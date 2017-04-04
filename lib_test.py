"""Tests for lib"""
from datetime import datetime
import os
from unittest.mock import (
    Mock,
    patch,
)

import pytest

from lib import (
    get_org_and_repo,
    get_release_pr,
    get_unchecked_authors,
    match_user,
    next_workday_at_10,
    parse_checkmarks,
    reformatted_full_name,
)


FAKE_RELEASE_PR_BODY = """

## Alice Pote
  - [x] Implemented AutomaticEmail API ([5de04973](../commit/5de049732f769ec8a2a24068514603f353e13ed4))
  - [ ] Unmarked some files as executable ([c665a2c7](../commit/c665a2c79eaf5e2d54b18f5a880709f5065ed517))

## Nathan Levesque
  - [x] Fixed seed data for naive timestamps (#2712) ([50d19c4a](../commit/50d19c4adf22c5ddc8b8299f4b4579c2b1e35b7f))
  - [garbage] xyz
    """

OTHER_PR = {
    "url": "https://api.github.com/repos/mitodl/micromasters/pulls/2985",
    "html_url": "https://github.com/mitodl/micromasters/pull/2985",
    "body": "not a release",
    "title": "not a release",
}
RELEASE_PR = {
    "url": "https://api.github.com/repos/mitodl/micromasters/pulls/2993",
    "html_url": "https://github.com/mitodl/micromasters/pull/2993",
    "body": FAKE_RELEASE_PR_BODY,
    "title": "Release 0.53.3",
}
FAKE_PULLS = [OTHER_PR, RELEASE_PR]


def test_parse_checkmarks():
    """parse_checkmarks should look up the Release PR body and return a list of commits"""
    assert parse_checkmarks(FAKE_RELEASE_PR_BODY) == [
        {
            'checked': True,
            'author_name': 'Alice Pote',
            'title': 'Implemented AutomaticEmail API'
        },
        {
            'checked': False,
            'author_name': 'Alice Pote',
            'title': 'Unmarked some files as executable'
        },
        {
            'checked': True,
            'author_name': 'Nathan Levesque',
            'title': 'Fixed seed data for naive timestamps (#2712)'
        },
    ]


def test_get_release_pr():
    """get_release_pr should grab a release from GitHub's API"""
    org = 'org'
    repo = 'repo'
    version = '0.53.3'

    with patch('lib.requests.get', return_value=Mock(json=Mock(return_value=FAKE_PULLS))) as get_mock:
        pulls = get_release_pr(org, repo, version)
    get_mock.assert_called_once_with("https://api.github.com/repos/{org}/{repo}/pulls".format(
        org=org,
        repo=repo,
    ))
    assert pulls == RELEASE_PR


def test_get_release_pr_no_pulls():
    """If there is no release PR, an exception should be raised"""
    with pytest.raises(Exception) as ex, patch(
        'lib.requests.get', return_value=Mock(json=Mock(return_value=FAKE_PULLS))
    ):
        get_release_pr('org', 'repo', 'version')

    assert ex.value.args[0] == "No release pull request on server"


def test_too_many_releases():
    """If there is no release PR, an exception should be raised"""
    pulls = [RELEASE_PR, RELEASE_PR]
    with pytest.raises(Exception) as ex, patch(
        'lib.requests.get', return_value=Mock(json=Mock(return_value=pulls))
    ):
        get_release_pr('org', 'repo', '0.53.3')

    assert ex.value.args[0] == "Too many release pull requests"


def test_get_unchecked_authors():
    """
    get_unchecked_authors should download the PR body, parse it,
    filter out checked authors and leave only unchecked ones
    """
    org = 'org'
    repo = 'repo'
    version = 'version'
    with patch('lib.get_release_pr', autospec=True, return_value=RELEASE_PR) as get_release_pr_mock:
        unchecked = get_unchecked_authors(org, repo, version)
    assert unchecked == {"Alice Pote"}
    get_release_pr_mock.assert_called_once_with(org, repo, version)


def test_get_org_and_repo():
    """get_org_and_repo should get the GitHub organization and repo from the directory"""
    # I would be fine with testing this on cwd but Travis has a really old version of git that doesn't support
    # get-url
    for git_url in [b"git@github.com:mitodl/release-script.git", b"https://github.com/mitodl/release-script.git"]:
        cwd = os.path.dirname(__file__)
        with patch('lib.check_output', autospec=True, return_value=git_url) as check_output_stub:
            assert get_org_and_repo(cwd) == ("mitodl", "release-script")
        check_output_stub.assert_called_once_with(["git", "remote", "get-url", "origin"], cwd=cwd)


def test_next_workday_at_10():
    """next_workday_at_10 should get the time that's tomorrow at 10am, or Monday if that's the next workday"""
    saturday_at_8am = datetime(2017, 4, 1, 8)
    assert next_workday_at_10(saturday_at_8am) == datetime(2017, 4, 3, 10)
    tuesday_at_4am = datetime(2017, 4, 4, 4)
    assert next_workday_at_10(tuesday_at_4am) == datetime(2017, 4, 5, 10)
    wednesday_at_3pm = datetime(2017, 4, 5, 15)
    assert next_workday_at_10(wednesday_at_3pm) == datetime(2017, 4, 6, 10)


def test_reformatted_full_name():
    """reformatted_full_name should take the first and last names and make it lowercase"""
    assert reformatted_full_name("") == ""
    assert reformatted_full_name("George") == "george"
    assert reformatted_full_name("X Y Z A B") == "x b"


FAKE_SLACK_USERS = [
    {
        'profile': {
            'real_name': 'George Schneeloch',
        },
        'name': 'gschneel',
    }
]


def test_match_users():
    """match_users should use the Levensthein distance to compare usernames"""
    assert match_user(FAKE_SLACK_USERS, "George Schneeloch") == "<@gschneel|gschneel>"
    assert match_user(FAKE_SLACK_USERS, "George Schneelock") == "<@gschneel|gschneel>"
    assert match_user(FAKE_SLACK_USERS, "George") == "George"
