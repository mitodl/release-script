"""Tests for finish_release.py"""
from datetime import datetime
import re
import os

import pytest

from lib import check_call
from release import VersionMismatchException, create_release_notes
from release_test import make_empty_commit
from finish_release import (
    check_release_tag,
    finish_release,
    merge_release,
    merge_release_candidate,
    tag_release,
    set_release_date
)
from test_util import async_context_manager_yielder


pytestmark = pytest.mark.asyncio


# pylint: disable=unused-argument, redefined-outer-name
async def test_check_release_tag(test_repo_directory):
    """check_release_tag should error if the most recent release commit doesn't match the version given"""
    await check_call(["git", "checkout", "-b", "release-candidate"], cwd=test_repo_directory)

    make_empty_commit("initial", "initial commit", cwd=test_repo_directory)
    make_empty_commit("User 1", "  Release 0.0.1  ", cwd=test_repo_directory)
    with pytest.raises(VersionMismatchException) as exception:
        await check_release_tag("0.0.2", root=test_repo_directory)
    assert exception.value.args[0] == "Commit name Release 0.0.1 does not match tag number 0.0.2"

    # No exception here
    await check_release_tag("0.0.1", root=test_repo_directory)


async def test_merge_release_candidate(mocker):
    """merge_release should merge the release candidate into release and push it"""
    patched_check_call = mocker.async_patch('finish_release.check_call')
    root = "/some/other/path"
    await merge_release_candidate(root=root)
    patched_check_call.assert_any_call(['git', 'checkout', 'release'], cwd=root)
    patched_check_call.assert_any_call(['git', 'merge', 'release-candidate', '--no-edit'], cwd=root)
    patched_check_call.assert_any_call(['git', 'push'], cwd=root)


async def test_merge_release(mocker):
    """merge_release should merge the release and push it to origin"""
    patched_check_call = mocker.async_patch('finish_release.check_call')
    root = "/a/bad/directory/path"
    await merge_release(root=root)
    patched_check_call.assert_any_call(['git', 'checkout', '-q', 'master'], cwd=root)
    patched_check_call.assert_any_call(['git', 'pull'], cwd=root)
    patched_check_call.assert_any_call(['git', 'merge', 'release', '--no-edit'], cwd=root)
    patched_check_call.assert_any_call(['git', 'push'], cwd=root)


async def test_tag_release(mocker, test_repo_directory):
    """tag_release should tag the release"""
    version = 'version'
    patched_check_call = mocker.async_patch('finish_release.check_call')
    await tag_release(version, root=test_repo_directory)
    patched_check_call.assert_any_call(
        ['git', 'tag', '-a', '-m', "Release {}".format(version), "v{}".format(version)],
        cwd=test_repo_directory
    )
    patched_check_call.assert_any_call(['git', 'push', '--follow-tags'], cwd=test_repo_directory)


async def test_finish_release(mocker, timezone, test_repo_directory):
    """finish_release should tag, merge and push the release"""
    token = 'token'
    version = 'version'
    repo_url = 'repo_url'

    validate_dependencies_mock = mocker.async_patch('finish_release.validate_dependencies')
    init_working_dir_mock = mocker.patch(
        'finish_release.init_working_dir', side_effect=async_context_manager_yielder(test_repo_directory)
    )
    check_release_mock = mocker.async_patch('finish_release.check_release_tag')
    merge_release_candidate_mock = mocker.async_patch('finish_release.merge_release_candidate')
    tag_release_mock = mocker.async_patch('finish_release.tag_release')
    merge_release_mock = mocker.async_patch('finish_release.merge_release')
    set_version_date_mock = mocker.async_patch('finish_release.set_release_date')

    await finish_release(
        github_access_token=token,
        repo_url=repo_url,
        version=version,
        timezone=timezone
    )
    validate_dependencies_mock.assert_called_once_with()
    init_working_dir_mock.assert_called_once_with(token, repo_url)
    check_release_mock.assert_called_once_with(version, root=test_repo_directory)
    merge_release_candidate_mock.assert_called_once_with(root=test_repo_directory)
    tag_release_mock.assert_called_once_with(version, root=test_repo_directory)
    merge_release_mock.assert_called_once_with(root=test_repo_directory)
    set_version_date_mock.assert_called_once_with(version, timezone, root=test_repo_directory)


async def test_set_release_date(test_repo_directory, timezone, mocker):
    """set_release_date should update release notes with dates"""
    mocker.async_patch('finish_release.check_call')
    mocker.async_patch('finish_release.check_output', return_value=b"2018-04-27 12:00:00 +0000\n")
    make_empty_commit("initial", "initial commit", cwd=test_repo_directory)
    await check_call(["git", "tag", "v0.1.0"], cwd=test_repo_directory)
    make_empty_commit("User 1", "Commit #1", cwd=test_repo_directory)
    base_branch = "master"
    await create_release_notes("0.1.0", with_checkboxes=False, base_branch=base_branch, root=test_repo_directory)
    make_empty_commit("User 2", "Commit #2", cwd=test_repo_directory)
    await check_call(["git", "tag", "v0.2.0"], cwd=test_repo_directory)
    await create_release_notes("0.2.0", with_checkboxes=False, base_branch=base_branch, root=test_repo_directory)
    await set_release_date("0.2.0", timezone, root=test_repo_directory)
    with open(os.path.join(test_repo_directory, 'RELEASE.rst'), 'r') as release_file:
        content = release_file.read()
    assert re.search(r"Version 0.1.0 \(Released April 27, 2018\)", content) is not None
    today = datetime.now().strftime("%B %d, %Y")
    assert f"Version 0.2.0 (Released {today})" in content


async def test_set_release_date_no_file(test_repo_directory, timezone, mocker):
    """ set_release_date should exit immediately if no release file exists """
    mock_check = mocker.patch('finish_release.check_call', autospec=True)
    mock_output = mocker.patch('finish_release.check_output', autospec=True)
    mocker.patch('finish_release.os.path.isfile', return_value=False)
    make_empty_commit("initial", "initial commit", cwd=test_repo_directory)
    await set_release_date("0.1.0", timezone, root=test_repo_directory)
    mock_check.assert_not_called()
    mock_output.assert_not_called()
