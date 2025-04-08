"""Tests for Doof"""

import asyncio
from datetime import timedelta

import pytest
import pytz

from bot import (
    CommandArgs,
    Bot,
)
from conftest import (
    LIBRARY_TEST_REPO_INFO,
    WEB_TEST_REPO_INFO,
)
from constants import (
    CI,
    LIBRARY_TYPE,
    WEB_APPLICATION_TYPE,
    FINISH_RELEASE_ID,
    NEW_RELEASE_ID,
    PROD,
    RC,
    SETUPTOOLS,
    NPM,
    WAITING_FOR_CHECKBOXES,
)
from exception import ReleaseException
from github import get_org_and_repo
from lib import (
    format_user_id,
    next_versions,
    ReleasePR,
    remove_path_from_url,
)
from repo_info import RepoInfo
from test_util import (
    async_context_manager_yielder,
)

pytestmark = pytest.mark.asyncio

GITHUB_ACCESS = "github"
SLACK_ACCESS = "slack"
NPM_TOKEN = "npm-token"


# pylint: disable=redefined-outer-name, too-many-lines
class DoofSpoof(Bot):
    """Testing bot"""

    def __init__(self, *, loop):
        """Since the testing bot isn't contacting slack or github we don't need these tokens here"""
        super().__init__(
            doof_id="Doofenshmirtz",
            slack_access_token=SLACK_ACCESS,
            github_access_token=GITHUB_ACCESS,
            npm_token=NPM_TOKEN,
            timezone=pytz.timezone("America/New_York"),
            repos_info=[WEB_TEST_REPO_INFO, LIBRARY_TEST_REPO_INFO],
            loop=loop,
        )

        self.slack_users = []
        self.messages = {}

    async def lookup_users(self):
        """Users in the channel"""
        return self.slack_users

    def _append(self, channel_id, message_dict):
        """Add a message to the list so we can assert it was sent"""
        if channel_id not in self.messages:
            self.messages[channel_id] = []
        self.messages[channel_id].append(message_dict)

    async def _say(self, *, channel_id, text=None, attachments=None, message_type=None):
        """Quick and dirty message recording"""
        self._append(
            channel_id,
            {"text": text, "attachments": attachments, "message_type": message_type},
        )

    async def update_message(
        self, *, channel_id, timestamp, text=None, attachments=None
    ):
        """
        Record message updates
        """
        self._append(
            channel_id,
            {"text": text, "attachments": attachments, "timestamp": timestamp},
        )

    async def delete_message(self, *, channel_id, timestamp):
        """
        Record message delete
        """
        self._append(channel_id, {"timestamp": timestamp})

    def said(self, text, *, attachments=None, channel_id=None, times=1):
        """Did doof say this thing?"""
        match_count = 0
        for message_channel_id, messages in self.messages.items():
            if channel_id is None or message_channel_id == channel_id:
                for message in messages:
                    if text not in str(message):
                        continue

                    if attachments is None:
                        match_count += 1
                    else:
                        if attachments == message["attachments"]:
                            match_count += 1

        if match_count == times:
            return True
        elif match_count == 0:
            return False
        raise Exception(
            f"Expected {text} to be said {times} time(s) but was said {match_count} times."
        )


@pytest.fixture
def sleep_sync_mock(mocker):
    """Mock asyncio.sleep so we don't spend time waiting during the release lifecycle"""
    yield mocker.async_patch("bot.async_sleep")


@pytest.fixture
def doof(event_loop, sleep_sync_mock):  # pylint: disable=unused-argument
    """Create a Doof"""
    yield DoofSpoof(loop=event_loop)


@pytest.fixture
def mock_labels(mocker):
    """mock out setting and getting labels"""

    _label = None

    def _set_label(*args, label, **kwargs):  # pylint: disable=unused-argument
        nonlocal _label
        _label = label

    def _get_label(*args, **kwargs):  # pylint: disable=unused-argument
        return _label

    mock_set = mocker.async_patch("bot.set_release_label", side_effect=_set_label)
    mock_get = mocker.async_patch("bot.status_for_repo_last_pr", side_effect=_get_label)
    yield mock_set, mock_get


async def test_release_notes(doof, test_repo, test_repo_directory, mocker):
    """Doof should show release notes"""
    old_version = "0.1.2"
    get_project_version_mock = mocker.async_patch(
        "bot.get_project_version", autospec=True, return_value=old_version
    )
    mocker.patch(
        "bot.init_working_dir",
        side_effect=async_context_manager_yielder(test_repo_directory),
    )
    notes = "some notes"
    create_release_notes_mock = mocker.async_patch(
        "bot.create_release_notes", return_value=notes
    )
    any_new_commits_mock = mocker.async_patch("bot.any_new_commits", return_value=True)
    org, repo = get_org_and_repo(test_repo.repo_url)
    release_pr = ReleasePR(
        "version",
        f"https://github.com/{org}/{repo}/pulls/123456",
        "body",
        123456,
        False,
    )
    get_release_pr_mock = mocker.async_patch(
        "bot.get_release_pr", return_value=release_pr
    )

    await doof.run_command(
        manager="mitodl_user",
        channel_id=test_repo.channel_id,
        words=["release", "notes"],
    )

    get_project_version_mock.assert_called_once_with(
        repo_info=test_repo, working_dir=test_repo_directory
    )
    create_release_notes_mock.assert_called_once_with(
        old_version,
        with_checkboxes=False,
        base_branch="master",
        root=test_repo_directory,
    )
    any_new_commits_mock.assert_called_once_with(
        old_version, base_branch="master", root=test_repo_directory
    )
    get_release_pr_mock.assert_called_once_with(
        github_access_token=GITHUB_ACCESS, org=org, repo=repo
    )

    assert doof.said(f"Release notes since {old_version}")
    assert doof.said(notes)
    assert doof.said(
        f"And also! There is a release already in progress: {release_pr.url}"
    )


