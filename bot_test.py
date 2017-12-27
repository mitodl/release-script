"""Tests for Doof"""
from datetime import datetime, timedelta
import json
from unittest.mock import Mock

import pytest
import pytz

from bot import Bot
from exception import ReleaseException
from github import get_org_and_repo
from lib import (
    format_user_id,
    ReleasePR,
)
from repo_info import RepoInfo


pytestmark = pytest.mark.asyncio


GITHUB_ACCESS = 'github'
SLACK_ACCESS = 'slack'


# pylint: disable=redefined-outer-name
def mock_socket():
    """A fake socket for recording messages in a Mock"""
    send_sync = Mock()

    async def send(message):
        """Helper function to convert the async function to a regular one"""
        # JSON parsing to make it easier to match
        message_dict = json.loads(message)
        send_sync(message_dict)

    def said(channel_id, text):
        """Has Doof said this thing?"""
        for call in send_sync.mock_calls:
            message = call[1][0]
            print("message '{}'".format(message))
            if message['type'] != 'message':
                continue
            if text in message['text'] and channel_id == message['channel']:
                return True
        return False

    return Mock(
        send=send,
        send_sync=send_sync,
        said=said,
    )


class DoofSpoof(Bot):
    """Testing bot"""
    def __init__(self, loop):
        super().__init__(
            websocket=mock_socket(),
            slack_access_token=SLACK_ACCESS,
            github_access_token=GITHUB_ACCESS,
            timezone=pytz.timezone("America/New_York"),
            loop=loop,
        )

        self.slack_users = []

    def lookup_users(self):
        """Users in the channel"""
        return self.slack_users


@pytest.fixture
def doof(event_loop):
    """Create a Doof"""
    yield DoofSpoof(event_loop)


@pytest.fixture
def repo_info():
    """Our fake repository info"""
    yield RepoInfo(
        name='doof_repo',
        repo_url='http://github.com/mitodl/doof.git',
        prod_hash_url='http://doof.example.com/hash.txt',
        rc_hash_url='http://doof-rc.example.com/hash.txt',
        channel_id='doof',
    )


async def test_release_notes(doof, repo_info, event_loop, mocker):
    """Doof should respond to 'hi'"""
    old_version = "0.1.2"
    update_version_mock = mocker.patch('bot.update_version', autospec=True, return_value=old_version)
    notes = "some notes"
    create_release_notes_mock = mocker.patch('bot.create_release_notes', autospec=True, return_value=notes)

    await doof.run_command('mitodl_user', repo_info.channel_id, repo_info, ['release', 'notes'], event_loop)

    update_version_mock.assert_called_once_with("9.9.9")
    create_release_notes_mock.assert_called_once_with(old_version, with_checkboxes=False)

    assert doof.websocket.said(repo_info.channel_id, "Release notes since {old_version}...\n\n{notes}".format(
        old_version=old_version,
        notes=notes,
    ))


async def test_version(doof, repo_info, event_loop, mocker):
    """
    Doof should tell you what version the latest release was
    """
    a_hash = 'hash'
    version = '1.2.3'
    fetch_release_hash_mock = mocker.patch('bot.fetch_release_hash', autospec=True, return_value=a_hash)
    get_version_tag_mock = mocker.patch('bot.get_version_tag', autospec=True, return_value="v{}".format(version))
    await doof.run_command('mitodl_user', repo_info.channel_id, repo_info, ['version'], event_loop)
    assert doof.websocket.said(
        repo_info.channel_id, "Wait a minute! My evil scheme is at version {}!".format(version)
    )

    fetch_release_hash_mock.assert_called_once_with(repo_info.prod_hash_url)
    get_version_tag_mock.assert_called_once_with(GITHUB_ACCESS, repo_info.repo_url, a_hash)


# pylint: disable=too-many-locals
@pytest.mark.parametrize("command", ['release', 'start release'])
async def test_release(doof, repo_info, event_loop, mocker, command):
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

    wait_for_deploy_sync_mock = Mock()

    async def wait_for_deploy_fake(*args, **kwargs):
        """await cannot be used with mock objects"""
        wait_for_deploy_sync_mock(*args, **kwargs)

    mocker.patch('bot.wait_for_deploy', wait_for_deploy_fake)
    authors = ['author1', 'author2']
    mocker.patch('bot.get_unchecked_authors', return_value=authors)

    wait_for_checkboxes_sync_mock = Mock()
    async def wait_for_checkboxes_fake(*args, **kwargs):
        """await cannot be used with mock objects"""
        wait_for_checkboxes_sync_mock(*args, **kwargs)
    mocker.patch('bot.wait_for_checkboxes', wait_for_checkboxes_fake)

    command_words = command.split() + [version]
    me = 'mitodl_user'
    await doof.run_command(me, repo_info.channel_id, repo_info, command_words, event_loop)

    # run out the clock
    for key, task in doof.tasks.items():
        await task

    org, repo = get_org_and_repo(repo_info.repo_url)
    get_release_pr_mock.assert_any_call(GITHUB_ACCESS, org, repo)
    release_mock.assert_called_once_with(
        github_access_token=GITHUB_ACCESS,
        repo_url=repo_info.repo_url,
        new_version=pr.version,
    )
    wait_for_deploy_sync_mock.assert_called_once_with(
        github_access_token=GITHUB_ACCESS,
        repo_url=repo_info.repo_url,
        hash_url=repo_info.rc_hash_url,
        watch_branch='release-candidate',
    )
    assert doof.websocket.said(repo_info.channel_id, "Now deploying to RC...")
    assert doof.websocket.said(
        repo_info.channel_id, "These people have commits in this release: {}".format(', '.join(authors))
    )
    wait_for_checkboxes_sync_mock.assert_called_once_with(GITHUB_ACCESS, org, repo)
    assert doof.websocket.said(
        repo_info.channel_id, "Release {version} is ready for the Merginator {name}".format(
            version=pr.version,
            name=format_user_id(me),
        )
    )


