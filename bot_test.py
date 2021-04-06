"""Tests for Doof"""
import asyncio
from datetime import datetime, timedelta

import pytest
import pytz

from bot import (
    CommandArgs,
    Bot,
)
from conftest import (
    ANNOUNCEMENTS_CHANNEL,
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
)
from exception import (
    ReleaseException,
    ResetException,
)
from github import get_org_and_repo
from lib import (
    format_user_id,
    next_versions,
    now_in_utc,
    ReleasePR,
    remove_path_from_url,
)
from repo_info import RepoInfo
from test_util import (
    async_context_manager_yielder,
    async_gen_wrapper,
    make_pr,
    make_issue,
    make_parsed_issue,
)

pytestmark = pytest.mark.asyncio

GITHUB_ACCESS = 'github'
SLACK_ACCESS = 'slack'
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
            repos_info=[WEB_TEST_REPO_INFO, LIBRARY_TEST_REPO_INFO, ANNOUNCEMENTS_CHANNEL],
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
        self._append(channel_id, {"text": text, "attachments": attachments, "message_type": message_type})

    async def update_message(self, *, channel_id, timestamp, text=None, attachments=None):
        """
        Record message updates
        """
        self._append(channel_id, {"text": text, "attachments": attachments, "timestamp": timestamp})

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
        raise Exception(f"Expected {text} to be said {times} time(s) but was said {match_count} times.")


@pytest.fixture
def doof(event_loop):
    """Create a Doof"""
    yield DoofSpoof(loop=event_loop)


async def test_release_notes(doof, test_repo, test_repo_directory, mocker):
    """Doof should show release notes"""
    old_version = "0.1.2"
    update_version_mock = mocker.async_patch('bot.update_version', autospec=True, return_value=old_version)
    mocker.patch(
        'bot.init_working_dir', side_effect=async_context_manager_yielder(test_repo_directory)
    )
    notes = "some notes"
    create_release_notes_mock = mocker.async_patch('bot.create_release_notes', return_value=notes)
    any_new_commits_mock = mocker.async_patch('bot.any_new_commits', return_value=True)
    org, repo = get_org_and_repo(test_repo.repo_url)
    release_pr = ReleasePR('version', f'https://github.com/{org}/{repo}/pulls/123456', 'body')
    get_release_pr_mock = mocker.async_patch('bot.get_release_pr', return_value=release_pr)

    await doof.run_command(
        manager='mitodl_user',
        channel_id=test_repo.channel_id,
        words=['release', 'notes'],
    )

    update_version_mock.assert_called_once_with(
        repo_info=test_repo, new_version="9.9.9", working_dir=test_repo_directory
    )
    create_release_notes_mock.assert_called_once_with(
        old_version, with_checkboxes=False, base_branch="master", root=test_repo_directory
    )
    any_new_commits_mock.assert_called_once_with(old_version, base_branch="master", root=test_repo_directory)
    get_release_pr_mock.assert_called_once_with(github_access_token=GITHUB_ACCESS, org=org, repo=repo)

    assert doof.said("Release notes since {}".format(old_version))
    assert doof.said(notes)
    assert doof.said(f"And also! There is a release already in progress: {release_pr.url}")


async def test_release_notes_no_new_notes(doof, test_repo, test_repo_directory, mocker):
    """Doof should show that there are no new commits"""
    mocker.patch(
        'bot.init_working_dir', side_effect=async_context_manager_yielder(test_repo_directory)
    )
    old_version = "0.1.2"
    update_version_mock = mocker.async_patch('bot.update_version', autospec=True, return_value=old_version)
    notes = "no new commits"
    create_release_notes_mock = mocker.async_patch('bot.create_release_notes', return_value=notes)
    org, repo = get_org_and_repo(test_repo.repo_url)
    get_release_pr_mock = mocker.async_patch('bot.get_release_pr', return_value=None)
    any_new_commits_mock = mocker.async_patch('bot.any_new_commits', return_value=False)

    await doof.run_command(
        manager='mitodl_user',
        channel_id=test_repo.channel_id,
        words=['release', 'notes'],
    )

    any_new_commits_mock.assert_called_once_with(old_version, base_branch="master", root=test_repo_directory)
    update_version_mock.assert_called_once_with(
        repo_info=test_repo, new_version="9.9.9", working_dir=test_repo_directory
    )
    create_release_notes_mock.assert_called_once_with(
        old_version, with_checkboxes=False, base_branch="master", root=test_repo_directory
    )
    get_release_pr_mock.assert_called_once_with(github_access_token=GITHUB_ACCESS, org=org, repo=repo)

    assert doof.said("Release notes since {}".format(old_version))
    assert not doof.said("Start a new release?")


