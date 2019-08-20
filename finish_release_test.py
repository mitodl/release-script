"""Tests for finish_release.py"""
from datetime import datetime
import re
from contextlib import asynccontextmanager

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


pytestmark = pytest.mark.asyncio


# pylint: disable=unused-argument, redefined-outer-name
async def test_check_release_tag(test_repo):
    """check_release_tag should error if the most recent release commit doesn't match the version given"""
    await check_call(["git", "checkout", "-b", "release-candidate"])

    make_empty_commit("initial", "initial commit")
    make_empty_commit("User 1", "  Release 0.0.1  ")
    with pytest.raises(VersionMismatchException) as exception:
        await check_release_tag("0.0.2")
    assert exception.value.args[0] == "Commit name Release 0.0.1 does not match tag number 0.0.2"

    # No exception here
    await check_release_tag("0.0.1")


async def test_merge_release_candidate(mocker):
    """merge_release should merge the release candidate into release and push it"""
    patched_check_call = mocker.async_patch('finish_release.check_call')
    await merge_release_candidate()
    patched_check_call.assert_any_call(['git', 'checkout', 'release'])
    patched_check_call.assert_any_call(['git', 'merge', 'release-candidate', '--no-edit'])
    patched_check_call.assert_any_call(['git', 'push'])


async def test_merge_release(mocker):
    """merge_release should merge the release and push it to origin"""
    patched_check_call = mocker.async_patch('finish_release.check_call')
    await merge_release()
    patched_check_call.assert_any_call(['git', 'checkout', '-q', 'master'])
    patched_check_call.assert_any_call(['git', 'pull'])
    patched_check_call.assert_any_call(['git', 'merge', 'release', '--no-edit'])
    patched_check_call.assert_any_call(['git', 'push'])


async def test_tag_release(mocker):
    """tag_release should tag the release"""
    version = 'version'
    patched_check_call = mocker.async_patch('finish_release.check_call')
    await tag_release(version)
    patched_check_call.assert_any_call(
        ['git', 'tag', '-a', '-m', "Release {}".format(version), "v{}".format(version)]
    )
    patched_check_call.assert_any_call(['git', 'push', '--follow-tags'])


async def test_finish_release(mocker, timezone):
    """finish_release should tag, merge and push the release"""
    token = 'token'
    version = 'version'
    repo_url = 'repo_url'

    @asynccontextmanager
    async def fake_init(*args, **kwargs):  # pylint: disable=unused-argument
        """Fake empty contextmanager"""
        yield

    validate_dependencies_mock = mocker.async_patch('finish_release.validate_dependencies')
    init_working_dir_mock = mocker.patch('finish_release.init_working_dir', side_effect=fake_init)
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
    check_release_mock.assert_called_once_with(version)
    merge_release_candidate_mock.assert_called_once_with()
    tag_release_mock.assert_called_once_with(version)
    merge_release_mock.assert_called_once_with()
    set_version_date_mock.assert_called_once_with(version, timezone)


async def test_set_release_date(test_repo, timezone, mocker):
    """set_release_date should update release notes with dates"""
    mocker.async_patch('finish_release.check_call')
    mocker.async_patch('finish_release.check_output', return_value=b"2018-04-27 12:00:00 +0000\n")
    make_empty_commit("initial", "initial commit")
    await check_call(["git", "tag", "v0.1.0"])
    make_empty_commit("User 1", "Commit #1")
    await create_release_notes("0.1.0", with_checkboxes=False)
    make_empty_commit("User 2", "Commit #2")
    await check_call(["git", "tag", "v0.2.0"])
    await create_release_notes("0.2.0", with_checkboxes=False)
    await set_release_date("0.2.0", timezone)
    with open('RELEASE.rst', 'r') as release_file:
        content = release_file.read()
    assert re.search(r"Version 0.1.0 \(Released April 27, 2018\)", content) is not None
    today = datetime.now().strftime("%B %d, %Y")
    assert f"Version 0.2.0 (Released {today})" in content


async def test_set_release_date_no_file(test_repo, timezone, mocker):
    """ set_release_date should exit immediately if no release file exists """
    mock_check = mocker.patch('finish_release.check_call', autospec=True)
    mock_output = mocker.patch('finish_release.check_output', autospec=True)
    mocker.patch('finish_release.os.path.isfile', return_value=False)
    make_empty_commit("initial", "initial commit")
    await set_release_date("0.1.0", timezone)
    mock_check.assert_not_called()
    mock_output.assert_not_called()
