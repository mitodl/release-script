"""Tests for Doof"""
from datetime import datetime, timedelta
from unittest.mock import Mock

import pytest
import pytz

from bot import (
    Bot,
    FINISH_RELEASE_ID
)
from conftest import (
    ANNOUNCEMENTS_CHANNEL,
    LIBRARY_TEST_REPO_INFO,
    WEB_TEST_REPO_INFO,
)
from constants import (
    LIBRARY_TYPE,
    TRAVIS_FAILURE,
    TRAVIS_SUCCESS,
    WEB_APPLICATION_TYPE,
)
from exception import (
    ReleaseException,
    ResetException,
)
from github import get_org_and_repo
from lib import (
    format_user_id,
    ReleasePR,
)


pytestmark = pytest.mark.asyncio


GITHUB_ACCESS = 'github'
SLACK_ACCESS = 'slack'


# pylint: disable=redefined-outer-name
class DoofSpoof(Bot):
    """Testing bot"""
    def __init__(self):
        """Since the testing bot isn't contacting slack or github we don't need these tokens here"""
        super().__init__(
            websocket=Mock(),
            slack_access_token=SLACK_ACCESS,
            github_access_token=GITHUB_ACCESS,
            timezone=pytz.timezone("America/New_York"),
            repos_info=[WEB_TEST_REPO_INFO, LIBRARY_TEST_REPO_INFO, ANNOUNCEMENTS_CHANNEL],
        )

        self.slack_users = []
        self.messages = {}

    def lookup_users(self):
        """Users in the channel"""
        return self.slack_users

    def _say(self, *, channel_id, text=None, attachments=None, message_type=None):
        """Quick and dirty message recording"""
        if channel_id not in self.messages:
            self.messages[channel_id] = []
        self.messages[channel_id].append(f"{text} {attachments} {message_type}")

    async def typing(self, channel_id):
        """Ignore typing"""

    async def update_message(self, *, channel_id, timestamp, text=None, attachments=None):
        """
        Record message updates
        """
        if channel_id not in self.messages:
            self.messages[channel_id] = []
        self.messages[channel_id].append(f"{text} {attachments} {timestamp}")

    def said(self, text, channel_id=None):
        """Did doof say this thing?"""
        for message_channel_id, messages in self.messages.items():
            if channel_id is None or message_channel_id == channel_id:
                for message in messages:
                    if text in message:
                        return True
        return False


@pytest.fixture
def doof():
    """Create a Doof"""
    yield DoofSpoof()


async def test_release_notes(doof, test_repo, event_loop, mocker):
    """Doof should show release notes"""
    old_version = "0.1.2"
    update_version_mock = mocker.patch('bot.update_version', autospec=True, return_value=old_version)
    notes = "some notes"
    create_release_notes_mock = mocker.patch('bot.create_release_notes', autospec=True, return_value=notes)
    org, repo = get_org_and_repo(test_repo.repo_url)
    release_pr = ReleasePR('version', f'https://github.com/{org}/{repo}/pulls/123456', 'body')
    get_release_pr_mock = mocker.patch('bot.get_release_pr', autospec=True, return_value=release_pr)

    await doof.run_command(
        manager='mitodl_user',
        channel_id=test_repo.channel_id,
        words=['release', 'notes'],
        loop=event_loop,
    )

    update_version_mock.assert_called_once_with("9.9.9")
    create_release_notes_mock.assert_called_once_with(old_version, with_checkboxes=False)
    get_release_pr_mock.assert_called_once_with(github_access_token=GITHUB_ACCESS, org=org, repo=repo)

    assert doof.said("Release notes since {}".format(old_version))
    assert doof.said(notes)
    assert doof.said(f"And also! There is a release already in progress: {release_pr.url}")


async def test_version(doof, test_repo, event_loop, mocker):
    """
    Doof should tell you what version the latest release was
    """
    a_hash = 'hash'
    version = '1.2.3'
    fetch_release_hash_mock = mocker.patch('bot.fetch_release_hash', autospec=True, return_value=a_hash)
    get_version_tag_mock = mocker.patch('bot.get_version_tag', autospec=True, return_value="v{}".format(version))
    await doof.run_command(
        manager='mitodl_user',
        channel_id=test_repo.channel_id,
        words=['version'],
        loop=event_loop,
    )
    assert doof.said(
        "Wait a minute! My evil scheme is at version {}!".format(version)
    )

    fetch_release_hash_mock.assert_called_once_with(test_repo.prod_hash_url)
    get_version_tag_mock.assert_called_once_with(GITHUB_ACCESS, test_repo.repo_url, a_hash)


