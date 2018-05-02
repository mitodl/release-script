"""Tests for finish_release.py"""
from subprocess import check_call

import pytest

from release import VersionMismatchException
from release_test import make_empty_commit
from finish_release import (
    check_release_tag,
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
