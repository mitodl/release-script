#!/usr/bin/env python3
"""Slack bot for managing releases"""

import asyncio
from datetime import datetime
import os
import sys
import logging
import json
import re

from dateutil.parser import parse
import requests
from websockets.exceptions import ConnectionClosed
import websockets

from exception import (
    InputException,
    ReleaseException,
)
from finish_release import finish_release
from github import calculate_karma, needs_review
from release import (
    create_release_notes,
    init_working_dir,
    release,
    update_version,
    SCRIPT_DIR,
)
from lib import (
    get_org_and_repo,
    get_release_pr,
    get_unchecked_authors,
    match_user,
    now_in_utc,
    next_workday_at_10,
    release_manager_name,
    wait_for_checkboxes,
)
from repo_info import RepoInfo
from wait_for_deploy import wait_for_deploy


log = logging.getLogger(__name__)


def get_channels_info(slack_access_token):
    """
    Get channel information from slack

    Args:
        slack_access_token (str): Used to authenticate with slack

    Returns:
        dict: A map of channel names to channel ids
    """
    # public channels
    resp = requests.post("https://slack.com/api/channels.list", data={
        "token": slack_access_token
    })
    resp.raise_for_status()
    channels = resp.json()['channels']
    channels_map = {channel['name']: channel['id'] for channel in channels}

    # private channels
    resp = requests.post("https://slack.com/api/groups.list", data={
        "token": slack_access_token
    })
    resp.raise_for_status()
    groups = resp.json()['groups']
    groups_map = {group['name']: group['id'] for group in groups}

    return {**channels_map, **groups_map}


def load_repos_info(channel_lookup):
    """
    Load repo information from JSON and looks up channel ids for each repo

    Args:
        channel_lookup (dict): Map of channel names to channel ids

    Returns:
        list of RepoInfo: Information about the repositories
    """
    with open(os.path.join(SCRIPT_DIR, "repos_info.json")) as f:
        repos_info = json.load(f)
        return [
            RepoInfo(
                name=repo_info['name'],
                repo_url=repo_info['repo_url'],
                rc_hash_url=repo_info['rc_hash_url'],
                prod_hash_url=repo_info['prod_hash_url'],
                channel_id=channel_lookup[repo_info['channel_name']],
            ) for repo_info in repos_info['repos']
        ]


def in_script_dir(file_path):
    """
    Get absolute path for a file from within the script directory

    Args:
        file_path (str): The path of a file relative to the script directory

    Returns:
        str: The absolute path to that file
    """
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), file_path)


def get_envs():
    """Get required environment variables"""
    required_keys = ('SLACK_ACCESS_TOKEN', 'BOT_ACCESS_TOKEN', 'GITHUB_ACCESS_TOKEN')
    env_dict = {key: os.environ.get(key, None) for key in required_keys}
    missing_env_keys = [k for k, v in env_dict.items() if v is None]
    if missing_env_keys:
        raise Exception("Missing required env variable(s): {}".format(', '.join(missing_env_keys)))
    return env_dict