async def test_typing(doof, test_repo, event_loop, mocker):
    """
    Doof should signal typing before any arbitrary command
    """
    typing_sync = mocker.Mock()

    async def typing_async(*args, **kwargs):
        """Wrap sync method to allow mocking"""
        typing_sync(*args, **kwargs)

    mocker.patch.object(doof, 'typing', typing_async)
    await doof.run_command(
        manager='mitodl_user',
        channel_id=test_repo.channel_id,
        words=['hi'],
        loop=event_loop,
    )
    assert doof.said("hello!")
    typing_sync.assert_called_once_with(test_repo.channel_id)


# pylint: disable=too-many-locals
@pytest.mark.parametrize("command", ['release', 'start release'])
async def test_release(doof, test_repo, event_loop, mocker, command):
    """
    Doof should do a release when asked
    """
    version = '1.2.3'
    pr = ReleasePR(
        version=version,
        url='http://new.url',
        body='Release PR body',
    )
    get_release_pr_mock = mocker.patch('bot.get_release_pr', autospec=True, side_effect=[None, pr, pr])
    release_mock = mocker.patch('bot.release', autospec=True)

    wait_for_deploy_sync_mock = mocker.Mock()

    async def wait_for_deploy_fake(*args, **kwargs):
        """await cannot be used with mock objects"""
        wait_for_deploy_sync_mock(*args, **kwargs)

    mocker.patch('bot.wait_for_deploy', wait_for_deploy_fake)
    authors = {'author1', 'author2'}
    mocker.patch('bot.get_unchecked_authors', return_value=authors)

    wait_for_checkboxes_sync_mock = mocker.Mock()
    async def wait_for_checkboxes_fake(*args, **kwargs):
        """await cannot be used with mock objects"""
        wait_for_checkboxes_sync_mock(*args, **kwargs)
    mocker.patch('bot.Bot.wait_for_checkboxes', wait_for_checkboxes_fake)

    command_words = command.split() + [version]
    me = 'mitodl_user'
    await doof.run_command(
        manager=me,
        channel_id=test_repo.channel_id,
        words=command_words,
        loop=event_loop,
    )

    org, repo = get_org_and_repo(test_repo.repo_url)
    get_release_pr_mock.assert_any_call(
        github_access_token=GITHUB_ACCESS,
        org=org,
        repo=repo,
    )
    release_mock.assert_called_once_with(
        github_access_token=GITHUB_ACCESS,
        repo_url=test_repo.repo_url,
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
            "These people have commits in this release: {}".format(', '.join(authors)),
            channel_id=channel_id,
        )
    assert wait_for_checkboxes_sync_mock.called is True


