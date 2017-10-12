#!/usr/bin/env python3
"""Slack bot for managing releases"""

import asyncio
from collections import namedtuple
from datetime import datetime
import os
import sys
import logging
import json
import re

import requests
from websockets.exceptions import ConnectionClosed
import websockets

from finish_release import finish_release
from release import (
    create_release_notes,
    init_working_dir,
    release,
    update_version,
)
from lib import (
    get_org_and_repo,
    get_release_pr,
    get_unchecked_authors,
    match_user,
    next_workday_at_10,
    release_manager_name,
    wait_for_checkboxes,
)
from wait_for_deploy import wait_for_deploy


RepoInfo = namedtuple('RepoInfo', [
    'repo_url',
    'rc_hash_url',
    'prod_hash_url',
    'channel_id',
])


log = logging.getLogger(__name__)


def in_script_dir(file_path):
    """
    Get absolute path for a file from within the script directory

    Args:
        file_path (str): The path of a file relative to the script directory

    Returns:
        str: The absolute path to that file
    """
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), file_path)


# pylint: disable=too-many-instance-attributes,too-many-arguments
class Bot:
    """Slack bot used to manage the release"""

    def __init__(self, websocket, access_token):
        """
        Create the slack bot

        Args:
            websocket (websockets.client.WebSocketClientProtocol): websocket for sending/receiving messages
            access_token (str): The OAuth access token used to interact with Slack
        """
        self.websocket = websocket
        self.access_token = access_token
        self.message_count = 0

    def lookup_users(self):
        """
        Get users list from slack
        """
        resp = requests.post("https://slack.com/api/users.list", data={
            "token": self.access_token
        })
        resp.raise_for_status()
        return resp.json()['members']

    def translate_slack_usernames(self, unchecked_authors):
        """
        Try to match each full name with a slack username.

        Args:
            unchecked_authors (iterable of str): An iterable of full names

        Returns:
            iterable of str:
                A iterable of either the slack name or a full name if a slack name was not found
        """
        try:
            slack_users = self.lookup_users()
            return [match_user(slack_users, author) for author in unchecked_authors]

        except Exception as exception:  # pylint: disable=broad-except
            sys.stderr.write("Error: {}".format(exception))
            return unchecked_authors

    async def say(self, channel_id, text):
        """
        Post a message in the Slack channel

        Args:
            channel_id (str): A channel id
            text (str): A message
        """
        await self.websocket.send(json.dumps({
            "id": self.message_count,
            "type": "message",
            "channel": channel_id,
            "text": text}))
        self.message_count += 1

    async def do_release(self, repo_info, version):
        """
        Start a new release and wait for deployment

        Args:
            repo_info (RepoInfo): Information for a repo
            version (str): The version
        """
        repo_url = repo_info.repo_url
        channel_id = repo_info.channel_id
        release(repo_url, version)

        await self.say(channel_id, "Behold, my new evil scheme - release {}! Now deploying to RC...".format(version))

        await wait_for_deploy(repo_url, repo_info.rc_hash_url, "release-candidate")
        org, repo = get_org_and_repo(repo_url)
        unchecked_authors = get_unchecked_authors(org, repo, version)
        slack_usernames = self.translate_slack_usernames(unchecked_authors)
        await self.say(
            channel_id,
            "Release {version} was deployed! PR is up at <{pr_url}|Release {version}>."
            " These people have commits in this release: {authors}".format(
                version=version,
                authors=", ".join(slack_usernames),
                pr_url=get_release_pr(org, repo, version)['html_url'],
            )
        )

    async def wait_for_checkboxes(self, repo_info, version):
        """
        Poll the Release PR and wait until all checkboxes are checked off

        Args:
            repo_info (RepoInfo): Information for a repo
            version (str): The version
        """
        channel_id = repo_info.channel_id
        await self.say(
            channel_id,
            "Wait, wait. Time out. My evil plan isn't evil enough until all the checkboxes are checked..."
        )
        org, repo = get_org_and_repo(repo_info.repo_url)
        await wait_for_checkboxes(org, repo, version)
        release_manager = release_manager_name()
        await self.say(
            channel_id,
            "All checkboxes checked off. Release {version} is ready for the Merginator{name}!".format(
                version=version,
                name=' {}'.format(self.translate_slack_usernames([release_manager])[0]) if release_manager else '',
            )
        )

    async def finish_release(self, repo_info, version):
        """
        Merge the release candidate into the release branch, tag it, merge to master, and wait for deployment

        Args:
            repo_info (RepoInfo): The info for a repo
            version (str): The version
        """
        channel_id = repo_info.channel_id
        repo_url = repo_info.repo_url
        finish_release(repo_url, version)

        await self.say(channel_id, "Merged evil scheme {}! Now deploying to production...".format(version))
        await wait_for_deploy(repo_url, repo_info.prod_hash_url, "release")
        await self.say(
            channel_id,
            "My evil scheme {} has been released to production. "
            "And by 'released', I mean completely...um...leased.".format(version)
        )

    async def commits_since_last_release(self, repo_info):
        """
        Have doof show the release notes since the last release

        Args:
            repo_info (RepoInfo): The info for a repo
        """
        with init_working_dir(repo_info.repo_url):
            last_version = update_version("9.9.9")

            release_notes = create_release_notes(last_version, with_checkboxes=False)
        await self.say(
            repo_info.channel_id,
            "Release notes since {version}...\n\n{notes}".format(
                version=last_version,
                notes=release_notes,
            ),
        )

    async def message_if_unchecked(self, repo_info, version):
        """
        Send a message next morning if any boxes are not yet checked off

        Args:
            repo_info (RepoInfo): Information for a repo
            version (str): The version of the release to check
        """
        org, repo = get_org_and_repo(repo_info.repo_url)
        unchecked_authors = get_unchecked_authors(org, repo, version)
        if unchecked_authors:
            slack_usernames = self.translate_slack_usernames(unchecked_authors)
            await self.say(
                repo_info.channel_id,
                "What an unexpected surprise! "
                "The following authors have not yet checked off their boxes: {}".format(
                    ", ".join(slack_usernames)
                )
            )

    async def delay_message(self, repo_info, version):
        """
        sleep until 10am next day, then message

        Args:
            repo_info (RepoInfo): The info for a repo
            version (str): The version number for the release
        """
        now = datetime.now()
        tomorrow_at_10 = next_workday_at_10(now)
        await asyncio.sleep((tomorrow_at_10 - now).total_seconds())
        await self.message_if_unchecked(repo_info, version)

    async def handle_message(self, channel_id, repo_info, words, loop):
        """
        Handle the message

        Args:
            channel_id (str): The channel id
            repo_info (RepoInfo): The repo info, if the channel id can be found for that repo
            words (list of str): the words making up a command
            loop (asyncio.events.AbstractEventLoop): The asyncio event loop
        """

        try:
            if has_command(['release', 'notes'], words):
                await self.commits_since_last_release(repo_info)
            elif has_command(['release'], words) or has_command(['start', 'release'], words):
                version = get_version_number(words[-1])

                loop.create_task(self.delay_message(repo_info, version))
                await self.do_release(repo_info, version)
                await self.wait_for_checkboxes(repo_info, version)
            elif has_command(['finish', 'release'], words):
                version = get_version_number(words[-1])

                await self.finish_release(repo_info, version)
            elif has_command(['wait', 'for', 'checkboxes'], words):
                version = get_version_number(words[-1])
                await self.wait_for_checkboxes(repo_info, version)
            elif has_command(['hi'], words):
                await self.say(
                    channel_id,
                    "A Mongol army? Really? Uh, I must have had the dial set for"
                    " 'Hun.' Oh, well, you don't look a gift horde in the mouth, so... hello! "
                )
            else:
                await self.say(channel_id, "Oooopps! Invalid command format")
        except BotException as ex:
            log.exception("A BotException was raised:")
            await self.say(channel_id, "Oops, something went wrong: {}".format(ex))
        except:  # pylint: disable=bare-except
            log.exception("Exception found when handling a message")
            await self.say(channel_id, "Oops, something went wrong...")