async def test_release_notes_no_new_notes(doof, test_repo, test_repo_directory, mocker):
    """Doof should show that there are no new commits"""
    mocker.patch(
        "bot.init_working_dir",
        side_effect=async_context_manager_yielder(test_repo_directory),
    )
    old_version = "0.1.2"
    get_project_version_mock = mocker.async_patch(
        "bot.get_project_version", autospec=True, return_value=old_version
    )
    notes = "no new commits"
    create_release_notes_mock = mocker.async_patch(
        "bot.create_release_notes", return_value=notes
    )
    org, repo = get_org_and_repo(test_repo.repo_url)
    get_release_pr_mock = mocker.async_patch("bot.get_release_pr", return_value=None)
    any_new_commits_mock = mocker.async_patch("bot.any_new_commits", return_value=False)

    await doof.run_command(
        manager="mitodl_user",
        channel_id=test_repo.channel_id,
        words=["release", "notes"],
    )

    any_new_commits_mock.assert_called_once_with(
        old_version, base_branch="master", root=test_repo_directory
    )
    get_project_version_mock.assert_called_once_with(
        repo_info=test_repo, working_dir=test_repo_directory
    )
    create_release_notes_mock.assert_called_once_with(
        old_version,
        with_checkboxes=False,
        base_branch="master",
        root=test_repo_directory,
    )
    get_release_pr_mock.assert_called_once_with(
        github_access_token=GITHUB_ACCESS, org=org, repo=repo
    )

    assert doof.said(f"Release notes since {old_version}")
    assert not doof.said("Start a new release?")


async def test_release_notes_buttons(doof, test_repo, test_repo_directory, mocker):
    """Doof should show release notes and then offer buttons to start a release"""
    mocker.patch(
        "bot.init_working_dir",
        side_effect=async_context_manager_yielder(test_repo_directory),
    )
    old_version = "0.1.2"
    get_project_version_mock = mocker.async_patch(
        "bot.get_project_version", autospec=True, return_value=old_version
    )
    notes = "some notes"
    create_release_notes_mock = mocker.async_patch(
        "bot.create_release_notes", return_value=notes
    )
    org, repo = get_org_and_repo(test_repo.repo_url)
    get_release_pr_mock = mocker.async_patch("bot.get_release_pr", return_value=None)
    any_new_commits_mock = mocker.async_patch("bot.any_new_commits", return_value=True)

    await doof.run_command(
        manager="mitodl_user",
        channel_id=test_repo.channel_id,
        words=["release", "notes"],
    )

    any_new_commits_mock.assert_called_once_with(
        old_version, base_branch="master", root=test_repo_directory
    )
    get_project_version_mock.assert_called_once_with(
        repo_info=test_repo, working_dir=test_repo_directory
    )
    create_release_notes_mock.assert_called_once_with(
        old_version,
        with_checkboxes=False,
        base_branch="master",
        root=test_repo_directory,
    )
    get_release_pr_mock.assert_called_once_with(
        github_access_token=GITHUB_ACCESS, org=org, repo=repo
    )

    assert doof.said(f"Release notes since {old_version}")
    assert doof.said(notes)
    minor_version, patch_version = next_versions(old_version)
    assert doof.said(
        "Start a new release?",
        attachments=[
            {
                "fallback": "New release",
                "callback_id": "new_release",
                "actions": [
                    {
                        "name": "minor_release",
                        "text": minor_version,
                        "value": minor_version,
                        "type": "button",
                    },
                    {
                        "name": "patch_release",
                        "text": patch_version,
                        "value": patch_version,
                        "type": "button",
                    },
                    {
                        "name": "cancel",
                        "text": "Dismiss",
                        "value": "cancel",
                        "type": "button",
                        "style": "danger",
                    },
                ],
            }
        ],
    )
    assert not doof.said("And also! There is a release already in progress")


async def test_version(doof, test_repo, mocker):
    """
    Doof should tell you what version the latest release was
    """
    a_hash = "hash"
    version = "1.2.3"
    fetch_release_hash_mock = mocker.async_patch(
        "bot.fetch_release_hash", return_value=a_hash
    )
    get_version_tag_mock = mocker.async_patch(
        "bot.get_version_tag", return_value=f"v{version}"
    )
    await doof.run_command(
        manager="mitodl_user",
        channel_id=test_repo.channel_id,
        words=["version"],
    )
    assert doof.said(f"Wait a minute! My evil scheme is at version {version}!")

    fetch_release_hash_mock.assert_called_once_with(test_repo.prod_hash_url)
    get_version_tag_mock.assert_called_once_with(
        github_access_token=GITHUB_ACCESS,
        repo_url=test_repo.repo_url,
        commit_hash=a_hash,
    )


@pytest.mark.parametrize(
    "deployment_server_type, expected_url",
    [
        [PROD, WEB_TEST_REPO_INFO.prod_hash_url],
        [RC, WEB_TEST_REPO_INFO.rc_hash_url],
        [CI, WEB_TEST_REPO_INFO.ci_hash_url],
    ],
)
async def test_hash(doof, test_repo, mocker, deployment_server_type, expected_url):
    """
    Doof should tell you what the latest commit was on production
    """
    a_hash = "hash"
    message = "def876 A merged PR (#97)"
    fetch_release_hash_mock = mocker.async_patch(
        "bot.fetch_release_hash", return_value=a_hash
    )
    get_version_tag_mock = mocker.async_patch(
        "bot.get_commit_oneline_message", return_value=message
    )
    await doof.run_command(
        manager="mitodl_user",
        channel_id=test_repo.channel_id,
        words=["hash", deployment_server_type],
    )
    assert doof.said(
        f"Oh, Perry the Platypus, look what you've done on {deployment_server_type}! {message}"
    )

    fetch_release_hash_mock.assert_called_once_with(expected_url)
    get_version_tag_mock.assert_called_once_with(
        github_access_token=GITHUB_ACCESS,
        repo_url=test_repo.repo_url,
        commit_hash=a_hash,
    )


