"""Tests for wait_for_deploy"""
import pytest

from test_util import async_context_manager_yielder
from wait_for_deploy import wait_for_deploy


pytestmark = pytest.mark.asyncio


async def test_wait_for_deploy(mocker, test_repo_directory):
    """wait_for_deploy should poll deployed web applications"""
    matched_hash = "match"
    mismatch_hash = "mismatch"
    fetch_release_patch = mocker.async_patch("wait_for_deploy.fetch_release_hash")
    fetch_release_patch.side_effect = [
        mismatch_hash,
        mismatch_hash,
        matched_hash,
    ]
    check_output_patch = mocker.async_patch(
        "wait_for_deploy.check_output",
    )
    check_output_patch.return_value = f" {matched_hash} ".encode()

    init_working_dir_mock = mocker.patch(
        "wait_for_deploy.init_working_dir",
        side_effect=async_context_manager_yielder(test_repo_directory),
    )
    mocker.async_patch("asyncio.sleep")

    repo_url = "repo_url"
    token = "token"
    hash_url = "hash"
    watch_branch = "watch"
    await wait_for_deploy(
        github_access_token=token,
        repo_url=repo_url,
        hash_url=hash_url,
        watch_branch=watch_branch,
    )

    check_output_patch.assert_called_once_with(
        ["git", "rev-parse", f"origin/{watch_branch}"], cwd=test_repo_directory
    )
    fetch_release_patch.assert_any_call(hash_url)
    assert fetch_release_patch.call_count == 3
    init_working_dir_mock.assert_called_once_with(token, repo_url)
