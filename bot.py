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

from exception import (
    InputException,
    ReleaseException,
)
from finish_release import finish_release
from github import (
    calculate_karma,
    get_org_and_repo,
    needs_review,
)
from release import (
    create_release_notes,
    init_working_dir,
    release,
    update_version,
    SCRIPT_DIR,
)
from lib import (
    get_release_pr,
    get_unchecked_authors,
    match_user,
    now_in_utc,
    next_workday_at_10,
    parse_date,
    release_manager_name,
    VERSION_RE,
    wait_for_checkboxes,
)
from repo_info import RepoInfo
from wait_for_deploy import (
    fetch_release_hash,
    wait_for_deploy,
)
from version import get_version_tag


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


CommandArgs = namedtuple('CommandArgs', ['channel_id', 'repo_info', 'args', 'loop'])
Command = namedtuple('Command', ['command', 'parsers', 'command_func', 'description'])
Parser = namedtuple('Parser', ['func', 'description'])


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

    async def typing(self, channel_id):
        """
        Post a message in the Slack channel that Doof is typing something

        Args:
            channel_id (str): A channel id
        """
        await self.websocket.send(json.dumps({
            "id": self.message_count,
            "type": "typing",
            "channel": channel_id
        }))
        self.message_count += 1

    async def release_command(self, command_args):
        """
        Start a new release and wait for deployment

        Args:
            command_args (CommandArgs): The arguments for this command
        """
        repo_info = command_args.repo_info
        version = command_args.args[0]
        repo_url = repo_info.repo_url
        channel_id = repo_info.channel_id
        org, repo = get_org_and_repo(repo_url)
        pr = get_release_pr(self.github_access_token, org, repo)
        if pr:
            raise ReleaseException("A release is already in progress: {}".format(pr.url))
        release(
            github_access_token=self.github_access_token,
            repo_url=repo_url,
            new_version=version,
        )

        await self.say(
            channel_id,
            "Behold, my new evil scheme - release {version} for {project}! Now deploying to RC...".format(
                version=version,
                project=repo_info.name,
            ),
        )

        await wait_for_deploy(
            github_access_token=self.github_access_token,
            repo_url=repo_url,
            hash_url=repo_info.rc_hash_url,
            watch_branch="release-candidate",
        )
        unchecked_authors = get_unchecked_authors(self.github_access_token, org, repo)
        slack_usernames = self.translate_slack_usernames(unchecked_authors)
        pr = get_release_pr(self.github_access_token, org, repo)
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

        await self.wait_for_checkboxes(repo_info)
        command_args.loop.create_task(self.delay_message(repo_info))

    async def wait_for_checkboxes_command(self, command_args):
        """
        Poll the Release PR and wait until all checkboxes are checked off

        Args:
            command_args (CommandArgs): The arguments for this command
        """
        await self.wait_for_checkboxes(command_args.repo_info)

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
        await wait_for_checkboxes(self.github_access_token, org, repo)
        release_manager = release_manager_name()
        pr = get_release_pr(self.github_access_token, org, repo)
        await self.say(
            channel_id,
            "All checkboxes checked off. Release {version} is ready for the Merginator{name}!".format(
                name=' {}'.format(self.translate_slack_usernames([release_manager])[0]) if release_manager else '',
                version=pr.version
            )
        )

    async def finish_release(self, command_args):
        """
        Merge the release candidate into the release branch, tag it, merge to master, and wait for deployment

        Args:
            command_args (CommandArgs): The arguments for this command
        """
        repo_info = command_args.repo_info
        channel_id = repo_info.channel_id
        repo_url = repo_info.repo_url
        org, repo = get_org_and_repo(repo_url)
        pr = get_release_pr(self.github_access_token, org, repo)
        if not pr:
            raise ReleaseException("No release currently in progress for {project}".format(project=repo_info.name))
        version = pr.version

        finish_release(
            github_access_token=self.github_access_token,
            repo_url=repo_url,
            version=version,
        )

        await self.say(
            channel_id,
            "Merged evil scheme {version} for {project}! Now deploying to production...".format(
                version=version,
                project=repo_info.name,
            ),
        )
        await wait_for_deploy(
            github_access_token=self.github_access_token,
            repo_url=repo_url,
            hash_url=repo_info.prod_hash_url,
            watch_branch="release",
        )
        await self.say(
            channel_id,
            "My evil scheme {version} for {project} has been released to production. "
            "And by 'released', I mean completely...um...leased.".format(
                version=version,
                project=repo_info.name,
            )
        )

    async def report_version(self, command_args):
        """
        Report the version that is running in production

        Args:
            command_args (RepoInfo): The arguments for this command
        """
        repo_info = command_args.repo_info
        channel_id = repo_info.channel_id
        repo_url = repo_info.repo_url

        commit_hash = fetch_release_hash(repo_info.prod_hash_url)

        version = get_version_tag(self.github_access_token, repo_url, commit_hash)
        await self.say(
            channel_id,
            "Wait a minute! My evil scheme is at version {version}!".format(version=version[1:])
        )

    async def commits_since_last_release(self, command_args):
        """
        Have doof show the release notes since the last release

        Args:
            command_args (CommandArgs): The arguments for this command
        """
        repo_info = command_args.repo_info
        with init_working_dir(self.github_access_token, repo_info.repo_url):
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
        unchecked_authors = get_unchecked_authors(self.github_access_token, org, repo)
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

    async def karma(self, command_args):
        """
        Print out PR karma for each user

        Args:
            command_args (CommandArgs): The arguments for this command
        """
        channel_id = command_args.channel_id
        start_date = command_args.args[0]

        await self.say(
            channel_id,
            "Pull request karma:\n{}".format(
                "\n".join(
                    "{name}: {karma}".format(name=name, karma=karma) for name, karma in
                    calculate_karma(self.github_access_token, start_date, now_in_utc().date())
                )
            )
        )

    async def needs_review(self, command_args):
        """
        Print out what PRs need review

        Args:
            command_args (CommandArgs): The arguments for this command
        """
        channel_id = command_args.channel_id
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

    async def hi(self, command_args):
        """
        Say hi

        Args:
            command_args (CommandArgs): The arguments for this command
        """
        channel_id = command_args.channel_id
        await self.say(
            channel_id,
            "A Mongol army? Really? Uh, I must have had the dial set for"
            " 'Hun.' Oh, well, you don't look a gift horde in the mouth, so... hello! "
        )

    async def help(self, command_args):
        """
        List the commands the user can use

        Args:
            command_args (CommandArgs): The arguments for this command
        """
        channel_id = command_args.channel_id
        descriptions = ["  *{command}*{join}{parsers}: {description}".format(
            command=command,
            parsers=" ".join("*<{}>*".format(parser.description) for parser in parsers),
            join=" " if parsers else "",
            description=description,
        ) for command, parsers, _, description in sorted(self.make_commands())]
        await self.say(
            channel_id,
            "Come on, Perry the Platypus. Let's go home. I talk to you enough, right? "
            "Yeah, you're right. Maybe too much.\n\n{}".format("\n".join(descriptions))
        )

    def make_commands(self):
        """
        Describe the commands which are available

        Returns:
            list of Command:
                A list of all commands available to use
        """
        return [
            Command(
                command='release notes',
                parsers=[],
                command_func=self.commits_since_last_release,
                description="Release notes since last release",
            ),
            Command(
                command='start release',
                parsers=[Parser(func=get_version_number, description='new version number')],
                command_func=self.release_command,
                description='Start a new release',
            ),
            Command(
                command='release',
                parsers=[Parser(func=get_version_number, description='new version number')],
                command_func=self.release_command,
                description='Start a new release',
            ),
            Command(
                command='finish release',
                parsers=[],
                command_func=self.finish_release,
                description='Finish a release',
            ),
            Command(
                command='wait for checkboxes',
                parsers=[],
                command_func=self.wait_for_checkboxes_command,
                description='Wait for committers to check off their boxes',
            ),
            Command(
                command='hi',
                parsers=[],
                command_func=self.hi,
                description='Say hi to doof',
            ),
            Command(
                command='karma',
                parsers=[Parser(func=parse_date, description='beginning date')],
                command_func=self.karma,
                description='Show pull request karma from a given date until today',
            ),
            Command(
                command='what needs review',
                parsers=[],
                command_func=self.needs_review,
                description='List pull requests which need review and are unassigned',
            ),
            Command(
                command='version',
                parsers=[],
                command_func=self.report_version,
                description='Show the version of the latest merged release',
            ),
            Command(
                command='help',
                parsers=[],
                command_func=self.help,
                description='Show available commands',
            ),
        ]

    async def run_command(self, channel_id, repo_info, words, loop):  # pylint: disable=too-many-locals
        """
        Run a command

        Args:
            channel_id (str): The channel id
            repo_info (RepoInfo): The repo info, if the channel id can be found for that repo
            words (list of str): the words making up a command
            loop (asyncio.events.AbstractEventLoop): The asyncio event loop
        """
        await self.typing(channel_id)
        commands = self.make_commands()
        for command, parsers, command_func, _ in commands:
            command_words = command.split()
            if has_command(command_words, words):
                args = words[len(command_words):]
                if len(args) != len(parsers):
                    await self.say(
                        channel_id,
                        "Careful, careful. I expected {expected_num} words but you said {actual_num}.".format(
                            expected_num=len(parsers),
                            actual_num=len(args),
                        )
                    )
                    return

                parsed_args = []
                for arg, parser in zip(args, parsers):
                    try:
                        parsed_args.append(parser.func(arg))
                    except:  # pylint: disable=bare-except
                        log.exception("Parser exception")
                        await self.say(
                            channel_id,
                            "Oh dear! You said `{word}` but I'm having trouble figuring out what that means.".format(
                                word=arg,
                            )
                        )
                        return

                await command_func(
                    CommandArgs(
                        repo_info=repo_info,
                        channel_id=channel_id,
                        args=[parser(arg) for arg, parser in zip(args, parsers)],
                        loop=loop,
                    )
                )
                return

        # No command matched
        await self.say(
            channel_id,
            "You're both persistent, I'll give ya that, but the security system "
            "is offline and there's nothing you or your little dog friend can do about it!"
            " Y'know, unless, one of you happens to be really good with computers."
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
            await self.run_command(channel_id, repo_info, words, loop)
        except (InputException, ReleaseException) as ex:
            log.exception("A BotException was raised:")
            await self.say(channel_id, "Oops! {}".format(ex))
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
    pattern = re.compile(VERSION_RE)
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
