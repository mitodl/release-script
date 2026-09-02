"""Tests for finish_release.py"""

import pytest

from exception import ReleaseException, VersionMismatchException
from lib import check_call, get_commit_hash
from release_test import make_empty_commit
from finish_release import (
    check_release_tag,
    finish_release,
    merge_release,
    merge_release_candidate,
    tag_release,
    verify_release_tag,
)
from test_util import async_context_manager_yielder


pytestmark = pytest.mark.asyncio


async def test_check_release_tag(test_repo_directory):
    """check_release_tag should error if the most recent release commit doesn't match the version given"""
    await check_call(
        ["git", "checkout", "-b", "release-candidate"], cwd=test_repo_directory
    )

    make_empty_commit("initial", "initial commit", cwd=test_repo_directory)
    make_empty_commit("User 1", "  Release 0.0.1  ", cwd=test_repo_directory)
    with pytest.raises(VersionMismatchException) as exception:
        await check_release_tag("0.0.2", root=test_repo_directory)
    assert (
        exception.value.args[0]
        == "Commit name Release 0.0.1 does not match tag number 0.0.2"
    )

    # No exception here
    await check_release_tag("0.0.1", root=test_repo_directory)


async def test_merge_release_candidate(mocker):
    """merge_release should merge the release candidate into release and push it"""
    patched_check_call = mocker.async_patch("finish_release.check_call")
    root = "/some/other/path"
    await merge_release_candidate(root=root)
    patched_check_call.assert_any_call(["git", "checkout", "release"], cwd=root)
    patched_check_call.assert_any_call(
        ["git", "merge", "release-candidate", "--no-edit"], cwd=root
    )
    patched_check_call.assert_any_call(["git", "push"], cwd=root)


async def test_merge_release(mocker):
    """merge_release should merge the release and push it to origin"""
    patched_check_call = mocker.async_patch("finish_release.check_call")
    branch = "a_branch"
    default_branch_mock = mocker.async_patch(
        "finish_release.get_default_branch", return_value=branch
    )
    root = "/a/bad/directory/path"
    await merge_release(root=root)
    patched_check_call.assert_any_call(["git", "checkout", "-q", branch], cwd=root)
    patched_check_call.assert_any_call(["git", "pull"], cwd=root)
    patched_check_call.assert_any_call(
        ["git", "merge", "release", "--no-edit"], cwd=root
    )
    patched_check_call.assert_any_call(["git", "push"], cwd=root)
    default_branch_mock.assert_called_once_with(root)


@pytest.mark.parametrize("already_tagged", [True, False])
async def test_tag_release(mocker, test_repo_directory, already_tagged):
    """
    tag_release should tag the release, unless the release candidate was already tagged
    when it was cut, and should push either way
    """
    version = "1.2.3"
    await check_call(
        ["git", "checkout", "-q", "-b", "release-candidate"], cwd=test_repo_directory
    )
    make_empty_commit("initial", f"Release {version}", cwd=test_repo_directory)
    if already_tagged:
        await check_call(
            ["git", "tag", "-a", "-m", f"Release {version}", f"v{version}"],
            cwd=test_repo_directory,
        )
    patched_check_call = mocker.async_patch("finish_release.check_call")

    await tag_release(version, root=test_repo_directory)

    tag_call = mocker.call(
        ["git", "tag", "-a", "-m", f"Release {version}", f"v{version}"],
        cwd=test_repo_directory,
    )
    assert (tag_call in patched_check_call.mock_calls) is not already_tagged
    patched_check_call.assert_any_call(
        ["git", "push", "--follow-tags"], cwd=test_repo_directory
    )


async def test_tag_release_wrong_commit(mocker, test_repo_directory):
    """
    tag_release should refuse to finish a release when the existing tag identifies
    unrelated code, since the tag cannot be moved
    """
    version = "1.2.3"
    await check_call(
        ["git", "checkout", "-q", "-b", "release-candidate"], cwd=test_repo_directory
    )
    make_empty_commit("initial", f"Release {version}", cwd=test_repo_directory)
    rc_commit = await get_commit_hash("HEAD", root=test_repo_directory)

    # tag a commit on a divergent branch, so it is neither the release commit nor a
    # descendant of it
    await check_call(
        ["git", "checkout", "-q", "-b", "unrelated", "HEAD~1"], cwd=test_repo_directory
    )
    make_empty_commit("someone", "unrelated work", cwd=test_repo_directory)
    unrelated_commit = await get_commit_hash("HEAD", root=test_repo_directory)
    await check_call(
        ["git", "tag", "-a", "-m", f"Release {version}", f"v{version}"],
        cwd=test_repo_directory,
    )
    patched_check_call = mocker.async_patch("finish_release.check_call")

    with pytest.raises(ReleaseException) as exception:
        await tag_release(version, root=test_repo_directory)

    assert exception.value.args[0] == (
        f"Tag v{version} points at {unrelated_commit}, which does not contain the "
        f"release-candidate commit {rc_commit}. Tags are immutable, so this release "
        f"cannot be finished under this version number."
    )
    patched_check_call.assert_not_called()


async def test_verify_release_tag_allows_descendant(test_repo_directory):
    """
    verify_release_tag should accept a tag on a commit that contains the release, which
    is where a tag created while finishing the release lands
    """
    version = "1.2.3"
    await check_call(
        ["git", "checkout", "-q", "-b", "release-candidate"], cwd=test_repo_directory
    )
    make_empty_commit("initial", f"Release {version}", cwd=test_repo_directory)

    # stand in for the release merge commit, tagged while finishing the release, leaving
    # release-candidate behind at the release commit
    await check_call(
        ["git", "checkout", "-q", "-b", "release"], cwd=test_repo_directory
    )
    make_empty_commit("doof", "Merge release-candidate", cwd=test_repo_directory)
    await check_call(
        ["git", "tag", "-a", "-m", f"Release {version}", f"v{version}"],
        cwd=test_repo_directory,
    )

    # no exception
    await verify_release_tag(version, root=test_repo_directory)


async def test_finish_release(mocker, test_repo_directory, test_repo):
    """finish_release should tag, merge and push the release"""
    token = "token"
    version = "version"

    validate_dependencies_mock = mocker.async_patch(
        "finish_release.validate_dependencies"
    )
    init_working_dir_mock = mocker.patch(
        "finish_release.init_working_dir",
        side_effect=async_context_manager_yielder(test_repo_directory),
    )
    check_release_mock = mocker.async_patch("finish_release.check_release_tag")
    merge_release_candidate_mock = mocker.async_patch(
        "finish_release.merge_release_candidate"
    )
    tag_release_mock = mocker.async_patch("finish_release.tag_release")
    merge_release_mock = mocker.async_patch("finish_release.merge_release")

    await finish_release(
        github_access_token=token,
        repo_info=test_repo,
        version=version,
    )
    validate_dependencies_mock.assert_called_once_with()
    init_working_dir_mock.assert_called_once_with(token, test_repo.repo_url)
    check_release_mock.assert_called_once_with(version, root=test_repo_directory)
    merge_release_candidate_mock.assert_called_once_with(root=test_repo_directory)
    tag_release_mock.assert_called_once_with(version, root=test_repo_directory)
    merge_release_mock.assert_called_once_with(root=test_repo_directory)