# pylint: disable=too-many-locals
@pytest.mark.parametrize("command", ["release", "start release"])
async def test_release(
    doof, test_repo, mocker, command, mock_labels
):  # pylint: disable=unused-argument
    """
    Doof should do a release when asked
    """
    version = "1.2.3"
    pr = ReleasePR(
        version=version,
        url="http://new.url",
        body="Release PR body",
        number=123,
        open=False,
    )
    get_release_pr_mock = mocker.async_patch(
        "bot.get_release_pr", side_effect=[None, pr, pr]
    )
    release_mock = mocker.async_patch("bot.release")

    wait_for_deploy_sync_mock = mocker.async_patch("bot.wait_for_deploy")
    authors = {"author1", "author2"}
    mocker.async_patch("bot.get_unchecked_authors", return_value=authors)

    wait_for_checkboxes_sync_mock = mocker.async_patch("bot.Bot.wait_for_checkboxes")

    command_words = command.split() + [version]
    me = "mitodl_user"
    await doof.run_command(
        manager=me,
        channel_id=test_repo.channel_id,
        words=command_words,
    )

    org, repo = get_org_and_repo(test_repo.repo_url)
    get_release_pr_mock.assert_any_call(
        github_access_token=GITHUB_ACCESS,
        org=org,
        repo=repo,
    )
    release_mock.assert_called_once_with(
        github_access_token=GITHUB_ACCESS,
        repo_info=test_repo,
        new_version=pr.version,
    )
    wait_for_deploy_sync_mock.assert_called_once_with(
        github_access_token=GITHUB_ACCESS,
        repo_url=test_repo.repo_url,
        hash_url=test_repo.rc_hash_url,
        watch_branch="release-candidate",
        expected_version=pr.version,
        timeout_seconds=3600,
    )
    assert doof.said("Now deploying to RC...")
    assert doof.said(
        f"Release {pr.version} for {test_repo.name} was deployed at {remove_path_from_url(test_repo.rc_hash_url)}!",
        channel_id=test_repo.channel_id,
    )
    assert wait_for_checkboxes_sync_mock.called is True


# pylint: disable=too-many-locals
async def test_hotfix_release(
    doof, test_repo, test_repo_directory, mocker, mock_labels
):  # pylint: disable=unused-argument
    """
    Doof should do a hotfix when asked
    """
    mocker.patch(
        "bot.init_working_dir",
        side_effect=async_context_manager_yielder(test_repo_directory),
    )
    commit_hash = "uthhg983u4thg9h5"
    version = "0.1.2"
    pr = ReleasePR(
        version=version,
        url="http://new.url",
        body="Release PR body",
        number=123,
        open=False,
    )
    get_release_pr_mock = mocker.async_patch(
        "bot.get_release_pr", side_effect=[None, pr, pr]
    )
    release_mock = mocker.async_patch("bot.release")

    wait_for_deploy_sync_mock = mocker.async_patch("bot.wait_for_deploy")
    authors = {"author1", "author2"}
    mocker.async_patch("bot.get_unchecked_authors", return_value=authors)

    wait_for_checkboxes_sync_mock = mocker.async_patch("bot.Bot.wait_for_checkboxes")

    old_version = "0.1.1"
    get_project_version_mock = mocker.async_patch(
        "bot.get_project_version", autospec=True, return_value=old_version
    )

    command_words = ["hotfix", commit_hash]
    me = "mitodl_user"
    await doof.run_command(
        manager=me,
        channel_id=test_repo.channel_id,
        words=command_words,
    )

    org, repo = get_org_and_repo(test_repo.repo_url)
    get_release_pr_mock.assert_any_call(
        github_access_token=GITHUB_ACCESS,
        org=org,
        repo=repo,
    )
    get_project_version_mock.assert_called_once_with(
        repo_info=test_repo, working_dir=test_repo_directory
    )
    release_mock.assert_called_once_with(
        github_access_token=GITHUB_ACCESS,
        repo_info=test_repo,
        new_version=pr.version,
        branch="release",
        commit_hash=commit_hash,
    )
    wait_for_deploy_sync_mock.assert_called_once_with(
        github_access_token=GITHUB_ACCESS,
        repo_url=test_repo.repo_url,
        hash_url=test_repo.rc_hash_url,
        watch_branch="release-candidate",
        expected_version=pr.version,
        timeout_seconds=3600,
    )
    assert doof.said("Now deploying to RC...")
    assert wait_for_checkboxes_sync_mock.called is True


@pytest.mark.parametrize("command", ["release", "start release"])
async def test_release_in_progress(doof, test_repo, mocker, command):
    """
    If a release is already in progress doof should fail
    """
    version = "1.2.3"
    url = "http://fake.release.pr"
    mocker.async_patch(
        "bot.get_release_pr",
        return_value=ReleasePR(
            version=version,
            url=url,
            body="Release PR body",
            number=123,
            open=False,
        ),
    )

    command_words = command.split() + [version]
    with pytest.raises(ReleaseException) as ex:
        await doof.run_command(
            manager="mitodl_user",
            channel_id=test_repo.channel_id,
            words=command_words,
        )
    assert ex.value.args[0] == f"A release is already in progress: {url}"