class BotException(Exception):
    """Exception raised for invalid input.

    Args:
        message (str): explanation of the error
    """
    def __init__(self, message):
        super().__init__(message)
        self.message = message


def get_version_number(text):
    """
    return version number at the end of the message

    Args:
        text (str): The word containing the version number

    Returns:
        str: The version if it parsed correctly
    """
    pattern = re.compile('^[0-9.]+$')
    if pattern.match(text):
        return text
    else:
        raise BotException("Invalid version number")


def has_command(command_words, input_words):
    """
    Check if words start the message

    Args:
        command_words (list of str):
            words making up the command we are looking for
        input_words (list of str):
            words making up the content of the message

    Returns:
        bool:
            True if this message is the given command
    """
    command_words = [word.lower() for word in command_words]
    input_words = [word.lower() for word in input_words]
    return command_words == input_words[:len(command_words)]


def main():
    """main function for bot command"""
    slack_access_token = os.environ.get('SLACK_ACCESS_TOKEN')
    if not slack_access_token:
        raise Exception("Missing SLACK_ACCESS_TOKEN")

    bot_access_token = os.environ.get('BOT_ACCESS_TOKEN')
    if not bot_access_token:
        raise Exception("Missing BOT_ACCESS_TOKEN")

    # these are temporary values for now
    repos_info = [
        RepoInfo(
            "git@github.com:mitodl/micromasters.git",
            "https://micromasters-rc.herokuapp.com/static/hash.txt",
            "https://micromasters.mit.edu/static/hash.txt",
            'G1VK0EDGA',
        ),
        RepoInfo(
            "git@github.com:mitodl/bootcamp-ecommerce.git",
            "https://bootcamp-ecommerce-rc.herokuapp.com/static/hash.txt",
            "https://bootcamp-ecommerce.mit.edu/static/hash.txt",
            'G49GL0CVA',
        ),
        RepoInfo(
            "git@github.com:mitodl/open-discussions.git",
            "https://odl-open-discussions-rc.herokuapp.com/static/hash.txt",
            "https://odl-open-discussions.herokuapp.com/static/hash.txt",
            'G5RHT8GDD',
        )
    ]

    resp = requests.post("https://slack.com/api/rtm.connect", data={
        "token": bot_access_token,
    })
    doof_id = resp.json()['self']['id']

    async def connect_to_message_server(loop):
        """Setup connection with websocket server"""
        async with websockets.connect(resp.json()['url']) as websocket:
            bot = Bot(websocket, slack_access_token)
            while True:
                message = await websocket.recv()
                print(message)
                message = json.loads(message)
                if message.get('type') != 'message':
                    continue

                content = message.get('text')
                if content is None:
                    continue

                channel_id = message.get('channel')
                channel_repo_info = None
                for repo_info in repos_info:
                    if repo_info.channel_id == channel_id:
                        channel_repo_info = repo_info

                all_words = content.strip().split()
                if len(all_words) > 0:
                    message_handle, *words = all_words
                    if message_handle in ("<@{}>".format(doof_id), "@doof"):
                        loop.create_task(
                            bot.handle_message(channel_id, channel_repo_info, words, loop)
                        )

    loop = asyncio.get_event_loop()
    while True:
        try:
            loop.run_until_complete(connect_to_message_server(loop))
        except ConnectionClosed:
            # wait 15 seconds then try again
            loop.run_until_complete(asyncio.sleep(15))


if __name__ == "__main__":
    main()
