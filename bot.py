#!/usr/bin/env python3
"""Slack bot for managing releases"""
import aiohttp
import asyncio
from collections import namedtuple
from datetime import datetime
import os
import sys
import logging
import json
import re

import pytz
from tornado.platform.asyncio import AsyncIOMainLoop
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
    format_user_id,
    match_user,
    now_in_utc,
    next_workday_at_10,
    parse_date,
    VERSION_RE,
    wait_for_checkboxes,
)
from repo_info import RepoInfo
from wait_for_deploy import (
    fetch_release_hash,
    wait_for_deploy,
)
from version import get_version_tag
from web import run_web_server


log = logging.getLogger(__name__)


CommandArgs = namedtuple('CommandArgs', ['channel_id', 'repo_info', 'args', 'loop', 'manager'])
Command = namedtuple('Command', ['command', 'parsers', 'command_func', 'description'])
Parser = namedtuple('Parser', ['func', 'description'])
FINISH_RELEASE_ID = 'finish_release'


async def get_channels_info(*, slack_access_token, client):
    """
    Get channel information from slack

    Args:
        slack_access_token (str): Used to authenticate with slack
        client (aiohttp.ClientSession): A session, used for HTTP requests

    Returns:
        dict: A map of channel names to channel ids
    """
    # public channels
    resp = await client.post("https://slack.com/api/channels.list", data={
        "token": slack_access_token
    })
    resp.raise_for_status()
    channels = resp.json()['channels']
    channels_map = {channel['name']: channel['id'] for channel in channels}

    # private channels
    resp = await client.post("https://slack.com/api/groups.list", data={
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
    required_keys = (
        'SLACK_ACCESS_TOKEN',
        'BOT_ACCESS_TOKEN',
        'GITHUB_ACCESS_TOKEN',
        'SLACK_WEBHOOK_TOKEN',
        'TIMEZONE',
        'PORT',
    )
    env_dict = {key: os.environ.get(key, None) for key in required_keys}
    missing_env_keys = [k for k, v in env_dict.items() if v is None]
    if missing_env_keys:
        raise Exception("Missing required env variable(s): {}".format(', '.join(missing_env_keys)))
    return env_dict


# pylint: disable=too-many-instance-attributes,too-many-arguments,too-many-public-methods
class Bot:
    """Slack bot used to manage the release"""

    def __init__(self, *, slack_access_token, github_access_token, timezone, repos_info, client):
        """
        Create the slack bot

        Args:
            slack_access_token (str): The OAuth access token used to interact with Slack
            github_access_token (str): The Github access token used to interact with Github
            timezone (tzinfo): The time zone of the team interacting with the bot
            repos_info (list of RepoInfo): Information about the repositories connected to channels
            client (aiohttp.ClientSession): The HTTP client session
        """
        self.slack_access_token = slack_access_token
        self.github_access_token = github_access_token
        self.timezone = timezone
        self.repos_info = repos_info
        self.client = client

    async def lookup_users(self):
        """
        Get users list from slack
        """
        resp = await self.client.post("https://slack.com/api/users.list", data={
            "token": self.slack_access_token
        })
        resp.raise_for_status()
        return resp.json()['members']

    async def translate_slack_usernames(self, names):
        """
        Try to match each full name with a slack username.

        Args:
            names (iterable of str): An iterable of full names

        Returns:
            iterable of str:
                A iterable of either the slack name or a full name if a slack name was not found
        """
        try:
            slack_users = await self.lookup_users()
            return [match_user(
                slack_users=slack_users,
                author_name=author,
            ) for author in names]

        except Exception as exception:  # pylint: disable=broad-except
            sys.stderr.write("Error: {}".format(exception))
            return names

    def get_repo_info(self, channel_id):
        """
        Get the repo info for a channel, or return None if no channel matches

        Args:
            channel_id (str): The channel id
        """
        for repo_info in self.repos_info:
            if repo_info.channel_id == channel_id:
                return repo_info
        return None

    async def say(self, *, channel_id, text=None, attachments=None, message_type=None):
        """
        Post a message in the Slack channel

        Args:
            channel_id (str): A channel id
            text (str): A message
            attachments (list of dict): Attachment information
            message_type (str): The type of message
        """
        attachments_dict = {"attachments": json.dumps(attachments)} if attachments else {}
        text_dict = {"text": text} if text else {}
        message_type_dict = {"type": message_type} if message_type else {}

        resp = await self.client.post('https://slack.com/api/chat.postMessage', data={
            "token": self.slack_access_token,
            "channel": channel_id,
            **text_dict,
            **attachments_dict,
            **message_type_dict,
        })
        resp.raise_for_status()

    async def update_message(self, *, channel_id, timestamp, text=None, attachments=None):
        """
        Update an existing message in slack

        Args:
            channel_id (str): The channel id
            timestamp (str): The timestamp of the message to update
            text (str): New text for the message
            attachments (list of dict): New attachments for the message
        """
        attachments_dict = {"attachments": json.dumps(attachments)} if attachments else {}
        text_dict = {"text": text} if text else {}

        resp = await self.client.post('https://slack.com/api/chat.update', data={
            "token": self.slack_access_token,
            "channel": channel_id,
            "ts": timestamp,
            **text_dict,
            **attachments_dict,
        })
        resp.raise_for_status()

    async def say_with_attachment(self, *, channel_id, title, text):
        """
        Post a message in the Slack channel, putting the text in an attachment with markdown enabled

        Args:
            channel_id (channel_id): A channel id
            title (str): A line of text before the main message
            text (str): A message
        """
        await self.say(
            channel_id=channel_id,
            text=title,
            attachments=[{
                "fallback": title,
                "text": text,
                "mrkdwn_in": ['text']
            }]
        )

    async def typing(self, channel_id):
        """
        Post a message in the Slack channel that Doof is typing something

        Args:
            channel_id (str): A channel id
        """
        await self.say(channel_id=channel_id, message_type="typing")

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
        pr = get_release_pr(
            github_access_token=self.github_access_token,
            org=org,
            repo=repo,
        )
        if pr:
            raise ReleaseException("A release is already in progress: {}".format(pr.url))
        release(
            github_access_token=self.github_access_token,
            repo_url=repo_url,
            new_version=version,
        )

        await self.say(
            channel_id=channel_id,
            text="Behold, my new evil scheme - release {version} for {project}! Now deploying to RC...".format(
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
        unchecked_authors = get_unchecked_authors(
            github_access_token=self.github_access_token,
            org=org,
            repo=repo,
        )
        slack_usernames = await self.translate_slack_usernames(unchecked_authors)
        pr = get_release_pr(
            github_access_token=self.github_access_token,
            org=org,
            repo=repo,
        )
        await self.say(
            channel_id=channel_id,
            text="Release {version} for {project} was deployed! PR is up at {pr_url}."
            " These people have commits in this release: {authors}".format(
                version=version,
                authors=", ".join(slack_usernames),
                pr_url=pr.url,
                project=repo_info.name,
            )
        )

        await self.wait_for_checkboxes(repo_info, command_args.manager)
        command_args.loop.create_task(self.delay_message(repo_info))

    async def wait_for_checkboxes_command(self, command_args):
        """
        Poll the Release PR and wait until all checkboxes are checked off

        Args:
            command_args (CommandArgs): The arguments for this command
        """
        await self.wait_for_checkboxes(command_args.repo_info, command_args.manager)

    async def wait_for_checkboxes(self, repo_info, manager):
        """
        Poll the Release PR and wait until all checkboxes are checked off

        Args:
            repo_info (RepoInfo): Information for a repo
            manager (str): User id for the release manager
        """
        channel_id = repo_info.channel_id
        await self.say(
            channel_id=channel_id,
            text="Wait, wait. Time out. My evil plan for {project} isn't evil enough "
            "until all the checkboxes are checked...".format(
                project=repo_info.name,
            )
        )
        org, repo = get_org_and_repo(repo_info.repo_url)
        await wait_for_checkboxes(self.github_access_token, org, repo)
        pr = get_release_pr(self.github_access_token, org, repo)
        await self.say(
            channel_id=channel_id,
            text="All checkboxes checked off. Release {version} is ready for the Merginator {name}!".format(
                name=format_user_id(manager),
                version=pr.version
            ),
            attachments=[
                {
                    "fallback": "Finish the release",
                    "callback_id": FINISH_RELEASE_ID,
                    "actions": [
                        {
                            "name": "finish_release",
                            "text": "Finish the release",
                            "type": "button",
                        }
                    ]
                }
            ]
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
            channel_id=channel_id,
            text="Merged evil scheme {version} for {project}! Now deploying to production...".format(
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
            channel_id=channel_id,
            text="My evil scheme {version} for {project} has been released to production. "
            "And by 'released', I mean completely...um...leased.".format(
                version=version,
                project=repo_info.name,
            )
        )

    async def report_version(self, command_args):
        """
        Report the version that is running in production

        Args:
            command_args (CommandArg): The arguments for this command
        """
        repo_info = command_args.repo_info
        channel_id = repo_info.channel_id
        repo_url = repo_info.repo_url

        commit_hash = fetch_release_hash(repo_info.prod_hash_url)

        version = get_version_tag(self.github_access_token, repo_url, commit_hash)
        await self.say(
            channel_id=channel_id,
            text="Wait a minute! My evil scheme is at version {version}!".format(version=version[1:])
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

        await self.say_with_attachment(
            channel_id=repo_info.channel_id,
            title="Release notes since {}".format(last_version),
            text=release_notes,
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
            slack_usernames = await self.translate_slack_usernames(unchecked_authors)
            await self.say(
                channel_id=repo_info.channel_id,
                text="What an unexpected surprise! "
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
        now = datetime.now(tz=self.timezone)
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

        title = "Pull request karma since {}".format(start_date)
        await self.say_with_attachment(
            channel_id=channel_id,
            title=title,
            text="\n".join(
                "*{name}*: {karma}".format(name=name, karma=karma)
                for name, karma in calculate_karma(self.github_access_token, start_date, now_in_utc().date())
            ),
        )

    async def needs_review(self, command_args):
        """
        Print out what PRs need review

        Args:
            command_args (CommandArgs): The arguments for this command
        """
        channel_id = command_args.channel_id
        title = "These PRs need review and are unassigned"
        await self.say_with_attachment(
            channel_id=channel_id,
            title=title,
            text="\n".join(
                "*{repo}*: {title}\n{url}".format(
                    repo=repo,
                    title=title,
                    url=url,
                ) for repo, title, url in
                needs_review(self.github_access_token)
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
            channel_id=channel_id,
            text="A Mongol army? Really? Uh, I must have had the dial set for"
            " 'Hun.' Oh, well, you don't look a gift horde in the mouth, so... hello! "
        )

    async def help(self, command_args):
        """
        List the commands the user can use

        Args:
            command_args (CommandArgs): The arguments for this command
        """
        channel_id = command_args.channel_id
        text = "\n".join("*{command}*{join}{parsers}: {description}".format(
            command=command,
            parsers=" ".join("*<{}>*".format(parser.description) for parser in parsers),
            join=" " if parsers else "",
            description=description,
        ) for command, parsers, _, description in sorted(self.make_commands()))
        title = (
            "Come on, Perry the Platypus. Let's go home. I talk to you enough, right? "
            "Yeah, you're right. Maybe too much."
        )
        await self.say_with_attachment(
            channel_id=channel_id,
            title=title,
            text=text,
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

    # pylint: disable=too-many-locals
    async def run_command(self, *, manager, channel_id, words, loop):
        """
        Run a command

        Args:
            manager (str): The user id for the person giving the command
            channel_id (str): The channel id
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
                        channel_id=channel_id,
                        text="Careful, careful. I expected {expected_num} words but you said {actual_num}.".format(
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
                            channel_id=channel_id,
                            text=(
                                "Oh dear! You said `{word}` but I'm having trouble"
                                " figuring out what that means.".format(
                                    word=arg,
                                )
                            )
                        )
                        return

                repo_info = self.get_repo_info(channel_id)
                await command_func(
                    CommandArgs(
                        repo_info=repo_info,
                        channel_id=channel_id,
                        args=parsed_args,
                        loop=loop,
                        manager=manager,
                    )
                )
                return

        # No command matched
        await self.say(
            channel_id=channel_id,
            text="You're both persistent, I'll give ya that, but the security system "
            "is offline and there's nothing you or your little dog friend can do about it!"
            " Y'know, unless, one of you happens to be really good with computers."
        )

    async def handle_message(self, *, manager, channel_id, words, loop):
        """
        Handle the message

        Args:
            manager (str): The user id for the person giving the command
            channel_id (str): The channel id
            words (list of str): the words making up a command
            loop (asyncio.events.AbstractEventLoop): The asyncio event loop
        """
        try:
            await self.run_command(
                manager=manager,
                channel_id=channel_id,
                words=words,
                loop=loop
            )
        except (InputException, ReleaseException) as ex:
            log.exception("A BotException was raised:")
            await self.say(channel_id=channel_id, text="Oops! {}".format(ex))
        except:  # pylint: disable=bare-except
            log.exception("Exception found when handling a message")
            await self.say(
                channel_id=channel_id,
                text="No! Perry the Platypus, don't do it! "
                     "Don't push the self-destruct button. This one right here.",
            )

    async def handle_webhook(self, *, webhook_dict, loop):
        """
        Handle a webhook coming from Slack. The payload has already been verified at this point.

        Args:
            webhook_dict (dict): The dict from Slack containing the webhook information
            loop (asyncio.events.AbstractEventLoop): The asyncio event loop
        """

        channel_id = webhook_dict['channel']['id']
        user_id = webhook_dict['user']['id']
        callback_id = webhook_dict['callback_id']
        timestamp = webhook_dict['message_ts']
        original_text = webhook_dict['original_message']['text']

        if callback_id == FINISH_RELEASE_ID:
            repo_info = self.get_repo_info(channel_id)
            await self.update_message(
                channel_id=channel_id,
                timestamp=timestamp,
                text=original_text,
                attachments=[{
                    "title": "Merging..."
                }],
            )
            try:
                await self.finish_release(CommandArgs(
                    channel_id=channel_id,
                    repo_info=repo_info,
                    args=[],
                    loop=loop,
                    manager=user_id,
                ))
            except:
                await self.update_message(
                    channel_id=channel_id,
                    timestamp=timestamp,
                    text=original_text,
                    attachments=[{
                        "title": "Error merging release"
                    }],
                )
                raise

        else:
            log.warning("Unknown callback id: %s", callback_id)


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


async def connect_to_message_server(
    *, rtm_url, doof_id, slack_access_token, slack_webhook_token,
    github_access_token, timezone, repos_info, port, client, loop
):
    """
    Setup connection with websocket server and handle messages

    Args:
        rtm_url (str): The URL for the websocket connection with Slack
        doof_id (str): The doof id
        slack_access_token (str): The slack access token
        slack_webhook_token (str): The slack webhook token
        github_access_token (str): The github access token
        timezone (datetime.tzinfo): A timezone object representing the team's time zone
        repos_info (list of RepoInfo): Repository information
        port (int): The port number for the webserver
        client (aiohttp.ClientSession): The HTTP client session
        loop (asyncio.events.AbstractEventLoop): The asyncio event loop
    """
    async with websockets.connect(rtm_url) as websocket:
        bot = Bot(
            slack_access_token=slack_access_token,
            github_access_token=github_access_token,
            timezone=timezone,
            repos_info=repos_info,
            client=client,
        )
        with run_web_server(
            token=slack_webhook_token,
            bot=bot,
            loop=loop,
            port=port,
        ):
            while True:
                message = await websocket.recv()
                print(message)
                message = json.loads(message)
                if message.get('type') != 'message':
                    continue

                if message.get('subtype') == 'message_changed':
                    # A user edits their message
                    # content = message.get('message', {}).get('text')
                    content = None
                else:
                    content = message.get('text')

                if content is None:
                    continue

                channel_id = message.get('channel')

                all_words = content.strip().split()
                if len(all_words) > 0:
                    message_handle, *words = all_words
                    if message_handle in ("<@{}>".format(doof_id), "@doof"):
                        print("handling...", words, channel_id)
                        loop.create_task(
                            bot.handle_message(
                                manager=message['user'],
                                channel_id=channel_id,
                                words=words,
                                loop=loop,
                            )
                        )


async def amain():
    """
    main function for bot command
    """
    envs = get_envs()
    loop = asyncio.get_event_loop()

    try:
        port = int(envs['PORT'])
    except ValueError:
        raise Exception("PORT is invalid")

    slack_access_token = envs['SLACK_ACCESS_TOKEN']
    slack_webhook_token = envs['SLACK_WEBHOOK_TOKEN']
    github_access_token = envs['GITHUB_ACCESS_TOKEN']
    timezone = pytz.timezone(envs['TIMEZONE'])

    async with aiohttp.ClientSession() as client:
        channels_info = await get_channels_info(
            client=client,
            slack_access_token=envs['SLACK_ACCESS_TOKEN'],
        )
        repos_info = load_repos_info(channels_info)

        resp = await client.post("https://slack.com/api/rtm.connect", data={
            "token": envs['BOT_ACCESS_TOKEN'],
        })
        resp.raise_for_status()
        rtm_url = resp.json()['url']
        doof_id = resp.json()['self']['id']

        # Start tornado and link it to the main event loop
        AsyncIOMainLoop().install()

        while True:
            try:
                await connect_to_message_server(
                    rtm_url=rtm_url,
                    doof_id=doof_id,
                    slack_access_token=slack_access_token,
                    slack_webhook_token=slack_webhook_token,
                    github_access_token=github_access_token,
                    timezone=timezone,
                    repos_info=repos_info,
                    port=port,
                    client=client,
                    loop=loop,
                )
            except ConnectionClosed:
                # wait 15 seconds then try again
                await asyncio.sleep(15)


if __name__ == "__main__":
    _loop = asyncio.get_event_loop()
    _loop.run_until_complete(amain())