@pytest.mark.parametrize("command", ["release", "start release"])
async def test_release_bad_version(doof, test_repo, command):
    """
    If the version doesn't parse correctly doof should fail
    """
    command_words = command.split() + ["a.b.c"]
    await doof.run_command(
        manager="mitodl_user",
        channel_id=test_repo.channel_id,
        words=command_words,
    )
    assert doof.said(
        "having trouble figuring out what that means",
    )


@pytest.mark.parametrize("command", ["release", "start release"])
async def test_release_no_args(doof, test_repo, command):
    """
    If no version is given doof should complain
    """
    command_words = command.split()
    await doof.run_command(
        manager="mitodl_user",
        channel_id=test_repo.channel_id,
        words=command_words,
    )
    assert doof.said(
        "Careful, careful. I expected 1 words but you said 0.",
    )


async def test_release_library(doof, library_test_repo, mocker):
    """Do a library release"""
    version = "1.2.3"
    pr = ReleasePR(
        version=version,
        url="http://new.url",
        body="Release PR body",
        number=123,
        open=False,
    )
    get_release_pr_mock = mocker.async_patch(
        "bot.get_release_pr", side_effect=[None, pr, pr]
    )
    release_mock = mocker.async_patch("bot.release")

    command_words = ["release", version]
    me = "mitodl_user"
    await doof.run_command(
        manager=me,
        channel_id=library_test_repo.channel_id,
        words=command_words,
    )

    org, repo = get_org_and_repo(library_test_repo.repo_url)
    release_mock.assert_called_once_with(
        github_access_token=GITHUB_ACCESS,
        repo_info=library_test_repo,
        new_version=pr.version,
    )
    get_release_pr_mock.assert_any_call(
        github_access_token=GITHUB_ACCESS,
        org=org,
        repo=repo,
    )
    assert doof.said(
        f"Behold, my new evil scheme - release {pr.version} for {library_test_repo.name}! PR is up at {pr.url}. "
        f"Once all tests pass, finish the release.",
        attachments=[
            {
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
                    },
                ],
                "callback_id": "finish_release",
                "fallback": "Finish the release",
            }
        ],
    )


@pytest.mark.parametrize("project_type", [WEB_APPLICATION_TYPE, LIBRARY_TYPE])
async def test_finish_release(
    doof, mocker, project_type, mock_labels
):  # pylint: disable=unused-argument
    """
    Doof should finish a release when asked
    """
    version = "1.2.3"
    pr = ReleasePR(
        version=version,
        url="http://new.url",
        body="Release PR body",
        number=123,
        open=False,
    )
    get_release_pr_mock = mocker.async_patch("bot.get_release_pr", return_value=pr)
    finish_release_mock = mocker.async_patch("bot.finish_release")

    wait_for_deploy_prod_mock = mocker.async_patch("bot.Bot._wait_for_deploy_prod")

    test_repo = (
        LIBRARY_TEST_REPO_INFO if project_type == LIBRARY_TYPE else WEB_TEST_REPO_INFO
    )

    await doof.run_command(
        manager="mitodl_user",
        channel_id=test_repo.channel_id,
        words=["finish", "release"],
    )

    org, repo = get_org_and_repo(test_repo.repo_url)
    get_release_pr_mock.assert_called_once_with(
        github_access_token=GITHUB_ACCESS,
        org=org,
        repo=repo,
    )
    finish_release_mock.assert_called_once_with(
        github_access_token=GITHUB_ACCESS,
        repo_info=test_repo,
        version=version,
        timezone=doof.timezone,
    )
    assert doof.said(f"Merged evil scheme {version} for {test_repo.name}!")
    if project_type == WEB_APPLICATION_TYPE:
        assert doof.said("deploying to production...")
        wait_for_deploy_prod_mock.assert_called_once_with(
            doof,
            repo_info=test_repo,
            manager="mitodl_user",
            release_pr=pr,
        )


async def test_finish_release_no_release(doof, test_repo, mocker):
    """
    If there's no release to finish doof should complain
    """
    get_release_pr_mock = mocker.async_patch("bot.get_release_pr", return_value=None)
    with pytest.raises(ReleaseException) as ex:
        await doof.run_command(
            manager="mitodl_user",
            channel_id=test_repo.channel_id,
            words=["finish", "release"],
        )
    assert "No release currently in progress" in ex.value.args[0]
    org, repo = get_org_and_repo(test_repo.repo_url)
    get_release_pr_mock.assert_called_once_with(
        github_access_token=GITHUB_ACCESS,
        org=org,
        repo=repo,
    )


async def test_webhook_different_callback_id(doof, mocker):
    """
    If the callback id doesn't match nothing should be done
    """
    finish_release_mock = mocker.patch("bot.finish_release", autospec=True)
    await doof.handle_webhook(
        webhook_dict={
            "token": "token",
            "callback_id": "xyz",
            "channel": {"id": "doof"},
            "user": {"id": "doofenshmirtz"},
            "message_ts": "123.45",
            "original_message": {
                "text": "Doof's original text",
            },
        },
    )

    assert finish_release_mock.called is False


