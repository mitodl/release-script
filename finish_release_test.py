"""Tests for finish_release.py"""
from datetime import datetime
import re
import os
from pathlib import Path

import pytest

from constants import GO, NPM, YARN_PATH
from exception import VersionMismatchException
from lib import (
    check_call,
    ReleasePR,
)
from release import create_release_notes
from release_test import make_empty_commit
from repo_info import UpdateOtherRepo
from finish_release import (
    check_release_tag,
    finish_release,
    merge_release,
    merge_release_candidate,
    tag_release,
    set_release_date,
    update_go_mod,
    update_other_repo_and_commit,
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
    branch = "a_branch"
    default_branch_mock = mocker.async_patch('finish_release.get_default_branch', return_value=branch)
    root = "/a/bad/directory/path"
    await merge_release(root=root)
    patched_check_call.assert_any_call(['git', 'checkout', '-q', branch], cwd=root)
    patched_check_call.assert_any_call(['git', 'pull'], cwd=root)
    patched_check_call.assert_any_call(['git', 'merge', 'release', '--no-edit'], cwd=root)
    patched_check_call.assert_any_call(['git', 'push'], cwd=root)
    default_branch_mock.assert_called_once_with(root)


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


# pylint: disable=too-many-locals
async def test_finish_release(mocker, timezone, test_repo_directory, test_repo):
    """finish_release should tag, merge and push the release"""
    token = 'token'
    version = 'version'

    validate_dependencies_mock = mocker.async_patch('finish_release.validate_dependencies')
    init_working_dir_mock = mocker.patch(
        'finish_release.init_working_dir', side_effect=async_context_manager_yielder(test_repo_directory)
    )
    check_release_mock = mocker.async_patch('finish_release.check_release_tag')
    merge_release_candidate_mock = mocker.async_patch('finish_release.merge_release_candidate')
    tag_release_mock = mocker.async_patch('finish_release.tag_release')
    merge_release_mock = mocker.async_patch('finish_release.merge_release')
    set_version_date_mock = mocker.async_patch('finish_release.set_release_date')
    release_pr = ReleasePR('version', 'https://github.com/org/repo/pull/123456', 'body')
    mocker.async_patch('finish_release.get_release_pr', return_value=release_pr)

    await finish_release(
        github_access_token=token,
        repo_info=test_repo,
        version=version,
        timezone=timezone,
    )
    validate_dependencies_mock.assert_called_once_with()
    init_working_dir_mock.assert_called_once_with(token, test_repo.repo_url)
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


@pytest.mark.parametrize("has_require", [True, False])
def test_update_go_mod(test_repo_directory, test_repo, has_require):
    """update_go_mod should update and replace a go.mod file"""
    go_mod_path = Path(test_repo_directory) / "go.mod"
    contents = """module github.com/mitodl/ocw-www

go 1.16

"""
    require_line = "require github.com/mitodl/ocw-hugo-themes/base-theme v0.0.0-20210429192641-b4d04aa624a0 // indirect"

    if has_require:
        contents += require_line

    with open(go_mod_path, "w") as file:
        file.write(contents)

    version = "4.5.6"
    changed = update_go_mod(
        path=go_mod_path,
        version=version,
        repo_url=test_repo.repo_url,
    )
    assert changed is has_require
    with open(go_mod_path) as file:
        new_contents = file.read()

    if has_require:
        assert new_contents == """module github.com/mitodl/ocw-www

go 1.16

require github.com/mitodl/doof v4.5.6 // indirect
"""
    else:
        assert new_contents == contents


@pytest.mark.parametrize("changed", [True, False])
@pytest.mark.parametrize("packaging_tool", [NPM, GO])
async def test_update_other_repo_and_commit(
    mocker, library_test_repo, npm_library_test_repo, changed, packaging_tool
):
    """update_other_repo_and_commit should update a dependency and push the updated code"""
    version = "12.3.45"
    token = "token"
    call_mock = mocker.async_patch("finish_release.call", return_value=1 if changed else 0)
    check_call_mock = mocker.async_patch("finish_release.check_call")
    update_go_mod_mock = mocker.patch("finish_release.update_go_mod")
    other_repo_path = "/tmp/abcdef"
    init_working_dir_mock = mocker.patch(
        'finish_release.init_working_dir', side_effect=async_context_manager_yielder(other_repo_path)
    )

    await update_other_repo_and_commit(
        github_access_token=token,
        new_version=version,
        repo_info=library_test_repo,
        update_other_repo=UpdateOtherRepo(
            name=npm_library_test_repo.name,
            packaging_tool=packaging_tool,
            repo_info=npm_library_test_repo
        ),
        pull_request=ReleasePR('version', 'https://github.com/org/repo/pull/123456', 'body')
    )

    if packaging_tool == NPM:
        check_call_mock.assert_any_call(
            [YARN_PATH, "add", f"{library_test_repo.name}@{version}"],
            cwd=Path(other_repo_path)
        )
    elif packaging_tool == GO:
        update_go_mod_mock.assert_called_once_with(
            path=Path(other_repo_path) / "go.mod",
            version=version,
            repo_url=library_test_repo.repo_url,
        )

    init_working_dir_mock.assert_called_once_with(token, npm_library_test_repo.repo_url)
    call_mock.assert_called_once_with(["git", "diff", "--exit-code"], cwd=Path(other_repo_path))
    if changed:
        check_call_mock.assert_any_call(["git", "add", "."], cwd=Path(other_repo_path))
        message = f"Update {library_test_repo.name} to {version} (org/repo#123456)"
        check_call_mock.assert_any_call(["git", "commit", "-m", message], cwd=Path(other_repo_path))
        check_call_mock.assert_any_call(["git", "push"], cwd=Path(other_repo_path))