# pylint: disable=too-many-instance-attributes,too-many-arguments
class Bot:
    """Slack bot used to manage the release"""

    def __init__(self, websocket, slack_access_token, github_access_token):
        """
        Create the slack bot

        Args:
            websocket (websockets.client.WebSocketClientProtocol): websocket for sending/receiving messages
            slack_access_token (str): The OAuth access token used to interact with Slack
            github_access_token (str): The Github access token used to interact with Github
        """
        self.websocket = websocket
        self.slack_access_token = slack_access_token
        self.github_access_token = github_access_token
        self.message_count = 0

    def lookup_users(self):
        """
        Get users list from slack
        """
        resp = requests.post("https://slack.com/api/users.list", data={
            "token": self.slack_access_token
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
        org, repo = get_org_and_repo(repo_url)
        pr = get_release_pr(org, repo)
        if pr:
            raise ReleaseException("A release is already in progress: {}".format(pr.url))
        release(self.github_access_token, repo_url, version)

        await self.say(
            channel_id,
            "Behold, my new evil scheme - release {version} for {project}! Now deploying to RC...".format(
                version=version,
                project=repo_info.name,
            ),
        )

        await wait_for_deploy(repo_url, repo_info.rc_hash_url, "release-candidate")
        unchecked_authors = get_unchecked_authors(org, repo)
        slack_usernames = self.translate_slack_usernames(unchecked_authors)
        await self.say(
            channel_id,
            "Release {version} for {project} was deployed! PR is up at {pr_url}."
            " These people have commits in this release: {authors}".format(
                version=version,
                authors=", ".join(slack_usernames),
                pr_url=pr.url,
                project=repo_info.name,
            )
        )

    async def wait_for_checkboxes(self, repo_info):
        """
        Poll the Release PR and wait until all checkboxes are checked off

        Args:
            repo_info (RepoInfo): Information for a repo
        """
        channel_id = repo_info.channel_id
        await self.say(
            channel_id,
            "Wait, wait. Time out. My evil plan for {project} isn't evil enough "
            "until all the checkboxes are checked...".format(
                project=repo_info.name,
            )
        )
        org, repo = get_org_and_repo(repo_info.repo_url)
        await wait_for_checkboxes(org, repo)
        release_manager = release_manager_name()
        pr = get_release_pr(org, repo)
        await self.say(
            channel_id,
            "All checkboxes checked off. Release {version} is ready for the Merginator{name}!".format(
                name=' {}'.format(self.translate_slack_usernames([release_manager])[0]) if release_manager else '',
                version=pr.version
            )
        )

    async def finish_release(self, repo_info):
        """
        Merge the release candidate into the release branch, tag it, merge to master, and wait for deployment

        Args:
            repo_info (RepoInfo): The info for a repo
        """
        channel_id = repo_info.channel_id
        repo_url = repo_info.repo_url
        org, repo = get_org_and_repo(repo_url)
        pr = get_release_pr(org, repo)
        if not pr:
            raise ReleaseException("No release currently in progress for {project}".format(project=repo_info.name))
        version = pr.version

        finish_release(repo_url, version)

        await self.say(
            channel_id,
            "Merged evil scheme {version} for {project}! Now deploying to production...".format(
                version=version,
                project=repo_info.name,
            ),
        )
        await wait_for_deploy(repo_url, repo_info.prod_hash_url, "release")
        await self.say(
            channel_id,
            "My evil scheme {version} for {project} has been released to production. "
            "And by 'released', I mean completely...um...leased.".format(
                version=version,
                project=repo_info.name,
            )
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

    async def message_if_unchecked(self, repo_info):
        """
        Send a message next morning if any boxes are not yet checked off

        Args:
            repo_info (RepoInfo): Information for a repo
        """
        org, repo = get_org_and_repo(repo_info.repo_url)
        unchecked_authors = get_unchecked_authors(org, repo)
        if unchecked_authors:
            slack_usernames = self.translate_slack_usernames(unchecked_authors)
            await self.say(
                repo_info.channel_id,
                "What an unexpected surprise! "
                "The following authors have not yet checked off their boxes for {project}: {names}".format(
                    names=", ".join(slack_usernames),
                    project=repo_info.name,
                )
            )

    async def delay_message(self, repo_info):
        """
        sleep until 10am next day, then message

        Args:
            repo_info (RepoInfo): The info for a repo
        """
        now = datetime.now()
        tomorrow_at_10 = next_workday_at_10(now)
        await asyncio.sleep((tomorrow_at_10 - now).total_seconds())
        await self.message_if_unchecked(repo_info)

    async def karma(self, channel_id, start_date):
        """
        Print out PR karma for each user
        """
        await self.say(
            channel_id,
            "Pull request karma:\n{}".format(
                "\n".join(
                    "{name}: {karma}".format(name=name, karma=karma) for name, karma in
                    calculate_karma(self.github_access_token, start_date, now_in_utc().date())
                )
            )
        )

    async def needs_review(self, channel_id):
        """
        Print out what PRs need review
        """
        await self.say(
            channel_id,
            "These PRs need review and are unassigned:\n{}".format(
                "\n".join(
                    "{repo}: {title} {url}".format(
                        repo=repo,
                        title=title,
                        url=url,
                    ) for repo, title, url in
                    needs_review(self.github_access_token)
                )
            )
        )

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

                loop.create_task(self.delay_message(repo_info))
                await self.do_release(repo_info, version)
                await self.wait_for_checkboxes(repo_info)
            elif has_command(['finish', 'release'], words):
                await self.finish_release(repo_info)
            elif has_command(['wait', 'for', 'checkboxes'], words):
                await self.wait_for_checkboxes(repo_info)
            elif has_command(['hi'], words):
                await self.say(
                    channel_id,
                    "A Mongol army? Really? Uh, I must have had the dial set for"
                    " 'Hun.' Oh, well, you don't look a gift horde in the mouth, so... hello! "
                )
            elif has_command(['karma'], words):
                start_date = parse(words[1]).date()
                await self.karma(repo_info, start_date)
            elif has_command(['what', 'needs', 'review'], words):
                await self.needs_review(channel_id)
            else:
                await self.say(channel_id, "Oooopps! Invalid command format")
        except (InputException, ReleaseException) as ex:
            log.exception("A BotException was raised:")
            await self.say(channel_id, "Oops, something went wrong: {}".format(ex))
        except:  # pylint: disable=bare-except
            log.exception("Exception found when handling a message")
            await self.say(
                channel_id,
                "No! Perry the Platypus, don't do it! Don't push the self-destruct button. This one right here.",
            )


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
        raise InputException("Invalid version number")


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
    envs = get_envs()

    channels_info = get_channels_info(envs['SLACK_ACCESS_TOKEN'])
    repos_info = load_repos_info(channels_info)

    resp = requests.post("https://slack.com/api/rtm.connect", data={
        "token": envs['BOT_ACCESS_TOKEN'],
    })
    resp.raise_for_status()
    doof_id = resp.json()['self']['id']

    async def connect_to_message_server(loop):
        """Setup connection with websocket server"""
        async with websockets.connect(resp.json()['url']) as websocket:
            bot = Bot(websocket, envs['SLACK_ACCESS_TOKEN'], envs['GITHUB_ACCESS_TOKEN'])
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