# pylint: disable=too-many-arguments
async def test_webhook_finish_release(
    doof, mocker, test_repo, library_test_repo, mock_labels
):  # pylint: disable=unused-argument
    """
    Finish the release
    """
    doof.repos_info = [test_repo, library_test_repo]

    pr_body = ReleasePR(
        version="version",
        url="url",
        body="body",
        number=123,
        open=False,
    )
    get_release_pr_mock = mocker.async_patch("bot.get_release_pr", return_value=pr_body)
    finish_release_mock = mocker.async_patch("bot.finish_release")
    wait_for_deploy_prod_mock = mocker.async_patch("bot.Bot._wait_for_deploy_prod")

    payload = {
        "token": "token",
        "callback_id": FINISH_RELEASE_ID,
        "channel": {"id": "doof"},
        "user": {"id": "doofenshmirtz"},
        "message_ts": "123.45",
        "original_message": {
            "text": "Doof's original text",
        },
    }
    await doof.handle_webhook(
        webhook_dict=payload,
    )

    repo_url = test_repo.repo_url
    org, repo = get_org_and_repo(repo_url)
    wait_for_deploy_prod_mock.assert_any_call(
        doof, repo_info=test_repo, manager=payload["user"]["id"], release_pr=pr_body
    )
    get_release_pr_mock.assert_any_call(
        github_access_token=doof.github_access_token,
        org=org,
        repo=repo,
    )
    finish_release_mock.assert_any_call(
        github_access_token=doof.github_access_token,
        repo_info=test_repo,
        version=pr_body.version,
        timezone=doof.timezone,
    )
    assert doof.said("Merging...")
    assert not doof.said("Error")


async def test_webhook_finish_release_fail(doof, mocker):
    """
    If finishing the release fails we should update the button to show the error
    """
    get_release_pr_mock = mocker.async_patch("bot.get_release_pr")
    finish_release_mock = mocker.async_patch("bot.finish_release", side_effect=KeyError)

    with pytest.raises(KeyError):
        await doof.handle_webhook(
            webhook_dict={
                "token": "token",
                "callback_id": FINISH_RELEASE_ID,
                "channel": {"id": "doof"},
                "user": {"id": "doofenshmirtz"},
                "message_ts": "123.45",
                "original_message": {
                    "text": "Doof's original text",
                },
            },
        )

    assert get_release_pr_mock.called is True
    assert finish_release_mock.called is True
    assert doof.said("Merging...")
    assert doof.said("Error")


async def test_webhook_start_release(doof, test_repo, mocker):
    """
    Start a new release
    """
    release_mock = mocker.async_patch("bot.Bot.release_command")

    version = "3.4.5"
    manager = "doofenshmirtz"
    channel_id = "doof"
    await doof.handle_webhook(
        webhook_dict={
            "token": "token",
            "callback_id": NEW_RELEASE_ID,
            "channel": {"id": channel_id},
            "user": {"id": manager},
            "message_ts": "123.45",
            "original_message": {
                "text": "Doof's original text",
            },
            "actions": [
                {
                    "value": version,
                    "name": "minor_release",
                }
            ],
        },
    )

    assert doof.said(f"Starting release {version}...")
    assert release_mock.call_count == 1
    assert release_mock.call_args[0][1] == CommandArgs(
        repo_info=test_repo,
        args=[version],
        manager=manager,
        channel_id=channel_id,
    )
    assert not doof.said("Error")


async def test_webhook_start_release_fail(doof, mocker):
    """
    If starting the release fails we should update the button to show the error
    """
    release_mock = mocker.patch(
        "bot.Bot.release_command", autospec=True, side_effect=ZeroDivisionError
    )
    version = "3.4.5"
    with pytest.raises(ZeroDivisionError):
        await doof.handle_webhook(
            webhook_dict={
                "token": "token",
                "callback_id": NEW_RELEASE_ID,
                "channel": {"id": "doof"},
                "user": {"id": "doofenshmirtz"},
                "message_ts": "123.45",
                "original_message": {
                    "text": "Doof's original text",
                },
                "actions": [
                    {
                        "value": version,
                        "name": "minor_release",
                    }
                ],
            },
        )

    assert doof.said(f"Starting release {version}...")
    assert release_mock.call_count == 1
    assert release_mock.call_args[0][1].args == [version]
    assert doof.said("Error")


async def test_webhook_dismiss_release(doof):
    """
    Delete the buttons in the message for a new release
    """
    timestamp = "123.45"
    version = "3.4.5"
    await doof.handle_webhook(
        webhook_dict={
            "token": "token",
            "callback_id": NEW_RELEASE_ID,
            "channel": {"id": "doof"},
            "user": {"id": "doofenshmirtz"},
            "message_ts": timestamp,
            "original_message": {
                "text": "Doof's original text",
            },
            "actions": [
                {
                    "value": version,
                    "name": "cancel",
                }
            ],
        },
    )

    assert doof.said(timestamp)
    assert not doof.said("Starting release")


async def test_uptime(doof, mocker, test_repo):
    """Uptime should show how much time the bot has been awake"""
    later = doof.doof_boot + timedelta(seconds=140)
    mocker.patch("bot.now_in_utc", autospec=True, return_value=later)
    await doof.run_command(
        manager="mitodl_user",
        channel_id=test_repo.channel_id,
        words=["uptime"],
    )
    assert doof.said("Awake for 2 minutes.")


@pytest.mark.parametrize("packaging_tool", [NPM, SETUPTOOLS])
async def test_publish(doof, library_test_repo, mocker, packaging_tool):
    """the publish command should start the upload process"""
    publish_patched = mocker.async_patch("bot.publish")

    library_test_repo = RepoInfo(
        **{**library_test_repo._asdict(), "packaging_tool": packaging_tool}
    )
    doof.repos_info = [library_test_repo]
    version = "3.4.5"

    await doof.run_command(
        manager="me",
        channel_id=library_test_repo.channel_id,
        words=["publish", version],
    )

    publish_patched.assert_called_once_with(
        repo_info=library_test_repo,
        github_access_token=GITHUB_ACCESS,
        version=version,
        npm_token=NPM_TOKEN,
    )
    server = "PyPI" if packaging_tool == SETUPTOOLS else "the npm registry"
    assert doof.said(f"Successfully uploaded {version} to {server}.")


