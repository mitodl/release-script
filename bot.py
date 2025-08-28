#!/usr/bin/env python3
# pylint: disable=too-many-lines
"""Slack bot for managing releases"""
import asyncio
from asyncio import sleep as async_sleep  # importing separately for simpler mocking
from collections import namedtuple
import os
import logging
import json
import re

import pytz
import sentry_sdk
import tornado

from client_wrapper import ClientWrapper
from constants import (
    ALL_CHECKBOXES_CHECKED,
    CI,
    DEPLOYED_TO_PROD,
    DEPLOYING_TO_PROD,
    DEPLOYING_TO_RC,
    WAITING_FOR_CHECKBOXES,
    FINISH_RELEASE_ID,
    NEW_RELEASE_ID,
    LIBRARY_TYPE,
    MINOR,
    NPM,
    PROD,
    RC,
    SETUPTOOLS,
    VALID_DEPLOYMENT_SERVER_TYPES,
    VALID_RELEASE_ALL_TYPES,
    WEB_APPLICATION_TYPE,
)
from exception import (
    InputException,
    ReleaseException,
    StatusException,
)
from finish_release import finish_release
from github import (
    get_org_and_repo,
    needs_review,
    set_release_label,
)
from release import (
    any_new_commits,
    create_release_notes,
    init_working_dir,
    release,
)
from lib import (
    get_default_branch,
    get_release_pr,
    get_unchecked_authors,
    format_user_id,
    load_repos_info,
    match_user,
    next_versions,
    now_in_utc,
    parse_text_matching_options,
    VERSION_RE,
    COMMIT_HASH_RE,
    remove_path_from_url,
)
from publish import publish
from slack import get_channels_info, get_doofs_id
from status import (
    format_status_for_repo,
    status_for_repo_last_pr,
    status_for_repo_new_commits,
)
from version import (
    get_commit_oneline_message,
    get_project_version,
    get_version_tag,
)
from wait_for_deploy import (
    fetch_release_hash,
    wait_for_deploy,
)
from web import make_app


log = logging.getLogger(__name__)


Task = namedtuple("Task", ["channel_id", "task"])
CommandArgs = namedtuple("CommandArgs", ["channel_id", "repo_info", "args", "manager"])
Command = namedtuple(
    "Command",
    ["command", "parsers", "command_func", "description", "supported_project_types"],
)
Parser = namedtuple("Parser", ["func", "description"])


def get_envs():
    """Get required environment variables"""
    required_keys = (
        "SLACK_ACCESS_TOKEN",
        "BOT_ACCESS_TOKEN",
        "GITHUB_ACCESS_TOKEN",
        "NPM_TOKEN",
        "SLACK_SECRET",
        "TIMEZONE",
        "PORT",
        "PYPI_USERNAME",
        "PYPI_PASSWORD",
        "PYPITEST_USERNAME",
        "PYPITEST_PASSWORD",
    )
    env_dict = {key: os.environ.get(key, None) for key in required_keys}
    missing_env_keys = [k for k, v in env_dict.items() if v is None]
    if missing_env_keys:
        raise Exception(
            f"Missing required env variable(s): {', '.join(missing_env_keys)}"
        )
    return env_dict