async def test_release_notes_buttons(doof, test_repo, test_repo_directory, mocker):
    """Doof should show release notes and then offer buttons to start a release"""
    mocker.patch(
        'bot.init_working_dir', side_effect=async_context_manager_yielder(test_repo_directory)
    )
    old_version = "0.1.2"
    update_version_mock = mocker.async_patch('bot.update_version', autospec=True, return_value=old_version)
    notes = "some notes"
    create_release_notes_mock = mocker.async_patch('bot.create_release_notes', return_value=notes)
    org, repo = get_org_and_repo(test_repo.repo_url)
    get_release_pr_mock = mocker.async_patch('bot.get_release_pr', return_value=None)
    any_new_commits_mock = mocker.async_patch('bot.any_new_commits', return_value=True)

    await doof.run_command(
        manager='mitodl_user',
        channel_id=test_repo.channel_id,
        words=['release', 'notes'],
    )

    any_new_commits_mock.assert_called_once_with(old_version, base_branch="master", root=test_repo_directory)
    update_version_mock.assert_called_once_with(
        repo_info=test_repo, new_version="9.9.9", working_dir=test_repo_directory
    )
    create_release_notes_mock.assert_called_once_with(
        old_version, with_checkboxes=False, base_branch="master", root=test_repo_directory
    )
    get_release_pr_mock.assert_called_once_with(github_access_token=GITHUB_ACCESS, org=org, repo=repo)

    assert doof.said("Release notes since {}".format(old_version))
    assert doof.said(notes)
    minor_version, patch_version = next_versions(old_version)
    assert doof.said("Start a new release?", attachments=[
        {
            'fallback': 'New release',
            'callback_id': 'new_release',
            'actions': [
                {'name': 'minor_release', 'text': minor_version, 'value': minor_version, 'type': 'button'},
                {'name': 'patch_release', 'text': patch_version, 'value': patch_version, 'type': 'button'},
                {'name': 'cancel', 'text': "Dismiss", 'value': "cancel", 'type': 'button', "style": "danger"}
            ]
        }
    ])
    assert not doof.said("And also! There is a release already in progress")


async def test_version(doof, test_repo, mocker):
    """
    Doof should tell you what version the latest release was
    """
    a_hash = 'hash'
    version = '1.2.3'
    fetch_release_hash_mock = mocker.async_patch('bot.fetch_release_hash', return_value=a_hash)
    get_version_tag_mock = mocker.async_patch('bot.get_version_tag', return_value="v{}".format(version))
    await doof.run_command(
        manager='mitodl_user',
        channel_id=test_repo.channel_id,
        words=['version'],
    )
    assert doof.said(
        "Wait a minute! My evil scheme is at version {}!".format(version)
    )

    fetch_release_hash_mock.assert_called_once_with(test_repo.prod_hash_url)
    get_version_tag_mock.assert_called_once_with(
        github_access_token=GITHUB_ACCESS,
        repo_url=test_repo.repo_url,
        commit_hash=a_hash,
    )


@pytest.mark.parametrize("deployment_server_type, expected_url", [
    [PROD, WEB_TEST_REPO_INFO.prod_hash_url],
    [RC, WEB_TEST_REPO_INFO.rc_hash_url],
    [CI, WEB_TEST_REPO_INFO.ci_hash_url]
])
async def test_hash(doof, test_repo, mocker, deployment_server_type, expected_url):
    """
    Doof should tell you what the latest commit was on production
    """
    a_hash = 'hash'
    message = "def876 A merged PR (#97)"
    fetch_release_hash_mock = mocker.async_patch('bot.fetch_release_hash', return_value=a_hash)
    get_version_tag_mock = mocker.async_patch('bot.get_commit_oneline_message', return_value=message)
    await doof.run_command(
        manager='mitodl_user',
        channel_id=test_repo.channel_id,
        words=['hash', deployment_server_type],
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
@pytest.mark.parametrize("command", ['release', 'start release'])
async def test_release(doof, test_repo, mocker, command):
    """
    Doof should do a release when asked
    """
    version = '1.2.3'
    pr = ReleasePR(
        version=version,
        url='http://new.url',
        body='Release PR body',
    )
    get_release_pr_mock = mocker.async_patch('bot.get_release_pr', side_effect=[None, pr, pr])
    release_mock = mocker.async_patch('bot.release')

    wait_for_deploy_sync_mock = mocker.async_patch('bot.wait_for_deploy')
    authors = {'author1', 'author2'}
    mocker.async_patch('bot.get_unchecked_authors', return_value=authors)

    wait_for_checkboxes_sync_mock = mocker.async_patch('bot.Bot.wait_for_checkboxes')

    command_words = command.split() + [version]
    me = 'mitodl_user'
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
        watch_branch='release-candidate',
    )
    assert doof.said("Now deploying to RC...")
    for channel_id in [test_repo.channel_id, ANNOUNCEMENTS_CHANNEL.channel_id]:
        assert doof.said(
            f"Release {pr.version} for {test_repo.name} was deployed at {remove_path_from_url(test_repo.rc_hash_url)}!",
            channel_id=channel_id,
        )
    assert wait_for_checkboxes_sync_mock.called is True