@pytest.mark.parametrize(
    "command,project_type",
    [
        ["version", LIBRARY_TYPE],
        ["wait for checkboxes", LIBRARY_TYPE],
        ["publish 1.2.3", WEB_APPLICATION_TYPE],
    ],
)  # pylint: disable=too-many-arguments
async def test_invalid_project_type(
    doof, test_repo, library_test_repo, command, project_type
):
    """
    Compare incompatible commands with project types
    """
    repo = test_repo if project_type == WEB_APPLICATION_TYPE else library_test_repo
    other_type = (
        LIBRARY_TYPE if project_type == WEB_APPLICATION_TYPE else WEB_APPLICATION_TYPE
    )

    await doof.run_command(
        manager="mitodl_user",
        channel_id=repo.channel_id,
        words=command.split(),
    )

    assert doof.said(
        f"That command is only for {other_type} projects but this is a {project_type} project."
    )


@pytest.mark.parametrize(
    "command",
    [
        "release 1.2.3",
        "start release 1.2.3",
        "finish release",
        "wait for checkboxes",
        "publish 1.2.3",
        "release notes",
    ],
)
async def test_command_without_repo(doof, command):
    """
    Test that commands won't work on channels without a repo
    """
    await doof.run_command(
        manager="mitodl_user",
        channel_id="not_a_repo_channel",
        words=command.split(),
    )

    assert doof.said(
        "That command requires a repo but this channel is not attached to any project."
    )


async def test_help(doof):
    """
    Test that doof will show help text
    """
    await doof.run_command(
        manager="mitodl_user",
        channel_id="not_a_repo_channel",
        words=["help"],
    )

    assert doof.said("*help*: Show available commands")


@pytest.mark.parametrize("has_checkboxes", [True, False])
async def test_wait_for_checkboxes(
    mocker, doof, sleep_sync_mock, test_repo, has_checkboxes, mock_labels
):  # pylint: disable=unused-argument,too-many-positional-arguments
    """wait_for_checkboxes should poll github, parse checkboxes and see if all are checked"""
    org, repo = get_org_and_repo(test_repo.repo_url)
    channel_id = test_repo.channel_id

    pr = ReleasePR(
        "version",
        f"https://github.com/{org}/{repo}/pulls/123456",
        "body",
        123456,
        False,
    )
    get_release_pr_mock = mocker.async_patch("bot.get_release_pr", return_value=pr)
    get_unchecked_patch = mocker.async_patch(
        "bot.get_unchecked_authors",
        side_effect=(
            [
                {"author1", "author2", "author3"},
                {"author2"},
                set(),
            ]
            if has_checkboxes
            else [set()]
        ),
    )
    doof.slack_users = [
        {"profile": {"real_name": name}, "id": username}
        for (name, username) in [
            ("Author 1", "author1"),
            ("Author 2", "author2"),
            ("Author 3", "author3"),
        ]
    ]

    me = "mitodl_user"
    await doof.wait_for_checkboxes(manager=me, repo_info=test_repo, release_pr=pr)
    get_unchecked_patch.assert_any_call(
        github_access_token=GITHUB_ACCESS,
        org=org,
        repo=repo,
    )
    assert get_unchecked_patch.call_count == (3 if has_checkboxes else 1)
    assert sleep_sync_mock.call_count == (2 if has_checkboxes else 0)
    get_release_pr_mock.assert_called_once_with(
        github_access_token=GITHUB_ACCESS, org=org, repo=repo
    )
    if has_checkboxes:
        assert doof.said(
            f"All checkboxes checked off. Release {pr.version} is ready for the Merginator {format_user_id(me)}",
            attachments=[
                {
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
                        },
                    ],
                    "callback_id": "finish_release",
                    "fallback": "Finish the release",
                }
            ],
        )
    if has_checkboxes:
        assert not doof.said(
            "Thanks for checking off your boxes <@author1>, <@author2>, <@author3>!",
            channel_id=channel_id,
        )
        assert doof.said(
            "Thanks for checking off your boxes <@author1>, <@author3>!",
            channel_id=channel_id,
        )
        assert doof.said(
            "Thanks for checking off your boxes <@author2>!", channel_id=channel_id
        )


async def test_wait_for_checkboxes_no_pr(
    mocker, doof, test_repo, mock_labels, sleep_sync_mock
):  # pylint: disable=unused-argument
    """wait_for_checkboxes should exit without error if the PR doesn't exist"""
    org, repo = get_org_and_repo(test_repo.repo_url)
    mock_set, mock_get = mock_labels  # pylint: disable=unused-variable
    mock_set(label=WAITING_FOR_CHECKBOXES)

    pr = ReleasePR(
        "version",
        f"https://github.com/{org}/{repo}/pulls/123456",
        "body",
        123456,
        False,
    )
    mocker.async_patch("bot.get_release_pr", side_effect=ReleaseException())
    mocker.async_patch("lib.get_release_pr", side_effect=ReleaseException())

    me = "mitodl_user"
    await doof.run_release_lifecycle(
        manager=me,
        repo_info=test_repo,
        release_pr=pr,
    )
    sleep_sync_mock.assert_called_once_with(10)


