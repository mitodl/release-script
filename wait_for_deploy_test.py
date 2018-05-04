"""Tests for wait_for_deploy"""
from contextlib import contextmanager

import pytest

from wait_for_deploy import wait_for_deploy


pytestmark = pytest.mark.asyncio


async def test_wait_for_deploy(mocker):
    """wait_for_deploy should poll deployed web applications"""
    matched_hash = 'match'
    mismatch_hash = 'mismatch'
    fetch_release_patch = mocker.patch('wait_for_deploy.fetch_release_hash', autospec=True, side_effect=[
        mismatch_hash,
        mismatch_hash,
        matched_hash,
    ])
    check_output_patch = mocker.patch(
        'wait_for_deploy.check_output',
        autospec=True,
        return_value=" {} ".format(matched_hash).encode(),
    )
    validate_patch = mocker.patch('wait_for_deploy.validate_dependencies', autospec=True)

    @contextmanager
    def fake_init(*args, **kwargs):  # pylint: disable=unused-argument
        """Fake empty contextmanager"""
        yield

    init_working_dir_mock = mocker.patch('wait_for_deploy.init_working_dir', side_effect=fake_init)
    sleep_sync_mock = mocker.Mock()

    async def sleep_fake(*args, **kwargs):
        """await cannot be used with mock objects"""
        sleep_sync_mock(*args, **kwargs)

    mocker.patch('asyncio.sleep', sleep_fake)

    repo_url = 'repo_url'
    token = 'token'
    hash_url = 'hash'
    watch_branch = 'watch'
    await wait_for_deploy(
        github_access_token=token,
        repo_url=repo_url,
        hash_url=hash_url,
        watch_branch=watch_branch,
    )

    validate_patch.assert_called_once_with()
    check_output_patch.assert_called_once_with(["git", "rev-parse", "origin/{}".format(watch_branch)])
    fetch_release_patch.assert_any_call(hash_url)
    assert fetch_release_patch.call_count == 3
    init_working_dir_mock.assert_called_once_with(token, repo_url)