@pytest.mark.parametrize("command", ['release', 'start release'])
async def test_release_in_progress(doof, repo_info, event_loop, mocker, command):
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
        await doof.run_command('mitodl_user', repo_info.channel_id, repo_info, command_words, event_loop)
    assert ex.value.args[0] == "A release is already in progress: {}".format(url)


@pytest.mark.parametrize("command", ['release', 'start release'])
async def test_release_bad_version(doof, repo_info, event_loop, command):
    """
    If the version doesn't parse correctly doof should fail
    """
    command_words = command.split() + ['a.b.c']
    await doof.run_command('mitodl_user', repo_info.channel_id, repo_info, command_words, event_loop)
    assert doof.websocket.said(
        repo_info.channel_id,
        'having trouble figuring out what that means',
    )


@pytest.mark.parametrize("command", ['release', 'start release'])
async def test_release_no_args(doof, repo_info, event_loop, command):
    """
    If no version is given doof should complain
    """
    command_words = command.split()
    await doof.run_command('mitodl_user', repo_info.channel_id, repo_info, command_words, event_loop)
    assert doof.websocket.said(
        repo_info.channel_id,
        "Careful, careful. I expected 1 words but you said 0.",
    )


async def test_finish_release(doof, repo_info, event_loop, mocker):
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

    wait_for_deploy_sync_mock = Mock()

    async def wait_for_deploy_fake(*args, **kwargs):
        """await cannot be used with mock objects"""
        wait_for_deploy_sync_mock(*args, **kwargs)

    mocker.patch('bot.wait_for_deploy', wait_for_deploy_fake)

    await doof.run_command('mitodl_user', repo_info.channel_id, repo_info, ['finish', 'release'], event_loop)

    org, repo = get_org_and_repo(repo_info.repo_url)
    get_release_pr_mock.assert_called_once_with(GITHUB_ACCESS, org, repo)
    finish_release_mock.assert_called_once_with(
        github_access_token=GITHUB_ACCESS,
        repo_url=repo_info.repo_url,
        version=version,
    )
    assert doof.websocket.said(repo_info.channel_id, 'deploying to production...')
    wait_for_deploy_sync_mock.assert_called_once_with(
        github_access_token=GITHUB_ACCESS,
        repo_url=repo_info.repo_url,
        hash_url=repo_info.prod_hash_url,
        watch_branch='release',
    )
    assert doof.websocket.said(repo_info.channel_id, 'has been released to production')


async def test_finish_release_no_release(doof, repo_info, event_loop, mocker):
    """
    If there's no release to finish doof should complain
    """
    get_release_pr_mock = mocker.patch('bot.get_release_pr', autospec=True, return_value=None)
    with pytest.raises(ReleaseException) as ex:
        await doof.run_command('mitodl_user', repo_info.channel_id, repo_info, ['finish', 'release'], event_loop)
    assert 'No release currently in progress' in ex.value.args[0]
    org, repo = get_org_and_repo(repo_info.repo_url)
    get_release_pr_mock.assert_called_once_with(GITHUB_ACCESS, org, repo)


async def test_delay_message(doof, repo_info, mocker):
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

    mocker.patch('bot.get_unchecked_authors', return_value=['author1'])

    await doof.delay_message(repo_info)
    assert doof.websocket.said(
        repo_info.channel_id,
        'The following authors have not yet checked off their boxes for doof_repo: author1',
    )
    assert next_workday_mock.call_count == 1
    assert abs(next_workday_mock.call_args[0][0] - now).total_seconds() < 1
    assert next_workday_mock.call_args[0][0].tzinfo.zone == doof.timezone.zone
    assert sleep_sync_mock.call_count == 1
    assert abs(seconds_diff - sleep_sync_mock.call_args[0][0]) < 1  # pylint: disable=unsubscriptable-object