# pylint: disable=too-many-arguments
@pytest.mark.parametrize(
    "repo_info, has_release_pr, has_expected",
    [
        [WEB_TEST_REPO_INFO, False, False],
        [WEB_TEST_REPO_INFO, True, True],
        [LIBRARY_TEST_REPO_INFO, False, False],
        [LIBRARY_TEST_REPO_INFO, True, False],
    ],
)
async def test_startup(doof, mocker, repo_info, has_release_pr, has_expected):
    """
    Test that doof will show help text
    """
    doof.repos_info = [repo_info]
    release_pr = ReleasePR(
        version="version",
        url=repo_info.repo_url,
        body="Release PR body",
        number=123,
        open=False,
    )
    org, repo = get_org_and_repo(repo_info.repo_url)
    get_release_pr_mock = mocker.async_patch(
        "bot.get_release_pr", return_value=(release_pr if has_release_pr else None)
    )
    run_release_lifecycle_mock = mocker.async_patch("bot.Bot.run_release_lifecycle")

    await doof.startup()
    if repo_info.project_type == WEB_APPLICATION_TYPE:
        get_release_pr_mock.assert_called_once_with(
            github_access_token=GITHUB_ACCESS,
            org=org,
            repo=repo,
            all_prs=True,
        )
    else:
        assert get_release_pr_mock.called is False

    # iterate once through event loop
    await asyncio.sleep(0)
    assert not doof.said("isn't evil enough until all the checkboxes are checked")

    if has_expected:
        run_release_lifecycle_mock.assert_called_once_with(
            doof, manager=None, repo_info=repo_info, release_pr=release_pr
        )
    else:
        assert run_release_lifecycle_mock.called is False


async def test_wait_for_deploy_rc(
    doof, test_repo, mocker, mock_labels
):  # pylint: disable=unused-argument
    """Bot._wait_for_deploy_prod should wait until repo has been deployed to RC"""
    wait_for_deploy_mock = mocker.async_patch("bot.wait_for_deploy")
    org, repo = get_org_and_repo(test_repo.repo_url)
    release_pr = ReleasePR(
        "version",
        f"https://github.com/{org}/{repo}/pulls/123456",
        "body",
        123456,
        False,
    )
    authors = {"author1", "author2"}
    get_unchecked = mocker.async_patch(
        "bot.get_unchecked_authors", return_value=authors
    )
    wait_for_checkboxes_sync_mock = mocker.async_patch("bot.Bot.wait_for_checkboxes")

    await doof._wait_for_deploy_rc(  # pylint: disable=protected-access
        repo_info=test_repo, manager="me", release_pr=release_pr
    )

    wait_for_deploy_mock.assert_called_once_with(
        github_access_token=GITHUB_ACCESS,
        repo_url=test_repo.repo_url,
        hash_url=test_repo.rc_hash_url,
        watch_branch="release-candidate",
        expected_version=release_pr.version,
        timeout_seconds=3600,
    )
    get_unchecked.assert_called_once_with(
        github_access_token=GITHUB_ACCESS,
        org=org,
        repo=repo,
    )
    wait_for_checkboxes_sync_mock.assert_called_once_with(
        mocker.ANY,
        repo_info=test_repo,
        manager="me",
        release_pr=release_pr,
    )


async def test_wait_for_deploy_prod(
    doof, test_repo, mocker, mock_labels
):  # pylint: disable=unused-argument
    """Bot._wait_for_deploy_prod should wait until repo has been deployed to production"""
    wait_for_deploy_mock = mocker.async_patch("bot.wait_for_deploy")
    channel_id = test_repo.channel_id
    release_pr = ReleasePR(
        "1.2.345", "https://github.com/org/repo/pulls/123456", "body", 123456, False
    )

    await doof._wait_for_deploy_prod(  # pylint: disable=protected-access
        repo_info=test_repo, manager="me", release_pr=release_pr
    )

    assert doof.said(
        f"My evil scheme {release_pr.version} for {test_repo.name} has been released "  # Use release_pr.version
        f"to production at {remove_path_from_url(test_repo.prod_hash_url)}. "
        "And by 'released', I mean completely...um...leased.",
        channel_id=channel_id,
    )
    wait_for_deploy_mock.assert_called_once_with(
        github_access_token=GITHUB_ACCESS,
        repo_url=test_repo.repo_url,
        hash_url=test_repo.prod_hash_url,
        watch_branch="release",
        expected_version=release_pr.version,  # Pass expected_version from PR
        timeout_seconds=3600,
    )


async def test_handle_event_message(doof):
    """
    Doof should handle messages appropriately
    """
    channel = "a channel"
    await doof.handle_event(
        webhook_dict={
            "token": "token",
            "type": "event_callback",
            "event": {
                "type": "message",
                "channel": channel,
                "text": f"<@{doof.doof_id}> hi",
                "user": "manager",
            },
        }
    )

    assert doof.said("hello!")


async def test_handle_event_no_callback(doof, mocker):
    """
    If it's not a callback event, ignore it
    """
    log_info = mocker.patch("bot.log.info")
    handle_message = mocker.patch("bot.Bot.handle_message")
    await doof.handle_event(
        webhook_dict={
            "token": "token",
            "type": "different_kind",
        }
    )

    assert (
        "Received event other than event callback or challenge"
        in log_info.call_args[0][0]
    )
    assert handle_message.called is False


async def test_handle_event_not_a_message(doof, mocker):
    """
    If the event is not a message type, ignore it
    """
    log_info = mocker.patch("bot.log.info")
    handle_message = mocker.patch("bot.Bot.handle_message")
    await doof.handle_event(
        webhook_dict={
            "token": "token",
            "type": "event_callback",
            "event": {
                "type": "other_kind",
            },
        }
    )

    assert "Received event other than message" in log_info.call_args[0][0]
    assert handle_message.called is False


async def test_handle_event_no_message(doof, mocker):
    """
    If it's an empty message, ingore it
    """
    handle_message = mocker.patch("bot.Bot.handle_message")
    await doof.handle_event(
        webhook_dict={
            "token": "token",
            "type": "event_callback",
            "event": {
                "type": "message",
                "text": "",
                "user": "manager",
            },
        }
    )

    assert handle_message.called is False


