"""Tests for Doof"""
import json
from unittest.mock import Mock

import pytest

from bot import Bot
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
        return send_sync(message_dict)

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


@pytest.fixture
def doof():
    """Create a Doof"""
    yield Bot(mock_socket(), SLACK_ACCESS, GITHUB_ACCESS)


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

    await doof.run_command(repo_info.channel_id, repo_info, ['release', 'notes'], event_loop)

    update_version_mock.assert_called_once_with("9.9.9")
    create_release_notes_mock.assert_called_once_with(old_version, with_checkboxes=False)

    assert doof.websocket.said(repo_info.channel_id, "Release notes since {old_version}...\n\n{notes}".format(
        old_version=old_version,
        notes=notes,
    ))


async def test_version(doof, repo_info, event_loop, mocker):
    """
    Doof should tell you what version
    """
    a_hash = 'hash'
    version = '1.2.3'
    fetch_release_hash_mock = mocker.patch('bot.fetch_release_hash', autospec=True, return_value=a_hash)
    get_version_tag_mock = mocker.patch('bot.get_version_tag', autospec=True, return_value="v{}".format(version))
    await doof.run_command(repo_info.channel_id, repo_info, ['version'], event_loop)
    assert doof.websocket.said(
        repo_info.channel_id, "Wait a minute! My evil scheme is at version {}!".format(version)
    )

    fetch_release_hash_mock.assert_called_once_with(repo_info.prod_hash_url)
    get_version_tag_mock.assert_called_once_with(GITHUB_ACCESS, repo_info.repo_url, a_hash)
