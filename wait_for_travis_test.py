"""Tests for wait_for_travis"""
import pytest

from constants import (
    NO_PR_BUILD,
    TRAVIS_FAILURE,
    TRAVIS_PENDING,
    TRAVIS_SUCCESS,
)
from wait_for_travis import wait_for_travis


pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize("statuses,result", [
    [[NO_PR_BUILD, NO_PR_BUILD], NO_PR_BUILD],
    [[NO_PR_BUILD, TRAVIS_SUCCESS], TRAVIS_SUCCESS],
    [[NO_PR_BUILD, TRAVIS_FAILURE], TRAVIS_FAILURE],
    [[TRAVIS_PENDING, TRAVIS_SUCCESS], TRAVIS_SUCCESS],
    [[TRAVIS_PENDING, TRAVIS_FAILURE], TRAVIS_FAILURE],
    [[TRAVIS_SUCCESS], TRAVIS_SUCCESS],
    [[TRAVIS_FAILURE], TRAVIS_FAILURE],
])
async def test_wait_for_travis(mocker, statuses, result):
    """wait_for_travis should check the github status API every 30 seconds"""
    get_status_mock = mocker.patch('wait_for_travis.get_status_of_pr', autospec=True, side_effect=statuses)
    sleep_sync_mock = mocker.Mock()

    async def sleep_fake(*args, **kwargs):
        """await cannot be used with mock objects"""
        sleep_sync_mock(*args, **kwargs)

    mocker.patch('asyncio.sleep', sleep_fake)

    token = 'token'
    org = 'org'
    repo = 'repo'
    branch = 'branch'
    assert await wait_for_travis(
        github_access_token=token,
        org=org,
        repo=repo,
        branch=branch,
    ) == result

    get_status_mock.assert_any_call(
        github_access_token=token,
        org=org,
        repo=repo,
        branch=branch,
    )
    assert get_status_mock.call_count == len(statuses)
    assert sleep_sync_mock.call_count == len(statuses) - 1
    if len(statuses) - 1 > 0:
        sleep_sync_mock.assert_any_call(30)