# pylint: disable=too-many-instance-attributes,too-many-arguments,too-many-public-methods
class Bot:
    """Slack bot used to manage the release"""

    def __init__(
        self,
        *,
        doof_id,
        slack_access_token,
        github_access_token,
        npm_token,
        timezone,
        repos_info,
    ):
        """
        Create the slack bot

        Args:
            doof_id (str): Doof's id
            slack_access_token (str): The OAuth access token used to interact with Slack
            github_access_token (str): The Github access token used to interact with Github
            npm_token (str): The NPM token to publish npm packages
            timezone (tzinfo): The time zone of the team interacting with the bot
            repos_info (list of RepoInfo): Information about the repositories connected to channels
        """
        self.doof_id = doof_id
        self.slack_access_token = slack_access_token
        self.github_access_token = github_access_token
        self.npm_token = npm_token
        self.timezone = timezone
        self.repos_info = repos_info
        # Keep track of long running or scheduled tasks
        self.tasks = set()
        self.doof_boot = now_in_utc()

    async def lookup_users(self):
        """
        Get users list from slack
        """
        client = ClientWrapper()
        resp = await client.post(
            "https://slack.com/api/users.list", data={"token": self.slack_access_token}
        )
        resp.raise_for_status()
        return resp.json()["members"]

    async def translate_slack_usernames(self, names):
        """
        Try to match each full name with a slack username.

        Args:
            names (iterable of str): An iterable of full names

        Returns:
            set of str:
                A iterable of either the slack name or a full name if a slack name was not found
        """
        try:
            slack_users = await self.lookup_users()
            return {match_user(slack_users, author) for author in names}

        except:  # pylint: disable=bare-except
            log.exception(
                "Exception during translate_slack_usernames, continuing with untranslated names..."
            )
            return set(names)

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

    async def _say(self, *, channel_id, text, attachments, message_type):
        """
        Post a message in a Slack channel

        Args:
            channel_id (str): A channel id
            text (str): A message
            attachments (list of dict): Attachment information
            message_type (str): The type of message
        """
        attachments_dict = (
            {"attachments": json.dumps(attachments)} if attachments else {}
        )
        text_dict = {"text": text} if text else {}
        message_type_dict = {"type": message_type} if message_type else {}

        client = ClientWrapper()
        resp = await client.post(
            "https://slack.com/api/chat.postMessage",
            data={
                "token": self.slack_access_token,
                "channel": channel_id,
                **text_dict,
                **attachments_dict,
                **message_type_dict,
            },
        )
        resp.raise_for_status()

    async def say(self, *, channel_id, text=None, attachments=None, message_type=None):
        """
        Post a message in the Slack channel

        Args:
            channel_id (str): A channel id
            text (str): A message
            attachments (list of dict): Attachment information
            message_type (str): The type of message
        """
        await self._say(
            channel_id=channel_id,
            text=text,
            attachments=attachments,
            message_type=message_type,
        )

    async def update_message(
        self, *, channel_id, timestamp, text=None, attachments=None
    ):
        """
        Update an existing message in slack

        Args:
            channel_id (str): The channel id
            timestamp (str): The timestamp of the message to update
            text (str): New text for the message
            attachments (list of dict): New attachments for the message
        """
        attachments_dict = (
            {"attachments": json.dumps(attachments)} if attachments else {}
        )
        text_dict = {"text": text} if text else {}

        client = ClientWrapper()
        resp = await client.post(
            "https://slack.com/api/chat.update",
            data={
                "token": self.slack_access_token,
                "channel": channel_id,
                "ts": timestamp,
                **text_dict,
                **attachments_dict,
            },
        )
        resp.raise_for_status()

    async def delete_message(self, *, channel_id, timestamp):
        """
        Deletes an existing message in slack

        Args:
            channel_id (str): The channel id
            timestamp (str): The timestamp of the message to update
        """
        client = ClientWrapper()
        resp = await client.post(
            "https://slack.com/api/chat.delete",
            data={
                "token": self.slack_access_token,
                "channel": channel_id,
                "ts": timestamp,
            },
        )
        resp.raise_for_status()

    async def say_with_attachment(self, *, channel_id, title, text, message_type=None):
        """
        Post a message in the Slack channel, putting the text in an attachment with markdown enabled

        Args:
            channel_id (channel_id): A channel id
            title (str): A line of text before the main message
            text (str): A message
            message_type (str): The type of message
        """
        await self.say(
            channel_id=channel_id,
            text=title,
            attachments=[{"fallback": title, "text": text, "mrkdwn_in": ["text"]}],
            message_type=message_type,
        )

    async def run_release_lifecycle(self, *, repo_info, manager, release_pr):
        """
        Look up the release step from the label, then continue release from that step

        Args:
            repo_info (RepoInfo): Info for a repository
            manager (str): Release manager
            release_pr (ReleasePR): Release pull request
        """
        status = await status_for_repo_last_pr(
            repo_info=repo_info,
            github_access_token=self.github_access_token,
            release_pr=release_pr,
        )

        # In general these functions should put things in this order:
        #  - polling and waiting at the beginning of the function
        #  - any actions like merging a branch
        #  - set label to next step
        #  - most speech by doof
        #  - call this function again to decide on the next step
        # The intention is that if a function terminates unexpectedly it
        # can start over with as little repeated speech/actions as possible.
        if status == DEPLOYING_TO_RC:
            await self._wait_for_deploy_rc(
                repo_info=repo_info, manager=manager, release_pr=release_pr
            )
        elif status == WAITING_FOR_CHECKBOXES:
            try:
                await self.wait_for_checkboxes(
                    repo_info=repo_info, manager=manager, release_pr=release_pr
                )
            except ReleaseException:
                # PR was probably closed
                pass
        elif status == ALL_CHECKBOXES_CHECKED:
            # Done, waiting for the release to finish
            pass
        elif status == DEPLOYING_TO_PROD:
            await self._wait_for_deploy_prod(
                repo_info=repo_info, manager=manager, release_pr=release_pr
            )
        elif status == DEPLOYED_TO_PROD:
            # all done
            pass

        # Give github some time to update label state
        await async_sleep(10)

    async def _library_release(self, *, repo_info, version):
        """Do a library release"""
        channel_id = repo_info.channel_id
        org, repo = get_org_and_repo(repo_info.repo_url)

        await release(
            github_access_token=self.github_access_token,
            repo_info=repo_info,
            new_version=version,
        )
        pr = await get_release_pr(
            github_access_token=self.github_access_token,
            org=org,
            repo=repo,
        )
        await self.say(
            channel_id=channel_id,
            text=(
                f"Behold, my new evil scheme - release {version} for {repo_info.name}! PR is up at {pr.url}. "
                f"Once all tests pass, finish the release."
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
                            "confirm": {
                                "title": "Are you sure?",
                                "ok_text": "Finish the release",
                                "dismiss_text": "Cancel",
                            },
                        }
                    ],
                }
            ],
        )

    async def _web_application_release(
        self, *, repo_info, version, hotfix_hash, manager
    ):
        """
        Do a web application release

        Args:
            repo_info (RepoInfo): Repository info for a release
            version (str): Version of a new release
            hotfix_hash (str or None):
                If present, treat this as a hotfix and use this for a commit hash.
                If None, this is not a hotfix.
            manager (str): Manager for the release
        """
        channel_id = repo_info.channel_id
        org, repo = get_org_and_repo(repo_info.repo_url)
        if hotfix_hash:
            await release(
                github_access_token=self.github_access_token,
                repo_info=repo_info,
                new_version=version,
                branch="release",
                commit_hash=hotfix_hash,
            )
            await self.say(
                channel_id=channel_id,
                text=f"Behold, my new evil scheme - hotfix release {version} "
                f"with commit {hotfix_hash}! Now deploying to RC...",
            )
        else:
            await release(
                github_access_token=self.github_access_token,
                repo_info=repo_info,
                new_version=version,
            )
            await self.say(
                channel_id=channel_id,
                text=f"Behold, my new evil scheme - release {version} for {repo_info.name}! Now deploying to RC...",
            )

        release_pr = await get_release_pr(
            github_access_token=self.github_access_token, org=org, repo=repo
        )
        await set_release_label(
            github_access_token=self.github_access_token,
            repo_url=repo_info.repo_url,
            pr_number=release_pr.number,
            label=DEPLOYING_TO_RC,
        )
        await self.run_release_lifecycle(
            repo_info=repo_info, manager=manager, release_pr=release_pr
        )

    async def _wait_for_deploy_with_alerts(
        self, *, repo_info, release_pr, hash_url, watch_branch
    ):
        """
        Wait for a deployment, but alert with a a timeout
        """
        repo_url = repo_info.repo_url
        channel_id = repo_info.channel_id
        timeout_seconds = 60 * 60

        while True:
            if await wait_for_deploy(
                github_access_token=self.github_access_token,
                repo_url=repo_url,
                hash_url=hash_url,
                watch_branch=watch_branch,
                timeout_seconds=timeout_seconds,
            ):
                break

            await self.say(
                channel_id=channel_id,
                text=(
                    f"Release {release_pr.version} for {repo_info.name} hasn't deployed yet."
                ),
            )
            # after the first failure, only alert every 24h
            timeout_seconds = 60 * 60 * 24

    async def _wait_for_deploy_rc(self, *, repo_info, manager, release_pr):
        """
        Check hash values to wait for deployment for RC
        """
        repo_url = repo_info.repo_url
        channel_id = repo_info.channel_id

        await self._wait_for_deploy_with_alerts(
            repo_info=repo_info,
            release_pr=release_pr,
            hash_url=repo_info.rc_hash_url,
            watch_branch="release-candidate",
        )

        rc_server = remove_path_from_url(repo_info.rc_hash_url)

        await set_release_label(
            github_access_token=self.github_access_token,
            repo_url=repo_url,
            pr_number=release_pr.number,
            label=WAITING_FOR_CHECKBOXES,
        )
        await self.say(
            channel_id=channel_id,
            text=(
                f"Release {release_pr.version} for {repo_info.name} was deployed at {rc_server}!"
            ),
        )
        await self._wait_for_checkboxes_initial_message(
            repo_info=repo_info, release_pr=release_pr
        )
        await self.run_release_lifecycle(
            repo_info=repo_info, manager=manager, release_pr=release_pr
        )

    async def _wait_for_deploy_prod(self, *, repo_info, manager, release_pr):
        """
        Check hash values to wait for deployment for production
        """
        repo_url = repo_info.repo_url
        channel_id = repo_info.channel_id
        version = await get_version_tag(
            github_access_token=self.github_access_token,
            repo_url=repo_url,
            commit_hash="origin/release",
        )

        await self._wait_for_deploy_with_alerts(
            repo_info=repo_info,
            release_pr=release_pr,
            hash_url=repo_info.prod_hash_url,
            watch_branch="release",
        )

        await set_release_label(
            github_access_token=self.github_access_token,
            repo_url=repo_url,
            pr_number=release_pr.number,
            label=DEPLOYED_TO_PROD,
        )

        prod_server = remove_path_from_url(repo_info.prod_hash_url)

        await self.say(
            channel_id=channel_id,
            text=(
                f"My evil scheme {version} for {repo_info.name} has been released to production at {prod_server}. "
                "And by 'released', I mean completely...um...leased."
            ),
        )
        await self.run_release_lifecycle(
            repo_info=repo_info, manager=manager, release_pr=release_pr
        )

    async def _new_release(self, *, repo_info, version, manager):
        """
        Start a new release

        Args:
            repo_info (RepoInfo): Repository information for the release
            version (str): The version of the new release
            manager (str): Person starting a release
        """
        if repo_info.project_type == LIBRARY_TYPE:
            await self._library_release(repo_info=repo_info, version=version)
        elif repo_info.project_type == WEB_APPLICATION_TYPE:
            await self._web_application_release(
                repo_info=repo_info, version=version, hotfix_hash=None, manager=manager
            )
        else:
            raise Exception(
                f"Configuration error: unknown project type {repo_info.project_type}"
            )

    async def release_command(self, command_args):
        """
        Start a new release and wait for deployment

        Args:
            command_args (CommandArgs): The arguments for this command
        """
        repo_info = command_args.repo_info
        version = command_args.args[0]
        repo_url = repo_info.repo_url
        org, repo = get_org_and_repo(repo_url)
        pr = await get_release_pr(
            github_access_token=self.github_access_token,
            org=org,
            repo=repo,
        )
        if pr:
            raise ReleaseException(f"A release is already in progress: {pr.url}")

        await self._new_release(
            repo_info=repo_info, version=version, manager=command_args.manager
        )

    async def hotfix_command(self, command_args):
        """
        Start a hotfix with the commit hash provided

        Args:
            command_args (CommandArgs): The arguments for this command
        """
        repo_info = command_args.repo_info
        hotfix_hash = command_args.args[0]
        repo_url = repo_info.repo_url
        org, repo = get_org_and_repo(repo_url)

        release_pr = await get_release_pr(
            github_access_token=self.github_access_token, org=org, repo=repo
        )
        if release_pr:
            await self.say(
                channel_id=repo_info.channel_id,
                text=f"There is a release already in progress: {release_pr.url}. Close that first!",
            )
            raise ReleaseException(
                f"There is a release already in progress: {release_pr.url}. Close that first!"
            )

        async with init_working_dir(
            self.github_access_token, repo_info.repo_url
        ) as working_dir:
            last_version = await get_project_version(
                repo_info=repo_info, working_dir=working_dir
            )

        _, new_patch = next_versions(last_version)

        await self._web_application_release(
            repo_info=repo_info,
            version=new_patch,
            hotfix_hash=hotfix_hash,
            manager=command_args.manager,
        )

    async def wait_for_checkboxes_command(self, command_args):
        """
        Poll the Release PR and wait until all checkboxes are checked off

        Args:
            command_args (CommandArgs): The arguments for this command
        """
        repo_info = command_args.repo_info
        org, repo = get_org_and_repo(repo_info.repo_url)
        release_pr = await get_release_pr(
            github_access_token=self.github_access_token,
            org=org,
            repo=repo,
        )
        await set_release_label(
            github_access_token=self.github_access_token,
            repo_url=command_args.repo_info.repo_url,
            pr_number=release_pr.number,
            label=WAITING_FOR_CHECKBOXES,
        )
        await self._wait_for_checkboxes_initial_message(
            repo_info=repo_info, release_pr=release_pr
        )
        await self.run_release_lifecycle(
            repo_info=command_args.repo_info,
            manager=command_args.manager,
            release_pr=release_pr,
        )

    async def _wait_for_checkboxes_initial_message(self, *, repo_info, release_pr):
        """
        Find out who hasn't checked their boxes and message the channel

        Args:
            repo_info (RepoInfo): Repo info
            release_pr (ReleasePR): The release PR
        """
        org, repo = get_org_and_repo(repo_info.repo_url)
        channel_id = repo_info.channel_id
        prev_unchecked_authors = await get_unchecked_authors(
            github_access_token=self.github_access_token,
            org=org,
            repo=repo,
        )
        await self.say(
            channel_id=channel_id,
            text=(
                f"PR is up at {release_pr.url}."
                f" These people have commits in this release: "
                f"{', '.join(await self.translate_slack_usernames(prev_unchecked_authors))}"
            ),
        )
        await self.say(
            channel_id=channel_id,
            text=(
                f"Wait, wait. Time out. My evil plan for {repo_info.name} isn't evil enough "
                "until all the checkboxes are checked..."
            ),
        )

    async def wait_for_checkboxes(self, *, repo_info, manager, release_pr):
        """
        Poll the Release PR and wait until all checkboxes are checked off

        Args:
            repo_info (RepoInfo): Information for a repo
            manager (str or None): User id for the release manager
            release_pr (ReleasePR): Release PR
        """
        repo_url = repo_info.repo_url
        channel_id = repo_info.channel_id
        org, repo = get_org_and_repo(repo_url)
        prev_unchecked_authors = await get_unchecked_authors(
            github_access_token=self.github_access_token,
            org=org,
            repo=repo,
        )

        while prev_unchecked_authors:
            await async_sleep(60)

            new_unchecked_authors = await get_unchecked_authors(
                github_access_token=self.github_access_token,
                org=org,
                repo=repo,
            )

            newly_checked = prev_unchecked_authors - new_unchecked_authors
            if newly_checked:
                await self.say(
                    channel_id=channel_id,
                    text=f"Thanks for checking off your boxes "
                    f"{', '.join(sorted(await self.translate_slack_usernames(newly_checked)))}!",
                )
            prev_unchecked_authors = new_unchecked_authors

        await set_release_label(
            github_access_token=self.github_access_token,
            repo_url=repo_url,
            pr_number=release_pr.number,
            label=ALL_CHECKBOXES_CHECKED,
        )
        pr = await get_release_pr(
            github_access_token=self.github_access_token,
            org=org,
            repo=repo,
        )
        await self.say(
            channel_id=channel_id,
            text=f"All checkboxes checked off. Release {pr.version} is ready for the Merginator{' ' + format_user_id(manager) if manager else ''}!",
            attachments=[
                {
                    "fallback": "Finish the release",
                    "callback_id": FINISH_RELEASE_ID,
                    "actions": [
                        {
                            "name": "finish_release",
                            "text": "Finish the release",
                            "type": "button",
                            "confirm": {
                                "title": "Are you sure?",
                                "ok_text": "Finish the release",
                                "dismiss_text": "Cancel",
                            },
                        }
                    ],
                }
            ],
        )

    async def publish(self, command_args):
        """
        Publish a package to PyPI or NPM

        Args:
            command_args (CommandArgs): The arguments for this command
        """
        repo_info = command_args.repo_info
        version = command_args.args[0]

        if repo_info.packaging_tool == NPM:
            server = "the npm registry"
        elif repo_info.packaging_tool == SETUPTOOLS:
            server = "PyPI"
        else:
            raise Exception(
                f"Unexpected packaging tool {repo_info.packaging_tool} for {repo_info.name}"
            )

        await self.say(
            channel_id=command_args.channel_id,
            text=f"Publishing evil scheme {version} to {server}...",
        )
        await publish(
            repo_info=repo_info,
            version=version,
            github_access_token=self.github_access_token,
            npm_token=self.npm_token,
        )

        await self.say(
            channel_id=command_args.channel_id,
            text=f"Successfully uploaded {version} to {server}.",
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
        pr = await get_release_pr(
            github_access_token=self.github_access_token,
            org=org,
            repo=repo,
        )
        if not pr:
            raise ReleaseException(
                f"No release currently in progress for {repo_info.name}"
            )
        version = pr.version

        await finish_release(
            github_access_token=self.github_access_token,
            repo_info=repo_info,
            version=version,
            timezone=self.timezone,
        )

        if repo_info.project_type == WEB_APPLICATION_TYPE:
            await self.say(
                channel_id=channel_id,
                text=f"Merged evil scheme {version} for {repo_info.name}! Now deploying to production...",
            )
            await set_release_label(
                github_access_token=self.github_access_token,
                repo_url=repo_url,
                pr_number=pr.number,
                label=DEPLOYING_TO_PROD,
            )
            await self.run_release_lifecycle(
                repo_info=repo_info, manager=command_args.manager, release_pr=pr
            )
        elif repo_info.project_type == LIBRARY_TYPE:
            await self.say(
                channel_id=channel_id,
                text=f"Merged evil scheme {version} for {repo_info.name}!",
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

        commit_hash = await fetch_release_hash(repo_info.prod_hash_url)

        version = await get_version_tag(
            github_access_token=self.github_access_token,
            repo_url=repo_url,
            commit_hash=commit_hash,
        )
        await self.say(
            channel_id=channel_id,
            text=f"Wait a minute! My evil scheme is at version {version[1:]}!",
        )

    async def report_hash(self, command_args):
        """
        Report the commit that is deployed on a server

        Args:
            command_args (CommandArg): The arguments for this command
        """
        repo_info = command_args.repo_info
        channel_id = repo_info.channel_id
        repo_url = repo_info.repo_url
        deployment_server_type = command_args.args[0]

        if deployment_server_type == CI:
            hash_url = repo_info.ci_hash_url
        elif deployment_server_type == RC:
            hash_url = repo_info.rc_hash_url
        elif deployment_server_type == PROD:
            hash_url = repo_info.prod_hash_url
        else:
            raise Exception("Unexpected server type")

        commit_hash = await fetch_release_hash(hash_url)
        message = await get_commit_oneline_message(
            github_access_token=self.github_access_token,
            repo_url=repo_url,
            commit_hash=commit_hash,
        )
        await self.say(
            channel_id=channel_id,
            text=f"Oh, Perry the Platypus, look what you've done on {deployment_server_type}! {message}",
        )

    async def commits_since_last_release(self, command_args):
        """
        Have doof show the release notes since the last release

        Args:
            command_args (CommandArgs): The arguments for this command
        """
        repo_info = command_args.repo_info
        async with init_working_dir(
            self.github_access_token, repo_info.repo_url
        ) as working_dir:
            default_branch = await get_default_branch(working_dir)
            last_version = await get_project_version(
                repo_info=repo_info, working_dir=working_dir
            )

            release_notes = await create_release_notes(
                last_version,
                with_checkboxes=False,
                base_branch=default_branch,
                root=working_dir,
            )
            has_new_commits = await any_new_commits(
                last_version, base_branch=default_branch, root=working_dir
            )

        await self.say_with_attachment(
            channel_id=repo_info.channel_id,
            title=f"Release notes since {last_version}",
            text=release_notes,
        )

        org, repo = get_org_and_repo(repo_info.repo_url)
        release_pr = await get_release_pr(
            github_access_token=self.github_access_token, org=org, repo=repo
        )
        if release_pr:
            await self.say(
                channel_id=repo_info.channel_id,
                text=f"And also! There is a release already in progress: {release_pr.url}",
            )
        elif has_new_commits:
            new_minor, new_patch = next_versions(last_version)
            await self.say(
                channel_id=repo_info.channel_id,
                text="Start a new release?",
                attachments=[
                    {
                        "fallback": "New release",
                        "callback_id": NEW_RELEASE_ID,
                        "actions": [
                            {
                                "name": "minor_release",
                                "text": new_minor,
                                "value": new_minor,
                                "type": "button",
                            },
                            {
                                "name": "patch_release",
                                "text": new_patch,
                                "value": new_patch,
                                "type": "button",
                            },
                            {
                                "name": "cancel",
                                "text": "Dismiss",
                                "value": "cancel",
                                "style": "danger",
                                "type": "button",
                            },
                        ],
                    }
                ],
            )

    async def start_new_releases(self, command_args):  # pylint: disable=too-many-locals
        """
        Start new releases for all projects with new commits

        Args:
            command_args (CommandArgs): The arguments for this command
        """
        new_release_type = command_args.args[0]

        await self.say(
            channel_id=command_args.channel_id, text="Starting new releases..."
        )
        new_release_repos = []
        for repo_info in self.repos_info:
            try:
                org, repo = get_org_and_repo(repo_info.repo_url)
                release_pr = await get_release_pr(
                    github_access_token=self.github_access_token,
                    org=org,
                    repo=repo,
                )
                if release_pr:
                    # release already in progress, skip
                    continue

                async with init_working_dir(
                    self.github_access_token, repo_info.repo_url
                ) as working_dir:
                    last_version = await get_project_version(
                        repo_info=repo_info, working_dir=working_dir
                    )
                    default_branch = await get_default_branch(working_dir)
                    has_new_commits = await any_new_commits(
                        last_version, base_branch=default_branch, root=working_dir
                    )
                    if not has_new_commits:
                        # Nothing to release
                        continue
                    release_notes = await create_release_notes(
                        last_version,
                        with_checkboxes=False,
                        base_branch=default_branch,
                        root=working_dir,
                    )

                new_release_repos.append(repo_info.name)
                minor, patch = next_versions(last_version)
                version = minor if new_release_type == MINOR else patch
                await self.say_with_attachment(
                    channel_id=repo_info.channel_id,
                    title=f"Starting release {version} with these commits",
                    text=release_notes,
                )
                asyncio.create_task(
                    self._new_release(
                        repo_info=repo_info,
                        version=version,
                        manager=command_args.manager,
                    )
                )
            except Exception as ex:
                raise ReleaseException(
                    f"Error when identifying release status or starting release for {repo_info.name}"
                ) from ex
        if new_release_repos:
            await self.say(
                channel_id=command_args.channel_id,
                text=f"Started new releases for {', '.join(new_release_repos)}",
            )
        else:
            await self.say(
                channel_id=command_args.channel_id, text="No new releases needed"
            )

    async def status(self, command_args):
        """Show the status of all repos"""
        await self.say(
            channel_id=command_args.channel_id, text="Calculating release statuses..."
        )

        sorted_repos_info = sorted(
            self.repos_info, key=lambda _repo_info: _repo_info.name
        )

        no_news = []
        text = ""
        for repo_info in sorted_repos_info:
            try:
                org, repo = get_org_and_repo(repo_info.repo_url)
                release_pr = await get_release_pr(
                    github_access_token=self.github_access_token,
                    org=org,
                    repo=repo,
                    all_prs=True,
                )
                status = await status_for_repo_last_pr(
                    github_access_token=self.github_access_token,
                    repo_info=repo_info,
                    release_pr=release_pr,
                )
                has_new_commits = await status_for_repo_new_commits(
                    github_access_token=self.github_access_token,
                    repo_info=repo_info,
                    release_pr=release_pr,
                )
                status_string = format_status_for_repo(
                    current_status=status, has_new_commits=has_new_commits
                )
                if status_string:
                    text += f"*{repo_info.name}*: {status_string}\n"
                else:
                    no_news.append(repo_info.name)
            except Exception as ex:
                raise StatusException(
                    f"Error calculating release status for {repo_info.name}"
                ) from ex
        if no_news:
            text += f"Nothing new for {', '.join(no_news)}"

        await self.say_with_attachment(
            channel_id=command_args.channel_id,
            title="Release statuses:",
            text=text,
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
                f"*{repo}*: {title}\n{url}"
                for repo, title, url in await needs_review(self.github_access_token)
            ),
        )

    async def uptime(self, command_args):
        """
        Say how long the bot has been running

        Args:
            command_args (CommandArgs): The arguments for this command
        """
        uptime = (now_in_utc() - self.doof_boot).total_seconds() / 60
        await self.say(
            channel_id=command_args.channel_id,
            text=f"Awake for {int(uptime)} minutes. "
            f"Oh, man. This had better be a dream because I don't like where this is going.",
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
            " 'Hun.' Oh, well, you don't look a gift horde in the mouth, so... hello! ",
        )

    async def help(self, command_args):
        """
        List the commands the user can use

        Args:
            command_args (CommandArgs): The arguments for this command
        """
        channel_id = command_args.channel_id
        text = "\n".join(
            f"*{command.command}*{' ' if command.parsers else ''}{' '.join(f'*<{parser.description}>*' for parser in command.parsers)}: {command.description}"
            for command in sorted(self.make_commands())
        )
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
                command="release notes",
                parsers=[],
                command_func=self.commits_since_last_release,
                description="Release notes since last release",
                supported_project_types=[LIBRARY_TYPE, WEB_APPLICATION_TYPE],
            ),
            Command(
                command="start release",
                parsers=[
                    Parser(func=get_version_number, description="new version number")
                ],
                command_func=self.release_command,
                description="Start a new release",
                supported_project_types=[LIBRARY_TYPE, WEB_APPLICATION_TYPE],
            ),
            Command(
                command="start new releases",
                parsers=[
                    Parser(
                        func=parse_text_matching_options(VALID_RELEASE_ALL_TYPES),
                        description="how to increment version for the next release (either 'minor' or 'patch')",
                    )
                ],
                command_func=self.start_new_releases,
                description="Start new releases for all projects which have new commits",
                supported_project_types=None,
            ),
            Command(
                command="release",
                parsers=[
                    Parser(func=get_version_number, description="new version number")
                ],
                command_func=self.release_command,
                description="Start a new release",
                supported_project_types=[LIBRARY_TYPE, WEB_APPLICATION_TYPE],
            ),
            Command(
                command="hotfix",
                parsers=[
                    Parser(
                        func=get_commit_hash, description="commit hash to cherry-pick"
                    )
                ],
                command_func=self.hotfix_command,
                description="Start a hotfix release",
                supported_project_types=[WEB_APPLICATION_TYPE],
            ),
            Command(
                command="finish release",
                parsers=[],
                command_func=self.finish_release,
                description="Finish a release",
                supported_project_types=[WEB_APPLICATION_TYPE, LIBRARY_TYPE],
            ),
            Command(
                command="wait for checkboxes",
                parsers=[],
                command_func=self.wait_for_checkboxes_command,
                description="Wait for committers to check off their boxes",
                supported_project_types=[WEB_APPLICATION_TYPE],
            ),
            Command(
                command="publish",
                parsers=[
                    Parser(
                        func=get_version_number,
                        description="version number of package to publish",
                    )
                ],
                command_func=self.publish,
                description="Publish a package to PyPI or NPM",
                supported_project_types=[LIBRARY_TYPE],
            ),
            Command(
                command="status",
                parsers=[],
                command_func=self.status,
                description="Show the status of repos managed by doof",
                supported_project_types=None,
            ),
            Command(
                command="hi",
                parsers=[],
                command_func=self.hi,
                description="Say hi to doof",
                supported_project_types=None,
            ),
            Command(
                command="what needs review",
                parsers=[],
                command_func=self.needs_review,
                description="List pull requests which need review and are unassigned",
                supported_project_types=None,
            ),
            Command(
                command="uptime",
                parsers=[],
                command_func=self.uptime,
                description="Shows how long this bot has been running",
                supported_project_types=None,
            ),
            Command(
                command="version",
                parsers=[],
                command_func=self.report_version,
                description="Show the version of the latest merged release",
                supported_project_types=[WEB_APPLICATION_TYPE],
            ),
            Command(
                command="hash",
                parsers=[
                    Parser(
                        func=parse_text_matching_options(VALID_DEPLOYMENT_SERVER_TYPES),
                        description=f"version type (one of {', '.join(VALID_DEPLOYMENT_SERVER_TYPES)})",
                    )
                ],
                command_func=self.report_hash,
                description="Show the latest commit deployed on a server",
                supported_project_types=[WEB_APPLICATION_TYPE],
            ),
            Command(
                command="help",
                parsers=[],
                command_func=self.help,
                description="Show available commands",
                supported_project_types=None,
            ),
        ]

    # pylint: disable=too-many-locals
    async def run_command(self, *, manager, channel_id, words):
        """
        Run a command

        Args:
            manager (str): The user id for the person giving the command
            channel_id (str): The channel id
            words (list of str): the words making up a command
        """
        for command in self.make_commands():
            command_words = command.command.split()
            if has_command(command_words, words):
                args = words[len(command_words) :]
                if len(args) != len(command.parsers):
                    await self.say(
                        channel_id=channel_id,
                        text=f"Careful, careful. I expected {len(command.parsers)} words but you said {len(args)}.",
                    )
                    return

                parsed_args = []
                for arg, parser in zip(args, command.parsers):
                    try:
                        parsed_args.append(parser.func(arg))
                    except:  # pylint: disable=bare-except
                        await self.say(
                            channel_id=channel_id,
                            text=(
                                f"Oh dear! You said `{arg}` but I'm having trouble"
                                " figuring out what that means."
                            ),
                        )
                        return

                repo_info = self.get_repo_info(channel_id)
                if command.supported_project_types is not None:
                    if repo_info is None:
                        await self.say(
                            channel_id=channel_id,
                            text="That command requires a repo but this channel is not attached to any project.",
                        )
                        return

                    if repo_info.project_type not in command.supported_project_types:
                        await self.say(
                            channel_id=channel_id,
                            text=(
                                f"That command is only for {', '.join(command.supported_project_types)} projects but "
                                f"this is a {repo_info.project_type} project."
                            ),
                        )
                        return
                await command.command_func(
                    CommandArgs(
                        repo_info=repo_info,
                        channel_id=channel_id,
                        args=parsed_args,
                        manager=manager,
                    )
                )
                return

        # No command matched
        await self.say(
            channel_id=channel_id,
            text="You're both persistent, I'll give ya that, but the security system "
            "is offline and there's nothing you or your little dog friend can do about it!"
            " Y'know, unless, one of you happens to be really good with computers.",
        )

    async def handle_message(self, *, manager, channel_id, words):
        """
        Handle the message

        Args:
            manager (str): The user id for the person giving the command
            channel_id (str): The channel id
            words (list of str): the words making up a command
        """
        try:
            await self.run_command(
                manager=manager,
                channel_id=channel_id,
                words=words,
            )
        except (InputException, ReleaseException) as ex:
            log.exception("A BotException was raised:")
            await self.say(channel_id=channel_id, text=f"Oops! {ex}")
        except:  # pylint: disable=bare-except
            log.exception("Exception found when handling a message")
            await self.say(
                channel_id=channel_id,
                text="No! Perry the Platypus, don't do it! "
                "Don't push the self-destruct button. This one right here.",
            )

    async def handle_webhook(self, webhook_dict):
        """
        Handle a webhook coming from Slack. The payload has already been verified at this point.

        Args:
            webhook_dict (dict): The dict from Slack containing the webhook information
        """
        channel_id = webhook_dict["channel"]["id"]
        user_id = webhook_dict["user"]["id"]
        callback_id = webhook_dict["callback_id"]
        timestamp = webhook_dict["message_ts"]
        original_text = webhook_dict["original_message"]["text"]

        if callback_id == FINISH_RELEASE_ID:
            repo_info = self.get_repo_info(channel_id)
            await self.update_message(
                channel_id=channel_id,
                timestamp=timestamp,
                text=original_text,
                attachments=[{"title": "Merging..."}],
            )
            try:
                await self.finish_release(
                    CommandArgs(
                        channel_id=channel_id,
                        repo_info=repo_info,
                        args=[],
                        manager=user_id,
                    )
                )
            except:
                await self.update_message(
                    channel_id=channel_id,
                    timestamp=timestamp,
                    text=original_text,
                    attachments=[{"title": "Error merging release"}],
                )
                raise

        elif callback_id == NEW_RELEASE_ID:
            repo_info = self.get_repo_info(channel_id)
            name = webhook_dict["actions"][0]["name"]
            if name == "cancel":
                await self.delete_message(
                    channel_id=channel_id,
                    timestamp=timestamp,
                )
                return

            version = webhook_dict["actions"][0]["value"]
            await self.update_message(
                channel_id=channel_id,
                timestamp=timestamp,
                text=original_text,
                attachments=[{"title": f"Starting release {version}..."}],
            )
            try:
                await self.release_command(
                    CommandArgs(
                        channel_id=channel_id,
                        repo_info=repo_info,
                        args=[version],
                        manager=user_id,
                    )
                )
            except:
                await self.update_message(
                    channel_id=channel_id,
                    timestamp=timestamp,
                    text=original_text,
                    attachments=[{"title": "Error starting release"}],
                )
                raise
        else:
            log.warning("Unknown callback id: %s", callback_id)

    async def handle_event(self, webhook_dict):
        """
        Process events from Slack's events API

        Args:
            webhook_dict (dict): Arguments for the event
        """
        if webhook_dict.get("type") != "event_callback":
            log.info(
                "Received event other than event callback or challenge: %s",
                webhook_dict,
            )
            return

        message = webhook_dict["event"]
        if message["type"] != "message":
            log.info("Received event other than message: %s", webhook_dict)
            return

        if message.get("subtype") == "message_changed":
            # A user edits their message
            # content = message.get('message', {}).get('text')
            content = None
        else:
            content = message.get("text")

        if content is None:
            return

        channel_id = message.get("channel")

        all_words = content.strip().split()
        if len(all_words) > 0:
            message_handle, *words = all_words
            if message_handle in (f"<@{self.doof_id}>", "@doof"):
                await self.handle_message(
                    manager=message["user"],
                    channel_id=channel_id,
                    words=words,
                )

    async def startup(self):
        """
        Run various tasks when bot starts
        """
        for repo_info in self.repos_info:
            if repo_info.project_type != WEB_APPLICATION_TYPE:
                continue

            org, repo = get_org_and_repo(repo_info.repo_url)
            release_pr = await get_release_pr(
                github_access_token=self.github_access_token,
                org=org,
                repo=repo,
                all_prs=True,
            )
            if not release_pr:
                continue

            asyncio.create_task(
                self.run_release_lifecycle(
                    repo_info=repo_info, manager=None, release_pr=release_pr
                )
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


def get_commit_hash(text):
    """
    return commit hash at the end of the message

    Args:
        text (str): The string containing the commit hash

    Returns:
        str: The commit hash if it parsed correctly
    """
    hash_pattern = re.compile(COMMIT_HASH_RE)
    if hash_pattern.match(text):
        return text
    else:
        raise InputException("Invalid commit hash")


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
    return command_words == input_words[: len(command_words)]


def init_sentry():
    """Initialize the Sentry SDK"""
    sentry_dsn = os.environ.get("SENTRY_SDK", "")

    if sentry_dsn:
        sentry_sdk.init(
            dsn=sentry_dsn,
            send_default_pii=False,
        )


async def async_main():
    """async function for bot"""
    envs = get_envs()

    init_sentry()

    channels_info = await get_channels_info(envs["SLACK_ACCESS_TOKEN"])
    doof_id = await get_doofs_id(envs["SLACK_ACCESS_TOKEN"])
    repos_info = load_repos_info(channels_info)
    try:
        port = int(envs["PORT"])
    except ValueError as ex:
        raise Exception("PORT is invalid") from ex

    bot = Bot(
        slack_access_token=envs["SLACK_ACCESS_TOKEN"],
        github_access_token=envs["GITHUB_ACCESS_TOKEN"],
        npm_token=envs["NPM_TOKEN"],
        timezone=pytz.timezone(envs["TIMEZONE"]),
        repos_info=repos_info,
        doof_id=doof_id,
    )
    app = make_app(secret=envs["SLACK_SECRET"], bot=bot)
    app.listen(port)

    await bot.startup()


def main():
    """main function for bot command"""
    tornado.ioloop.IOLoop.current().run_sync(async_main)


if __name__ == "__main__":
    main()