# pylint: disable=too-many-locals
async def test_hotfix_release(doof, test_repo, test_repo_directory, mocker):
    """
    Doof should do a hotfix when asked
    """
    mocker.patch(
        'bot.init_working_dir', side_effect=async_context_manager_yielder(test_repo_directory)
    )
    commit_hash = 'uthhg983u4thg9h5'
    version = '0.1.2'
    pr = ReleasePR(
        version=version,
        url='http://new.url',
        body='Release PR body',
    )
    get_release_pr_mock = mocker.async_patch('bot.get_release_pr', side_effect=[None, pr, pr])
    release_mock = mocker.async_patch('bot.release')

    wait_for_deploy_sync_mock = mocker.async_patch('bot.wait_for_deploy')
    authors = {'author1', 'author2'}
    mocker.async_patch('bot.get_unchecked_authors', return_value=authors)

    wait_for_checkboxes_sync_mock = mocker.async_patch('bot.Bot.wait_for_checkboxes')

    old_version = "0.1.1"
    update_version_mock = mocker.async_patch('bot.update_version', autospec=True, return_value=old_version)

    command_words = ['hotfix', commit_hash]
    me = 'mitodl_user'
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
    update_version_mock.assert_called_once_with(
        repo_info=test_repo, new_version="9.9.9", working_dir=test_repo_directory
    )
    release_mock.assert_called_once_with(
        github_access_token=GITHUB_ACCESS,
        repo_info=test_repo,
        new_version=pr.version,
        branch='release',
        commit_hash=commit_hash,
    )
    wait_for_deploy_sync_mock.assert_called_once_with(
        github_access_token=GITHUB_ACCESS,
        repo_url=test_repo.repo_url,
        hash_url=test_repo.rc_hash_url,
        watch_branch='release-candidate',
    )
    assert doof.said("Now deploying to RC...")
    assert wait_for_checkboxes_sync_mock.called is True


@pytest.mark.parametrize("command", ['release', 'start release'])
async def test_release_in_progress(doof, test_repo, mocker, command):
    """
    If a release is already in progress doof should fail
    """
    version = '1.2.3'
    url = 'http://fake.release.pr'
    mocker.async_patch('bot.get_release_pr', return_value=ReleasePR(
        version=version,
        url=url,
        body='Release PR body',
    ))

    command_words = command.split() + [version]
    with pytest.raises(ReleaseException) as ex:
        await doof.run_command(
            manager='mitodl_user',
            channel_id=test_repo.channel_id,
            words=command_words,
        )
    assert ex.value.args[0] == "A release is already in progress: {}".format(url)


@pytest.mark.parametrize("command", ['release', 'start release'])
async def test_release_bad_version(doof, test_repo, command):
    """
    If the version doesn't parse correctly doof should fail
    """
    command_words = command.split() + ['a.b.c']
    await doof.run_command(
        manager='mitodl_user',
        channel_id=test_repo.channel_id,
        words=command_words,
    )
    assert doof.said(
        'having trouble figuring out what that means',
    )


@pytest.mark.parametrize("command", ['release', 'start release'])
async def test_release_no_args(doof, test_repo, command):
    """
    If no version is given doof should complain
    """
    command_words = command.split()
    await doof.run_command(
        manager='mitodl_user',
        channel_id=test_repo.channel_id,
        words=command_words,
    )
    assert doof.said(
        "Careful, careful. I expected 1 words but you said 0.",
    )


async def test_release_library(doof, library_test_repo, mocker):
    """Do a library release"""
    version = '1.2.3'
    pr = ReleasePR(
        version=version,
        url='http://new.url',
        body='Release PR body',
    )
    get_release_pr_mock = mocker.async_patch('bot.get_release_pr', side_effect=[None, pr, pr])
    release_mock = mocker.async_patch('bot.release')

    command_words = ['release', version]
    me = 'mitodl_user'
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
                'actions': [
                    {
                        'name': 'finish_release', 'text': 'Finish the release', 'type': 'button',
                        "confirm": {
                            "title": "Are you sure?",
                            "ok_text": "Finish the release",
                            "dismiss_text": "Cancel",
                        }
                    },
                ],
                'callback_id': 'finish_release', 'fallback': 'Finish the release'
            }
        ]
    )


