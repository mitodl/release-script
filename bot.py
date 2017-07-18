#!/usr/bin/env python3
"""Slack bot for managing releases"""

import asyncio
from datetime import datetime
import os
from subprocess import check_output
import sys
import json
import re
import websockets

import requests

from finish_release import finish_release
from release import release
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
CHANNEL_ID = 'C67SGCU9H'


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

    def __init__(self, websocket, access_token, channel_mapping):
        """
        Create the slack bot

        Args:
            websocket (websockets.client.WebSocketClientProtocol): websocket for sending/receiving messages
            access_token (str): The OAuth access token used to interact with Slack
            channel_mapping (dict): Details for repos by channel_id
        """
        self.websocket = websocket
        self.access_token = access_token
        self.channel_id = CHANNEL_ID
        self.channel_mapping = channel_mapping
        channel_details = channel_mapping[self.channel_id]
        self.repo_dir = channel_details['repo_dir']

        self.org, self.repo = get_org_and_repo(self.repo_dir)
        self.rc_hash_url = channel_details['rc_hash_url']
        self.prod_hash_url = channel_details['prod_hash_url']
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

    async def say(self, text):
        """
        Post a message in the Slack channel

        Args:
            text (str): A message
        """
        await self.websocket.send(json.dumps({
            "id": self.message_count,
            "type": "message",
            "channel": self.channel_id,
            "text": text}))
        self.message_count += 1

    async def do_release(self, version):
        """
        Start a new release and wait for deployment
        """
        release(self.repo_url, self.version)

        await self.say("Behold, my new evil scheme - release {}! Now deploying to RC...".format(self.version))

        await wait_for_deploy(self.repo_url, self.rc_hash_url, "release-candidate")
        unchecked_authors = get_unchecked_authors(self.org, self.repo, self.version)
        slack_usernames = self.translate_slack_usernames(unchecked_authors)
        await self.say(
            "Release {version} was deployed! PR is up at <{pr_url}|Release {version}>."
            " These people have commits in this release: {authors}".format(
                version=version,
                authors=", ".join(slack_usernames),
                pr_url=self.pr_url(version),
            )
        )

    def pr_url(self, version):
        """Get URL for Release PR"""
        return get_release_pr(self.org, self.repo, version)['html_url']

    async def wait_for_checkboxes(self, version):
        """
        Poll the Release PR and wait until all checkboxes are checked off
        """
        await self.say("Wait, wait. Time out. My evil plan isn't evil enough until all the checkboxes are checked...")
        await wait_for_checkboxes(self.org, self.repo, version)
        release_manager = release_manager_name()
        await self.say("All checkboxes checked off. Release {version} is ready for the Merginator{name}!".format(
            version=version,
            name=' {}'.format(self.translate_slack_usernames([release_manager])[0]) if release_manager else '',
        ))

    async def finish_release(self, version):
        """
        Merge the release candidate into the release branch, tag it, merge to master, and wait for deployment
        """
        finish_release(self.repo_url, self.version)

        await self.say("Merged evil scheme {}! Now deploying to production...".format(self.version))
        await wait_for_deploy(self.repo_url, self.prod_hash_url, "release")
        await self.say(
            "My evil scheme {} has been released to production. "
            "And by 'released', I mean completely...um...leased.".format(version)
        )

    async def message_if_unchecked(self, version):
        """
        Send a message next morning if any boxes are not yet checked off
        """
        unchecked_authors = get_unchecked_authors(self.org, self.repo, version)
        if unchecked_authors:
            slack_usernames = self.translate_slack_usernames(unchecked_authors)
            await self.say(
                "What an unexpected surprise! "
                "The following authors have not yet checked off their boxes: {}".format(
                    ", ".join(slack_usernames)
                )
            )

    async def delay_message(self, version):
        """sleep until 10am next day, then message"""
        now = datetime.now()
        tomorrow_at_10 = next_workday_at_10(now)
        await asyncio.sleep((tomorrow_at_10 - now).total_seconds())
        await self.message_if_unchecked(version)

    async def handle_message(self, content, loop):
        """handle the message"""
        if has_command(['release'], content):
            try:
                version = get_version_number(content)
            except BotException as exception:
                await self.say("{}".format(exception))
            else:
                if has_command(['start', 'release'], content):
                    loop.create_task(self.delay_message(version))
                    await self.do_release(version)
                    await self.wait_for_checkboxes(version)
                elif has_command(['finish', 'release'], content):
                    await self.finish_release(version)
                else:
                    await self.say("Oooopps! Invalid command format")
        else:
            await self.say("Want to start a release? hhhmmmmm")


class BotException(Exception):
    """Exception raised for invalid input.

    Args:
        message: explanation of the error
    """
    def __init__(self, message):
        self.message = message


def get_version_number(content):
    """return version number at the end of the message"""
    pattern = re.compile('^[0-9.]+$')
    if pattern.match(content[-1]):
        return content[-1]
    else:
        raise BotException("Invalid version number")


def has_command(words, content):
    """Check if words are in the message"""
    for word in words:
        if word not in content:
            return False
    return True


def main():
    """main function for bot command"""
    slack_access_token = os.environ.get('SLACK_ACCESS_TOKEN')
    if not slack_access_token:
        raise Exception("Missing SLACK_ACCESS_TOKEN")

    bot_access_token = os.environ.get('BOT_ACCESS_TOKEN')
    if not bot_access_token:
        raise Exception("Missing BOT_ACCESS_TOKEN")

    # these are temporary values for now
    mm_urls = {
        'repo_dir': os.environ.get('REPO_DIR'),
        'rc_hash_url': "https://micromasters-rc.herokuapp.com/static/hash.txt",
        'prod_hash_url': "https://micromasters.mit.edu/static/hash.txt"
    }
    channel_mapping = {
        CHANNEL_ID: mm_urls
    }

    resp = requests.post("https://slack.com/api/rtm.connect", data={
        "token": bot_access_token,
    })
    doof_id = resp.json()['self']['id']

    async def connect_to_message_server(loop):
        """Setup connection with websocket server"""
        async with websockets.connect(resp.json()['url']) as websocket:
            bot = Bot(websocket, slack_access_token, channel_mapping)
            while True:
                message = await websocket.recv()
                print(message)
                message = json.loads(message)
                if message.get('type') == 'message':
                    content = message.get('text')
                    if content.startswith("<@{}>".format(doof_id)):
                        content = content.lower().split()[1:]
                        await bot.handle_message(content, loop)

    loop = asyncio.get_event_loop()
    loop.run_until_complete(connect_to_message_server(loop))


if __name__ == "__main__":
    main()
