"""Tests for wait_for_checked"""
import pytest

from wait_for_checked import wait_for_checkboxes


pytestmark = pytest.mark.asyncio


async def test_wait_for_checkboxes(mocker):
    """wait_for_checkboxes should poll github, parse checkboxes and see if all are checked"""
    get_unchecked_patch = mocker.patch('wait_for_checked.get_unchecked_authors', autospec=True, side_effect=[
        ['author1', 'author2'],
        ['author2'],
        [],
    ])
    sleep_sync_mock = mocker.Mock()

    async def sleep_fake(*args, **kwargs):
        """await cannot be used with mock objects"""
        sleep_sync_mock(*args, **kwargs)

    mocker.patch('asyncio.sleep', sleep_fake)

    token = 'token'
    org = 'org'
    repo = 'repo'
    await wait_for_checkboxes(
        github_access_token=token,
        org=org,
        repo=repo,
    )
    get_unchecked_patch.assert_any_call(
        github_access_token=token,
        org=org,
        repo=repo,
    )
    assert get_unchecked_patch.call_count == 3
    assert sleep_sync_mock.call_count == 2
