"""Tests for finish_release.py"""
import re
from contextlib import contextmanager
from subprocess import check_call

import pytest

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


# pylint: disable=unused-argument, redefined-outer-name
def test_check_release_tag(test_repo):
    """check_release_tag should error if the most recent release commit doesn't match the version given"""
    check_call(["git", "checkout", "-b", "release-candidate"])

    make_empty_commit("initial", "initial commit")
    make_empty_commit("User 1", "  Release 0.0.1  ")
    with pytest.raises(VersionMismatchException) as exception:
        check_release_tag("0.0.2")
    assert exception.value.args[0] == "Commit name Release 0.0.1 does not match tag number 0.0.2"

    # No exception here
    check_release_tag("0.0.1")


def test_merge_release_candidate(mocker):
    """merge_release should merge the release candidate into release and push it"""
    patched_check_call = mocker.patch('finish_release.check_call', autospec=True)
    merge_release_candidate()
    patched_check_call.assert_any_call(['git', 'checkout', 'release'])
    patched_check_call.assert_any_call(['git', 'merge', 'release-candidate', '--no-edit'])
    patched_check_call.assert_any_call(['git', 'push'])


def test_merge_release(mocker):
    """merge_release should merge the release and push it to origin"""
    patched_check_call = mocker.patch('finish_release.check_call', autospec=True)
    merge_release()
    patched_check_call.assert_any_call(['git', 'checkout', '-q', 'master'])
    patched_check_call.assert_any_call(['git', 'pull'])
    patched_check_call.assert_any_call(['git', 'merge', 'release', '--no-edit'])
    patched_check_call.assert_any_call(['git', 'push'])


def test_tag_release(mocker):
    """tag_release should tag the release"""
    version = 'version'
    patched_check_call = mocker.patch('finish_release.check_call', autospec=True)
    tag_release(version)
    patched_check_call.assert_any_call(
        ['git', 'tag', '-a', '-m', "Release {}".format(version), "v{}".format(version)]
    )
    patched_check_call.assert_any_call(['git', 'push', '--follow-tags'])


def test_finish_release(mocker, timezone):
    """finish_release should tag, merge and push the release"""
    token = 'token'
    version = 'version'
    repo_url = 'repo_url'

    @contextmanager
    def fake_init(*args, **kwargs):  # pylint: disable=unused-argument
        """Fake empty contextmanager"""
        yield

    init_working_dir_mock = mocker.patch('finish_release.init_working_dir', side_effect=fake_init)
    check_release_mock = mocker.patch('finish_release.check_release_tag', autospec=True)
    merge_release_candidate_mock = mocker.patch('finish_release.merge_release_candidate', autospec=True)
    tag_release_mock = mocker.patch('finish_release.tag_release', autospec=True)
    merge_release_mock = mocker.patch('finish_release.merge_release', autospec=True)
    set_version_date_mock = mocker.patch('finish_release.set_release_date', autospec=True)

    finish_release(
        github_access_token=token,
        repo_url=repo_url,
        version=version,
        timezone=timezone
    )
    init_working_dir_mock.assert_called_once_with(token, repo_url)
    check_release_mock.assert_called_once_with(version)
    merge_release_candidate_mock.assert_called_once_with()
    tag_release_mock.assert_called_once_with(version)
    merge_release_mock.assert_called_once_with()
    set_version_date_mock.assert_called_once_with(version, timezone)


def test_set_release_date(test_repo, timezone, mocker):
    """set_release_date should update release notes with dates"""
    mocker.patch('finish_release.check_call', autospec=True)
    mocker.patch('finish_release.check_output', autospec=True, return_value=b"2018-07-23 12:00:00 +0000\n")
    make_empty_commit("initial", "initial commit")
    check_call(["git", "tag", "v0.1.0"])
    make_empty_commit("User 1", "Commit #1")
    create_release_notes("0.1.0", with_checkboxes=False)
    make_empty_commit("User 2", "Commit #2")
    check_call(["git", "tag", "v0.2.0"])
    create_release_notes("0.2.0", with_checkboxes=False)
    set_release_date("0.2.0", timezone)
    with open('RELEASE.rst', 'r') as release_file:
        content = release_file.read()
    assert re.search(r"Version 0.1.0 \(Released July 23, 2018\)", content) is not None
    assert re.search(r"Version 0.2.0 \(Released July 23, 2018\)", content) is not None


def test_set_release_date_no_file(test_repo, timezone, mocker):
    """ set_release_date should exit immediately if no release file exists """
    mock_check = mocker.patch('finish_release.check_call', autospec=True)
    mock_output = mocker.patch('finish_release.check_output', autospec=True)
    mocker.patch('finish_release.os.path.isfile', return_value=False)
    make_empty_commit("initial", "initial commit")
    set_release_date("0.1.0", timezone)
    mock_check.assert_not_called()
    mock_output.assert_not_called()
