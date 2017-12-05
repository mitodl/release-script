"""Tests for github functions"""
import json
import os
from unittest.mock import patch

from dateutil.parser import parse

from bot import SCRIPT_DIR
from github import (
    create_pr,
    calculate_karma,
    get_org_and_repo,
    github_auth_headers,
    needs_review,
    KARMA_QUERY,
    NEEDS_REVIEW_QUERY,
)


def test_karma():
    """Assert behavior of karma calculation"""
    with open(os.path.join(SCRIPT_DIR, "test_karma_response.json")) as f:
        payload = json.load(f)
    github_access_token = 'token'

    with patch('github.run_query', autospec=True, return_value=payload) as patched:
        assert calculate_karma(github_access_token, parse("2017-11-09").date(), parse("2017-11-09").date()) == [
            ('Tobias Macey', 1),
        ]
    patched.assert_called_once_with(github_access_token, KARMA_QUERY)


def test_needs_review():
    """Assert behavior of needs review"""
    with open(os.path.join(SCRIPT_DIR, "test_needs_review_response.json")) as f:
        payload = json.load(f)
    github_access_token = 'token'

    with patch('github.run_query', autospec=True, return_value=payload) as patched:
        assert needs_review(github_access_token) == [
            ('release-script', 'Add PR karma', 'https://github.com/mitodl/release-script/pull/88'),
            ('release-script', 'Add codecov integration', 'https://github.com/mitodl/release-script/pull/85'),
            (
                'release-script',
                'Add repo name to certain doof messages',
                'https://github.com/mitodl/release-script/pull/83',
            ),
            (
                'cookiecutter-djangoapp',
                'Don\'t reference INSTALLED_APPS directly',
                'https://github.com/mitodl/cookiecutter-djangoapp/pull/104',
            ),
            (
                'cookiecutter-djangoapp',
                'Refactor docker-compose setup',
                'https://github.com/mitodl/cookiecutter-djangoapp/pull/101'
            ),
            (
                'cookiecutter-djangoapp',
                'Use application LOG_LEVEL environment variable for celery workers',
                'https://github.com/mitodl/cookiecutter-djangoapp/pull/103'
            ),
            (
                'micromasters',
                'Log failed send_automatic_email and update_percolate_memberships',
                'https://github.com/mitodl/micromasters/pull/3707'
            ),
            (
                'open-discussions',
                'split post display into two components',
                'https://github.com/mitodl/open-discussions/pull/331'
            ),
            (
                'edx-platform',
                'Exposed option to manage static asset imports for studio import',
                'https://github.com/mitodl/edx-platform/pull/41'
            ),
        ]
    patched.assert_called_once_with(github_access_token, NEEDS_REVIEW_QUERY)


def test_create_pr():
    """create_pr should create a pr or raise an exception if the attempt failed"""
    access_token = 'github_access_token'
    org = 'abc'
    repo = 'xyz'
    title = 'title'
    body = 'body'
    head = 'head'
    base = 'base'
    with patch('requests.post', autospec=True) as patched:
        create_pr(
            access_token,
            'https://github.com/{}/{}.git'.format(org, repo),
            title,
            body,
            head,
            base,
        )
    endpoint = 'https://api.github.com/repos/{}/{}/pulls'.format(org, repo)
    patched.assert_called_once_with(
        endpoint,
        headers={
            "Authorization": "Bearer {}".format(access_token),
            "Accept": "application/vnd.github.v3+json",
        },
        data=json.dumps({
            'title': title,
            'body': body,
            'head': head,
            'base': base,
        })
    )


def test_github_auth_headers():
    """github_auth_headers should have appropriate headers for autentication"""
    github_access_token = 'access'
    assert github_auth_headers(github_access_token) == {
        "Authorization": "Bearer {}".format(github_access_token),
        "Accept": "application/vnd.github.v3+json",
    }


def test_get_org_and_repo():
    """get_org_and_repo should get the GitHub organization and repo from the directory"""
    # I would be fine with testing this on cwd but Travis has a really old version of git that doesn't support
    # get-url
    for git_url in ["git@github.com:mitodl/release-script.git", "https://github.com/mitodl/release-script.git"]:
        assert get_org_and_repo(git_url) == ("mitodl", "release-script")