@pytest.mark.parametrize("command", ['release', 'start release'])
async def test_release_in_progress(doof, test_repo, event_loop, mocker, command):
    """
    If a release is already in progress doof should fail
    """
    version = '1.2.3'
    url = 'http://fake.release.pr'
    mocker.patch('bot.get_release_pr', autospec=True, return_value=ReleasePR(
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
            loop=event_loop,
        )
    assert ex.value.args[0] == "A release is already in progress: {}".format(url)


@pytest.mark.parametrize("command", ['release', 'start release'])
async def test_release_bad_version(doof, test_repo, event_loop, command):
    """
    If the version doesn't parse correctly doof should fail
    """
    command_words = command.split() + ['a.b.c']
    await doof.run_command(
        manager='mitodl_user',
        channel_id=test_repo.channel_id,
        words=command_words,
        loop=event_loop,
    )
    assert doof.said(
        'having trouble figuring out what that means',
    )


@pytest.mark.parametrize("command", ['release', 'start release'])
async def test_release_no_args(doof, test_repo, event_loop, command):
    """
    If no version is given doof should complain
    """
    command_words = command.split()
    await doof.run_command(
        manager='mitodl_user',
        channel_id=test_repo.channel_id,
        words=command_words,
        loop=event_loop,
    )
    assert doof.said(
        "Careful, careful. I expected 1 words but you said 0.",
    )


async def test_release_library(doof, library_test_repo, event_loop, mocker):
    """Do a library release"""
    version = '1.2.3'
    pr = ReleasePR(
        version=version,
        url='http://new.url',
        body='Release PR body',
    )
    get_release_pr_mock = mocker.patch('bot.get_release_pr', autospec=True, side_effect=[None, pr, pr])
    release_mock = mocker.patch('bot.release', autospec=True)
    finish_release_mock = mocker.patch('bot.finish_release', autospec=True)

    wait_for_travis_sync_mock = mocker.Mock()
    wait_for_travis_sync_mock.return_value = TRAVIS_SUCCESS

    async def wait_for_travis_fake(*args, **kwargs):
        """await cannot be used with mock objects"""
        return wait_for_travis_sync_mock(*args, **kwargs)
    mocker.patch('bot.wait_for_travis', wait_for_travis_fake)

    command_words = ['release', version]
    me = 'mitodl_user'
    await doof.run_command(
        manager=me,
        channel_id=library_test_repo.channel_id,
        words=command_words,
        loop=event_loop,
    )

    org, repo = get_org_and_repo(library_test_repo.repo_url)
    release_mock.assert_called_once_with(
        github_access_token=GITHUB_ACCESS,
        repo_url=library_test_repo.repo_url,
        new_version=pr.version,
    )
    wait_for_travis_sync_mock.assert_called_once_with(
        github_access_token=GITHUB_ACCESS,
        org=org,
        repo=repo,
        branch='release-candidate',
    )
    get_release_pr_mock.assert_called_once_with(
        github_access_token=GITHUB_ACCESS,
        org=org,
        repo=repo,
    )
    finish_release_mock.assert_called_once_with(
        github_access_token=GITHUB_ACCESS,
        repo_url=library_test_repo.repo_url,
        version=version,
        timezone=doof.timezone
    )
    assert doof.said(
        "My evil scheme {version} for {project} has been merged!".format(
            version=pr.version,
            project=library_test_repo.name,
        )
    )


async def test_release_library_failure(doof, library_test_repo, event_loop, mocker):
    """If a library release fails we shouldn't merge it"""
    version = '1.2.3'
    pr = ReleasePR(
        version=version,
        url='http://new.url',
        body='Release PR body',
    )
    mocker.patch('bot.get_release_pr', autospec=True, side_effect=[None, pr, pr])
    release_mock = mocker.patch('bot.release', autospec=True)
    finish_release_mock = mocker.patch('bot.finish_release', autospec=True)

    wait_for_travis_sync_mock = mocker.Mock()
    wait_for_travis_sync_mock.return_value = TRAVIS_FAILURE

    async def wait_for_travis_fake(*args, **kwargs):
        """await cannot be used with mock objects"""
        return wait_for_travis_sync_mock(*args, **kwargs)
    mocker.patch('bot.wait_for_travis', wait_for_travis_fake)

    command_words = ['release', version]
    me = 'mitodl_user'
    await doof.run_command(
        manager=me,
        channel_id=library_test_repo.channel_id,
        words=command_words,
        loop=event_loop,
    )

    org, repo = get_org_and_repo(library_test_repo.repo_url)
    release_mock.assert_called_once_with(
        github_access_token=GITHUB_ACCESS,
        repo_url=library_test_repo.repo_url,
        new_version=pr.version,
    )
    wait_for_travis_sync_mock.assert_called_once_with(
        github_access_token=GITHUB_ACCESS,
        org=org,
        repo=repo,
        branch='release-candidate',
    )
    assert finish_release_mock.call_count == 0
    assert doof.said(
        "Uh-oh, it looks like, uh, coffee break's over. During the release Travis had a failure."
    )


async def test_finish_release(doof, test_repo, event_loop, mocker):
    """
    Doof should finish a release when asked
    """
    version = '1.2.3'
    pr = ReleasePR(
        version=version,
        url='http://new.url',
        body='Release PR body',
    )
    get_release_pr_mock = mocker.patch('bot.get_release_pr', autospec=True, return_value=pr)
    finish_release_mock = mocker.patch('bot.finish_release', autospec=True)

    wait_for_deploy_sync_mock = mocker.Mock()

    async def wait_for_deploy_fake(*args, **kwargs):
        """await cannot be used with mock objects"""
        wait_for_deploy_sync_mock(*args, **kwargs)

    mocker.patch('bot.wait_for_deploy', wait_for_deploy_fake)

    await doof.run_command(
        manager='mitodl_user',
        channel_id=test_repo.channel_id,
        words=['finish', 'release'],
        loop=event_loop,
    )

    org, repo = get_org_and_repo(test_repo.repo_url)
    get_release_pr_mock.assert_called_once_with(
        github_access_token=GITHUB_ACCESS,
        org=org,
        repo=repo,
    )
    finish_release_mock.assert_called_once_with(
        github_access_token=GITHUB_ACCESS,
        repo_url=test_repo.repo_url,
        version=version,
        timezone=doof.timezone
    )
    assert doof.said('deploying to production...')
    wait_for_deploy_sync_mock.assert_called_once_with(
        github_access_token=GITHUB_ACCESS,
        repo_url=test_repo.repo_url,
        hash_url=test_repo.prod_hash_url,
        watch_branch='release',
    )
    assert doof.said('has been released to production')


async def test_finish_release_no_release(doof, test_repo, event_loop, mocker):
    """
    If there's no release to finish doof should complain
    """
    get_release_pr_mock = mocker.patch('bot.get_release_pr', autospec=True, return_value=None)
    with pytest.raises(ReleaseException) as ex:
        await doof.run_command(
            manager='mitodl_user',
            channel_id=test_repo.channel_id,
            words=['finish', 'release'],
            loop=event_loop,
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

    sleep_sync_mock = Mock()

    async def sleep_fake(*args, **kwargs):
        """await cannot be used with mock objects"""
        sleep_sync_mock(*args, **kwargs)

    mocker.patch('asyncio.sleep', sleep_fake)

    mocker.patch('bot.get_unchecked_authors', return_value={'author1'})

    await doof.delay_message(test_repo)
    assert doof.said(
        'The following authors have not yet checked off their boxes for doof_repo: author1',
    )
    assert next_workday_mock.call_count == 1
    assert abs(next_workday_mock.call_args[0][0] - now).total_seconds() < 1
    assert next_workday_mock.call_args[0][0].tzinfo.zone == doof.timezone.zone
    assert sleep_sync_mock.call_count == 1
    assert abs(seconds_diff - sleep_sync_mock.call_args[0][0]) < 1  # pylint: disable=unsubscriptable-object


async def test_webhook_different_callback_id(doof, event_loop, mocker):
    """
    If the callback id doesn't match nothing should be done
    """
    finish_release_mock = mocker.patch(
        'bot.finish_release', autospec=True
    )
    await doof.handle_webhook(
        loop=event_loop,
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


async def test_webhook_finish_release(doof, event_loop, mocker):
    """
    Finish the release
    """
    wait_for_deploy_sync_mock = Mock()

    async def wait_for_deploy_fake(*args, **kwargs):
        """await cannot be used with mock objects"""
        wait_for_deploy_sync_mock(*args, **kwargs)

    pr_body = ReleasePR(
        version='version',
        url='url',
        body='body',
    )
    get_release_pr_mock = mocker.patch('bot.get_release_pr', autospec=True, return_value=pr_body)
    finish_release_mock = mocker.patch('bot.finish_release', autospec=True)
    mocker.patch('bot.wait_for_deploy', wait_for_deploy_fake)

    await doof.handle_webhook(
        loop=event_loop,
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

    repo_url = WEB_TEST_REPO_INFO.repo_url
    hash_url = WEB_TEST_REPO_INFO.prod_hash_url
    org, repo = get_org_and_repo(repo_url)
    wait_for_deploy_sync_mock.assert_any_call(
        github_access_token=doof.github_access_token,
        hash_url=hash_url,
        repo_url=repo_url,
        watch_branch='release',
    )
    get_release_pr_mock.assert_any_call(
        github_access_token=doof.github_access_token,
        org=org,
        repo=repo,
    )
    finish_release_mock.assert_any_call(
        github_access_token=doof.github_access_token,
        repo_url=repo_url,
        version=pr_body.version,
        timezone=doof.timezone
    )
    assert doof.said("Merging...")
    assert not doof.said("Error")


async def test_webhook_finish_release_fail(doof, event_loop, mocker):
    """
    If finishing the release fails we should update the button to show the error
    """
    get_release_pr_mock = mocker.patch('bot.get_release_pr', autospec=True)
    finish_release_mock = mocker.patch('bot.finish_release', autospec=True, side_effect=KeyError)

    with pytest.raises(KeyError):
        await doof.handle_webhook(
            loop=event_loop,
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


async def test_uptime(doof, event_loop, mocker, test_repo):
    """Uptime should show how much time the bot has been awake"""
    now = datetime(2015, 1, 1, 3, 4, 5, tzinfo=pytz.utc)
    doof.doof_boot = now
    later = now + timedelta(seconds=140)
    mocker.patch('bot.now_in_utc', autospec=True, return_value=later)
    await doof.run_command(
        manager='mitodl_user',
        channel_id=test_repo.channel_id,
        words=['uptime'],
        loop=event_loop,
    )
    assert doof.said("Awake for 2 minutes.")


async def test_reset(doof, event_loop, test_repo):
    """Reset should cause a reset"""
    with pytest.raises(ResetException):
        await doof.run_command(
            manager='mitodl_user',
            channel_id=test_repo.channel_id,
            words=['reset'],
            loop=event_loop
        )


@pytest.mark.parametrize("command,project_type", [
    ['finish release', LIBRARY_TYPE],
    ['wait for checkboxes', LIBRARY_TYPE],
    ['upload to pypi 1.2.3', WEB_APPLICATION_TYPE],
    ['upload to pypitest 1.2.3', WEB_APPLICATION_TYPE],
])  # pylint: disable=too-many-arguments
async def test_invalid_project_type(doof, test_repo, library_test_repo, event_loop, command, project_type):
    """
    Compare incompatible commands with project types
    """
    repo = test_repo if project_type == WEB_APPLICATION_TYPE else library_test_repo
    other_type = LIBRARY_TYPE if project_type == WEB_APPLICATION_TYPE else WEB_APPLICATION_TYPE

    await doof.run_command(
        manager='mitodl_user',
        channel_id=repo.channel_id,
        words=command.split(),
        loop=event_loop,
    )

    assert doof.said(f'That command is only for {other_type} projects but this is a {project_type} project.')


@pytest.mark.parametrize('command', [
    'release 1.2.3',
    'start release 1.2.3',
    'finish release',
    'wait for checkboxes',
    'upload to pypi 1.2.3',
    'upload to pypitest 1.2.3',
    'release notes',
])
async def test_command_without_repo(doof, event_loop, command):
    """
    Test that commands won't work on channels without a repo
    """
    await doof.run_command(
        manager='mitodl_user',
        channel_id='not_a_repo_channel',
        words=command.split(),
        loop=event_loop,
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


async def test_help(doof, event_loop):
    """
    Test that doof will show help text
    """
    await doof.run_command(
        manager='mitodl_user',
        channel_id='not_a_repo_channel',
        words=["help"],
        loop=event_loop,
    )

    assert doof.said("*help*: Show available commands")


async def test_wait_for_checkboxes(mocker, doof, test_repo):
    """wait_for_checkboxes should poll github, parse checkboxes and see if all are checked"""
    org, repo = get_org_and_repo(test_repo.repo_url)

    pr = ReleasePR('version', f'https://github.com/{org}/{repo}/pulls/123456', 'body')
    get_release_pr_mock = mocker.patch('bot.get_release_pr', autospec=True, return_value=pr)
    get_unchecked_patch = mocker.patch('bot.get_unchecked_authors', autospec=True, side_effect=[
        {'author1', 'author2', 'author3'},
        {'author2'},
        set(),
    ])
    sleep_sync_mock = mocker.Mock()

    async def sleep_fake(*args, **kwargs):
        """await cannot be used with mock objects"""
        sleep_sync_mock(*args, **kwargs)

    mocker.patch('asyncio.sleep', sleep_fake)

    me = 'mitodl_user'
    await doof.wait_for_checkboxes(
        manager=me,
        repo_info=test_repo,
    )
    get_unchecked_patch.assert_any_call(
        github_access_token=GITHUB_ACCESS,
        org=org,
        repo=repo,
    )
    assert get_unchecked_patch.call_count == 3
    assert sleep_sync_mock.call_count == 2
    get_release_pr_mock.assert_called_once_with(github_access_token=GITHUB_ACCESS, org=org, repo=repo)
    assert doof.said(
        "Release {version} is ready for the Merginator {name}".format(
            version=pr.version,
            name=format_user_id(me),
        )
    )
    assert doof.said(
        "Thanks for checking off your boxes author1, author3!"
    )
    assert doof.said(
        "Thanks for checking off your boxes author2!"
    )