async def test_handle_event_message_changed(doof, mocker):
    """
    Edits to messages are currently ignored
    """
    handle_message = mocker.patch("bot.Bot.handle_message")
    await doof.handle_event(
        webhook_dict={
            "token": "token",
            "type": "event_callback",
            "event": {
                "type": "message",
                "subtype": "message_changed",
                "text": f"<@{doof.doof_id}> hi",
                "channel": "Channel",
                "user": "manager",
            },
        }
    )

    assert handle_message.called is False


@pytest.mark.parametrize(
    "version_arg, expected_version", [["minor", "1.3.0"], ["patch", "1.2.4"]]
)
@pytest.mark.parametrize("has_release_pr", [True, False])
@pytest.mark.parametrize("has_new_commits", [True, False])
async def test_start_new_releases(
    doof,
    mocker,
    test_repo,
    test_repo_directory,
    version_arg,
    expected_version,
    has_release_pr,
    has_new_commits,
):  # pylint: disable=too-many-positional-arguments
    """start new releases command should iterate through releases and start ones without an existing PR"""
    old_version = "1.2.3"
    default_branch = "default"
    command_args = CommandArgs(
        channel_id="channel-id",
        manager="me",
        repo_info=test_repo,
        args=[version_arg],
    )
    org, repo = get_org_and_repo(test_repo.repo_url)
    mocker.patch(
        "bot.init_working_dir",
        side_effect=async_context_manager_yielder(test_repo_directory),
    )
    get_release_pr_mock = mocker.async_patch(
        "bot.get_release_pr",
        return_value=(
            ReleasePR(
                version=old_version,
                url="https://example.com",
                body="...",
                number=123,
                open=False,
            )
            if has_release_pr
            else None
        ),
    )
    release_notes = f"Release notes for {test_repo.repo_url}"
    get_project_version_mock = mocker.async_patch(
        "bot.get_project_version", return_value=old_version
    )
    get_default_branch_mock = mocker.async_patch(
        "bot.get_default_branch", return_value=default_branch
    )
    any_new_commits_mock = mocker.async_patch(
        "bot.any_new_commits", return_value=has_new_commits
    )
    release_notes_mock = mocker.async_patch(
        "bot.create_release_notes", return_value=release_notes
    )
    new_release_mock = mocker.async_patch("bot.Bot._new_release")

    await doof.start_new_releases(command_args)
    assert doof.said("Starting new releases...")
    # iterate once through event loop
    await asyncio.sleep(0)
    get_release_pr_mock.assert_any_call(
        github_access_token=GITHUB_ACCESS, org=org, repo=repo
    )

    if not has_release_pr:
        get_project_version_mock.assert_any_call(
            repo_info=test_repo, working_dir=test_repo_directory
        )
        get_default_branch_mock.assert_any_call(test_repo_directory)
        any_new_commits_mock.assert_any_call(
            old_version, base_branch=default_branch, root=test_repo_directory
        )
    if not has_release_pr and has_new_commits:
        release_notes_mock.assert_any_call(
            old_version,
            with_checkboxes=False,
            base_branch=default_branch,
            root=test_repo_directory,
        )
        new_release_mock.assert_any_call(
            doof,
            repo_info=test_repo,
            version=expected_version,
            manager=command_args.manager,
        )
        assert doof.said(
            f"Started new releases for {WEB_TEST_REPO_INFO.name}, {LIBRARY_TEST_REPO_INFO.name}",
            channel_id=command_args.channel_id,
        )
        title = f"Starting release {expected_version} with these commits"
        assert doof.said(
            title,
            channel_id=test_repo.channel_id,
            attachments=[
                {"fallback": title, "text": release_notes, "mrkdwn_in": ["text"]}
            ],
        )

    else:
        assert new_release_mock.called is False
        assert doof.said("No new releases needed", channel_id=command_args.channel_id)


async def test_status(doof, mocker, test_repo, library_test_repo):
    """The status command should list statuses for each repo"""
    status_last_pr_mock = mocker.async_patch("bot.status_for_repo_last_pr")
    status_new_commits_mock = mocker.async_patch("bot.status_for_repo_new_commits")
    release_pr = ReleasePR("1.2.3", "http://example.com", "body", 12, True)
    get_release_pr_mock = mocker.async_patch(
        "bot.get_release_pr", return_value=release_pr
    )
    description_text = "description"
    format_status_mock = mocker.patch(
        "bot.format_status_for_repo", side_effect=[description_text, ""]
    )
    await doof.run_command(
        manager="mitodl_user",
        channel_id="not_a_repo_channel",
        words=["status"],
    )
    assert doof.said(f"*{test_repo.name}*: {description_text}")
    assert doof.said(f"Nothing new for {library_test_repo.name}")
    for repo_info in [test_repo, library_test_repo]:
        status_last_pr_mock.assert_any_call(
            github_access_token=GITHUB_ACCESS,
            repo_info=repo_info,
            release_pr=release_pr,
        )
        status_new_commits_mock.assert_any_call(
            github_access_token=GITHUB_ACCESS,
            repo_info=repo_info,
            release_pr=release_pr,
        )
        format_status_mock.assert_any_call(
            current_status=status_last_pr_mock.return_value,
            has_new_commits=status_new_commits_mock.return_value,
        )
        org, repo = get_org_and_repo(repo_info.repo_url)
        get_release_pr_mock.assert_any_call(
            github_access_token=GITHUB_ACCESS, org=org, repo=repo, all_prs=True
        )