@pytest.mark.parametrize("project_type", [WEB_APPLICATION_TYPE, LIBRARY_TYPE])
async def test_finish_release(doof, mocker, project_type):
    """
    Doof should finish a release when asked
    """
    version = '1.2.3'
    pr = ReleasePR(
        version=version,
        url='http://new.url',
        body='Release PR body',
    )
    get_release_pr_mock = mocker.async_patch('bot.get_release_pr', return_value=pr)
    finish_release_mock = mocker.async_patch('bot.finish_release')

    wait_for_deploy_prod_mock = mocker.async_patch('bot.Bot._wait_for_deploy_prod')

    test_repo = LIBRARY_TEST_REPO_INFO if project_type == LIBRARY_TYPE else WEB_TEST_REPO_INFO

    await doof.run_command(
        manager='mitodl_user',
        channel_id=test_repo.channel_id,
        words=['finish', 'release'],
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
        assert doof.said('deploying to production...')
        wait_for_deploy_prod_mock.assert_called_once_with(
            doof,
            repo_info=test_repo
        )


async def test_finish_release_no_release(doof, test_repo, mocker):
    """
    If there's no release to finish doof should complain
    """
    get_release_pr_mock = mocker.async_patch('bot.get_release_pr', return_value=None)
    with pytest.raises(ReleaseException) as ex:
        await doof.run_command(
            manager='mitodl_user',
            channel_id=test_repo.channel_id,
            words=['finish', 'release'],
        )
    assert 'No release currently in progress' in ex.value.args[0]
    org, repo = get_org_and_repo(test_repo.repo_url)
    get_release_pr_mock.assert_called_once_with(
        github_access_token=GITHUB_ACCESS,
        org=org,
        repo=repo,
    )


async def test_delay_message(doof, test_repo, mocker):
    """
    Doof should finish a release when asked
    """
    now = datetime.now(tz=doof.timezone)
    seconds_diff = 30
    future = now + timedelta(seconds=seconds_diff)
    next_workday_mock = mocker.patch('bot.next_workday_at_10', autospec=True, return_value=future)

    sleep_sync_mock = mocker.async_patch('asyncio.sleep')

    mocker.async_patch('bot.get_unchecked_authors', return_value={'author1'})

    await doof.wait_for_checkboxes_reminder(repo_info=test_repo)
    assert doof.said(
        'The following authors have not yet checked off their boxes for doof_repo: author1',
    )
    assert next_workday_mock.call_count == 1
    assert abs(next_workday_mock.call_args[0][0] - now).total_seconds() < 1
    assert next_workday_mock.call_args[0][0].tzinfo.zone == doof.timezone.zone
    assert sleep_sync_mock.call_count == 1
    assert abs(seconds_diff - sleep_sync_mock.call_args[0][0]) < 1  # pylint: disable=unsubscriptable-object


async def test_webhook_different_callback_id(doof, mocker):
    """
    If the callback id doesn't match nothing should be done
    """
    finish_release_mock = mocker.patch(
        'bot.finish_release', autospec=True
    )
    await doof.handle_webhook(
        webhook_dict={
            "token": "token",
            "callback_id": "xyz",
            "channel": {
                "id": "doof"
            },
            "user": {
                "id": "doofenshmirtz"
            },
            "message_ts": "123.45",
            "original_message": {
                "text": "Doof's original text",
            }
        },
    )

    assert finish_release_mock.called is False


# pylint: disable=too-many-arguments
async def test_webhook_finish_release(doof, mocker, test_repo, library_test_repo):
    """
    Finish the release
    """
    doof.repos_info = [test_repo, library_test_repo]

    pr_body = ReleasePR(
        version='version',
        url='url',
        body='body',
    )
    get_release_pr_mock = mocker.async_patch('bot.get_release_pr', return_value=pr_body)
    finish_release_mock = mocker.async_patch('bot.finish_release')
    wait_for_deploy_prod_mock = mocker.async_patch('bot.Bot._wait_for_deploy_prod')

    await doof.handle_webhook(
        webhook_dict={
            "token": "token",
            "callback_id": FINISH_RELEASE_ID,
            "channel": {
                "id": "doof"
            },
            "user": {
                "id": "doofenshmirtz"
            },
            "message_ts": "123.45",
            "original_message": {
                "text": "Doof's original text",
            }
        },
    )

    repo_url = test_repo.repo_url
    org, repo = get_org_and_repo(repo_url)
    wait_for_deploy_prod_mock.assert_any_call(
        doof,
        repo_info=test_repo,
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
    get_release_pr_mock = mocker.async_patch('bot.get_release_pr')
    finish_release_mock = mocker.async_patch('bot.finish_release', side_effect=KeyError)

    with pytest.raises(KeyError):
        await doof.handle_webhook(
            webhook_dict={
                "token": "token",
                "callback_id": FINISH_RELEASE_ID,
                "channel": {
                    "id": "doof"
                },
                "user": {
                    "id": "doofenshmirtz"
                },
                "message_ts": "123.45",
                "original_message": {
                    "text": "Doof's original text",
                }
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
    org, repo = get_org_and_repo(test_repo.repo_url)
    get_release_pr_mock = mocker.async_patch('bot.get_release_pr', return_value=None)

    release_mock = mocker.async_patch('bot.Bot._web_application_release')

    version = "3.4.5"
    await doof.handle_webhook(
        webhook_dict={
            "token": "token",
            "callback_id": NEW_RELEASE_ID,
            "channel": {
                "id": "doof"
            },
            "user": {
                "id": "doofenshmirtz"
            },
            "message_ts": "123.45",
            "original_message": {
                "text": "Doof's original text",
            },
            "actions": [
                {
                    "value": version,
                    "name": "minor_release",
                }
            ]
        },
    )

    assert doof.said(f"Starting release {version}...")
    assert release_mock.call_count == 1
    assert release_mock.call_args[0][1].args == [version]
    assert not doof.said("Error")
    get_release_pr_mock.assert_called_once_with(github_access_token=GITHUB_ACCESS, org=org, repo=repo)


async def test_webhook_start_release_fail(doof, mocker):
    """
    If starting the release fails we should update the button to show the error
    """
    release_mock = mocker.patch('bot.Bot.release_command', autospec=True, side_effect=ZeroDivisionError)
    version = "3.4.5"
    with pytest.raises(ZeroDivisionError):
        await doof.handle_webhook(
            webhook_dict={
                "token": "token",
                "callback_id": NEW_RELEASE_ID,
                "channel": {
                    "id": "doof"
                },
                "user": {
                    "id": "doofenshmirtz"
                },
                "message_ts": "123.45",
                "original_message": {
                    "text": "Doof's original text",
                },
                "actions": [
                    {
                        "value": version,
                        "name": "minor_release",
                    }
                ]
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
            "channel": {
                "id": "doof"
            },
            "user": {
                "id": "doofenshmirtz"
            },
            "message_ts": timestamp,
            "original_message": {
                "text": "Doof's original text",
            },
            "actions": [
                {
                    "value": version,
                    "name": "cancel",
                }
            ]
        },
    )

    assert doof.said(timestamp)
    assert not doof.said("Starting release")


async def test_uptime(doof, mocker, test_repo):
    """Uptime should show how much time the bot has been awake"""
    later = doof.doof_boot + timedelta(seconds=140)
    mocker.patch('bot.now_in_utc', autospec=True, return_value=later)
    await doof.run_command(
        manager='mitodl_user',
        channel_id=test_repo.channel_id,
        words=['uptime'],
    )
    assert doof.said("Awake for 2 minutes.")


async def test_reset(doof, test_repo):
    """Reset should cause a reset"""
    with pytest.raises(ResetException):
        await doof.run_command(
            manager='mitodl_user',
            channel_id=test_repo.channel_id,
            words=['reset'],
        )


@pytest.mark.parametrize("command", [["publish"], ["upload", "to", "pypi"]])
@pytest.mark.parametrize("packaging_tool", [NPM, SETUPTOOLS])
async def test_publish(doof, library_test_repo, mocker, command, packaging_tool):
    """the publish command should start the upload process"""
    publish_patched = mocker.async_patch('bot.publish')

    library_test_repo = RepoInfo(**{
        **library_test_repo._asdict(),
        "packaging_tool": packaging_tool
    })
    doof.repos_info = [library_test_repo]
    version = "3.4.5"

    await doof.run_command(
        manager='me',
        channel_id=library_test_repo.channel_id,
        words=[*command, version],
    )

    publish_patched.assert_called_once_with(
        repo_info=library_test_repo,
        github_access_token=GITHUB_ACCESS,
        version=version,
        npm_token=NPM_TOKEN,
    )
    server = "PyPI" if packaging_tool == SETUPTOOLS else "the npm registry"
    assert doof.said(f"Successfully uploaded {version} to {server}.")


@pytest.mark.parametrize("command,project_type", [
    ['version', LIBRARY_TYPE],
    ['wait for checkboxes', LIBRARY_TYPE],
    ['upload to pypi 1.2.3', WEB_APPLICATION_TYPE],
    ['publish 1.2.3', WEB_APPLICATION_TYPE],
])  # pylint: disable=too-many-arguments
async def test_invalid_project_type(doof, test_repo, library_test_repo, command, project_type):
    """
    Compare incompatible commands with project types
    """
    repo = test_repo if project_type == WEB_APPLICATION_TYPE else library_test_repo
    other_type = LIBRARY_TYPE if project_type == WEB_APPLICATION_TYPE else WEB_APPLICATION_TYPE

    await doof.run_command(
        manager='mitodl_user',
        channel_id=repo.channel_id,
        words=command.split(),
    )

    assert doof.said(f'That command is only for {other_type} projects but this is a {project_type} project.')


@pytest.mark.parametrize('command', [
    'release 1.2.3',
    'start release 1.2.3',
    'finish release',
    'wait for checkboxes',
    'upload to pypi 1.2.3',
    'publish 1.2.3',
    'release notes',
])
async def test_command_without_repo(doof, command):
    """
    Test that commands won't work on channels without a repo
    """
    await doof.run_command(
        manager='mitodl_user',
        channel_id='not_a_repo_channel',
        words=command.split(),
    )

    assert doof.said(
        'That command requires a repo but this channel is not attached to any project.'
    )


@pytest.mark.parametrize("is_announcement", [True, False])
async def test_announcement(is_announcement, doof):
    """
    Test that an announcement will get sent to multiple channels
    """
    text = "some text here"
    await doof.say(
        channel_id=LIBRARY_TEST_REPO_INFO.channel_id,
        text=text,
        attachments=[{"some": "attachment"}],
        message_type="a message",
        is_announcement=is_announcement
    )
    assert doof.said(text, channel_id=LIBRARY_TEST_REPO_INFO.channel_id) is True
    assert doof.said(text, channel_id=ANNOUNCEMENTS_CHANNEL.channel_id) is is_announcement


async def test_help(doof):
    """
    Test that doof will show help text
    """
    await doof.run_command(
        manager='mitodl_user',
        channel_id='not_a_repo_channel',
        words=["help"],
    )

    assert doof.said("*help*: Show available commands")


@pytest.mark.parametrize("speak_initial, has_checkboxes", [
    [True, False],
    [True, True],
    [False, False],
    [False, True],
])
async def test_wait_for_checkboxes(
        mocker, doof, test_repo, speak_initial, has_checkboxes
):
    """wait_for_checkboxes should poll github, parse checkboxes and see if all are checked"""
    org, repo = get_org_and_repo(test_repo.repo_url)
    channel_id = test_repo.channel_id

    pr = ReleasePR('version', f'https://github.com/{org}/{repo}/pulls/123456', 'body')
    get_release_pr_mock = mocker.async_patch('bot.get_release_pr', return_value=pr)
    get_unchecked_patch = mocker.async_patch('bot.get_unchecked_authors', side_effect=[
        {'author1', 'author2', 'author3'},
        {'author2'},
        set(),
    ] if has_checkboxes else [set()])
    doof.slack_users = [
        {"profile": {"real_name": name}, "id": username} for (name, username) in [
            ("Author 1", "author1"),
            ("Author 2", "author2"),
            ("Author 3", "author3"),
        ]
    ]

    sleep_sync_mock = mocker.async_patch('asyncio.sleep')

    me = 'mitodl_user'
    await doof.wait_for_checkboxes(
        manager=me,
        repo_info=test_repo,
        speak_initial=speak_initial,
    )
    if speak_initial:
        assert doof.said("isn't evil enough until all the checkboxes are checked")
    get_unchecked_patch.assert_any_call(
        github_access_token=GITHUB_ACCESS,
        org=org,
        repo=repo,
    )
    assert get_unchecked_patch.call_count == (3 if has_checkboxes else 1)
    assert sleep_sync_mock.call_count == (2 if has_checkboxes else 0)
    get_release_pr_mock.assert_called_once_with(github_access_token=GITHUB_ACCESS, org=org, repo=repo)
    if speak_initial or has_checkboxes:
        assert doof.said(
            "All checkboxes checked off. Release {version} is ready for the Merginator {name}".format(
                version=pr.version,
                name=format_user_id(me),
            ),
            attachments=[
                {
                    'actions': [
                        {
                            'name': 'finish_release', 'text': 'Finish the release', 'type': 'button',
                            "confirm": {
                                "title": "Are you sure?",
                                "ok_text": "Finish the release",
                                "dismiss_text": "Cancel",
                            }
                        },
                    ],
                    'callback_id': 'finish_release', 'fallback': 'Finish the release'
                }
            ]
        )
    if speak_initial:
        assert doof.said(f"PR is up at {pr.url}. These people have commits in this release:", channel_id=channel_id)
    if has_checkboxes:
        assert not doof.said(
            "Thanks for checking off your boxes <@author1>, <@author2>, <@author3>!", channel_id=channel_id
        )
        assert doof.said(
            "Thanks for checking off your boxes <@author1>, <@author3>!", channel_id=channel_id
        )
        assert doof.said(
            "Thanks for checking off your boxes <@author2>!", channel_id=channel_id
        )


# pylint: disable=too-many-arguments
@pytest.mark.parametrize("repo_info, has_release_pr, has_expected", [
    [WEB_TEST_REPO_INFO, False, False],
    [WEB_TEST_REPO_INFO, True, True],
    [LIBRARY_TEST_REPO_INFO, False, False],
    [LIBRARY_TEST_REPO_INFO, True, False],
    [ANNOUNCEMENTS_CHANNEL, False, False],
    [ANNOUNCEMENTS_CHANNEL, True, False],
])
async def test_startup(doof, mocker, repo_info, has_release_pr, has_expected):
    """
    Test that doof will show help text
    """
    doof.repos_info = [repo_info]
    release_pr = ReleasePR(
        version="version",
        url=repo_info.repo_url,
        body='Release PR body',
    )
    mocker.async_patch('bot.get_release_pr', return_value=(
        release_pr if has_release_pr else None
    ))
    wait_for_checkboxes_mock = mocker.async_patch('bot.Bot.wait_for_checkboxes')
    wait_for_deploy_mock = mocker.async_patch('bot.Bot.wait_for_deploy')

    await doof.startup()
    # iterate once through event loop
    await asyncio.sleep(0)
    assert not doof.said("isn't evil enough until all the checkboxes are checked")

    if has_expected:
        wait_for_checkboxes_mock.assert_called_once_with(doof, manager=None, repo_info=repo_info, speak_initial=False)
        wait_for_deploy_mock.assert_called_once_with(doof, repo_info=repo_info)
    else:
        assert wait_for_checkboxes_mock.call_count == 0
        assert wait_for_deploy_mock.call_count == 0


@pytest.mark.parametrize("needs_deploy_rc", [True, False])
@pytest.mark.parametrize("needs_deploy_prod", [True, False])
async def test_wait_for_deploy(doof, test_repo, needs_deploy_rc, needs_deploy_prod, mocker):
    """bot.wait_for_deploy should check if deploys are needed for RC or PROD"""

    def _is_release_deployed(branch, **kwargs):  # pylint: disable=unused-argument
        """Helper function to provide right value for is_release_deployed"""
        if branch == "release":
            return not needs_deploy_prod
        elif branch == "release-candidate":
            return not needs_deploy_rc
        raise Exception("Unexpected branch")

    is_release_deployed_mock = mocker.async_patch(
        'bot.is_release_deployed', side_effect=_is_release_deployed
    )
    wait_for_deploy_rc_mock = mocker.async_patch('bot.Bot._wait_for_deploy_rc')
    wait_for_deploy_prod_mock = mocker.async_patch('bot.Bot._wait_for_deploy_prod')

    await doof.wait_for_deploy(repo_info=test_repo)

    is_release_deployed_mock.assert_any_call(
        github_access_token=GITHUB_ACCESS,
        repo_url=test_repo.repo_url,
        hash_url=test_repo.prod_hash_url,
        branch="release",
    )
    is_release_deployed_mock.assert_any_call(
        github_access_token=GITHUB_ACCESS,
        repo_url=test_repo.repo_url,
        hash_url=test_repo.rc_hash_url,
        branch="release-candidate",
    )
    if needs_deploy_rc:
        wait_for_deploy_rc_mock.assert_called_once_with(doof, repo_info=test_repo)
    else:
        assert wait_for_deploy_rc_mock.called is False
    if needs_deploy_prod:
        wait_for_deploy_prod_mock.assert_called_once_with(doof, repo_info=test_repo)
    else:
        assert wait_for_deploy_prod_mock.called is False


async def test_wait_for_deploy_rc(doof, test_repo, mocker):
    """Bot._wait_for_deploy_prod should wait until repo has been deployed to RC"""
    wait_for_deploy_mock = mocker.async_patch('bot.wait_for_deploy')
    org, repo = get_org_and_repo(test_repo.repo_url)
    release_pr = ReleasePR('version', f'https://github.com/{org}/{repo}/pulls/123456', 'body')
    get_release_pr_mock = mocker.async_patch('bot.get_release_pr', return_value=release_pr)

    await doof._wait_for_deploy_rc(repo_info=test_repo)  # pylint: disable=protected-access

    wait_for_deploy_mock.assert_called_once_with(
        github_access_token=GITHUB_ACCESS,
        repo_url=test_repo.repo_url,
        hash_url=test_repo.rc_hash_url,
        watch_branch='release-candidate'
    )
    get_release_pr_mock.assert_called_once_with(
        github_access_token=GITHUB_ACCESS,
        org=org,
        repo=repo,
    )


async def test_wait_for_deploy_prod(doof, test_repo, mocker):
    """Bot._wait_for_deploy_prod should wait until repo has been deployed to production"""
    wait_for_deploy_mock = mocker.async_patch('bot.wait_for_deploy')
    version = "1.2.345"
    get_version_tag_mock = mocker.async_patch('bot.get_version_tag', return_value="v{}".format(version))
    channel_id = test_repo.channel_id

    await doof._wait_for_deploy_prod(repo_info=test_repo)  # pylint: disable=protected-access

    get_version_tag_mock.assert_called_once_with(
        github_access_token=GITHUB_ACCESS,
        repo_url=test_repo.repo_url,
        commit_hash="origin/release",
    )
    assert doof.said(
        f"My evil scheme v{version} for {test_repo.name} has been released "
        f"to production at {remove_path_from_url(test_repo.prod_hash_url)}. "
        "And by 'released', I mean completely...um...leased.", channel_id=channel_id
    )
    wait_for_deploy_mock.assert_called_once_with(
        github_access_token=GITHUB_ACCESS,
        repo_url=test_repo.repo_url,
        hash_url=test_repo.prod_hash_url,
        watch_branch='release'
    )


async def test_issue_release_notes(doof, test_repo, mocker):
    """issue release notes should list closed issues over the last seven days"""
    org, repo = get_org_and_repo(test_repo.repo_url)
    channel_id = test_repo.channel_id
    pr = make_pr(123, "A PR")
    fetch_prs = mocker.patch('bot.fetch_pull_requests_since_date', return_value=[pr])
    tups = [
        (pr, [(make_issue(333), make_parsed_issue(333, False))])
    ]
    fetch_issues = mocker.patch('bot.fetch_issues_for_pull_requests', return_value=async_gen_wrapper(tups))
    notes = "some release notes"
    make_release_notes = mocker.patch('bot.make_issue_release_notes', return_value=notes)
    await doof.issue_release_notes(CommandArgs(
        repo_info=test_repo,
        channel_id=test_repo.channel_id,
        args=[],
        manager="me"
    ))

    assert doof.said("Release notes for issues closed by PRs", channel_id=channel_id)
    assert doof.said(notes, channel_id=channel_id)

    fetch_prs.assert_called_once_with(
        github_access_token=GITHUB_ACCESS,
        org=org,
        repo=repo,
        since=(now_in_utc() - timedelta(days=7)).date()
    )
    fetch_issues.assert_called_once_with(
        github_access_token=GITHUB_ACCESS,
        pull_requests=[pr],
    )
    make_release_notes.assert_called_once_with(
        tups,
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
            }
        }
    )

    assert doof.said("hello!")


async def test_handle_event_no_callback(doof, mocker):
    """
    If it's not a callback event, ignore it
    """
    log_info = mocker.patch('bot.log.info')
    handle_message = mocker.patch('bot.Bot.handle_message')
    await doof.handle_event(
        webhook_dict={
            "token": "token",
            "type": "different_kind",
        }
    )

    assert "Received event other than event callback or challenge" in log_info.call_args[0][0]
    assert handle_message.called is False


async def test_handle_event_not_a_message(doof, mocker):
    """
    If the event is not a message type, ignore it
    """
    log_info = mocker.patch('bot.log.info')
    handle_message = mocker.patch('bot.Bot.handle_message')
    await doof.handle_event(
        webhook_dict={
            "token": "token",
            "type": "event_callback",
            "event": {
                "type": "other_kind",
            }
        }
    )

    assert "Received event other than message" in log_info.call_args[0][0]
    assert handle_message.called is False


async def test_handle_event_no_message(doof, mocker):
    """
    If it's an empty message, ingore it
    """
    handle_message = mocker.patch('bot.Bot.handle_message')
    await doof.handle_event(
        webhook_dict={
            "token": "token",
            "type": "event_callback",
            "event": {
                "type": "message",
                "text": "",
                "user": "manager",
            }
        }
    )

    assert handle_message.called is False


async def test_handle_event_message_changed(doof, mocker):
    """
    Edits to messages are currently ignored
    """
    handle_message = mocker.patch('bot.Bot.handle_message')
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
            }
        }
    )

    assert handle_message.called is False
