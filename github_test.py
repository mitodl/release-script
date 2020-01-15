"""Tests for github functions"""
from datetime import date, datetime, timezone
import json
import os

from dateutil.parser import parse
import pytest

from constants import (
    NO_PR_BUILD,
    SCRIPT_DIR,
    TRAVIS_PENDING,
    TRAVIS_FAILURE,
    TRAVIS_SUCCESS,
)
from github import (
    create_pr,
    calculate_karma,
    fetch_issues_for_pull_requests,
    fetch_pull_requests_since_date,
    get_issue,
    get_org_and_repo,
    get_status_of_pr,
    github_auth_headers,
    make_issue_release_notes,
    make_pull_requests_query,
    needs_review,
    KARMA_QUERY,
    NEEDS_REVIEW_QUERY,
    PullRequest,
)
from test_util import (
    async_gen_wrapper,
    make_issue,
    make_parsed_issue,
    make_pr,
    TEST_ORG,
    TEST_REPO,
)


pytestmark = pytest.mark.asyncio


async def test_karma(mocker):
    """Assert behavior of karma calculation"""
    with open(os.path.join(SCRIPT_DIR, "test_karma_response.json")) as f:
        payload = json.load(f)
    github_access_token = 'token'

    patched = mocker.async_patch('github.run_query', return_value=payload)
    assert await calculate_karma(
        github_access_token=github_access_token,
        begin_date=parse("2017-11-09").date(),
        end_date=parse("2017-11-09").date(),
    ) == [
        ('Tobias Macey', 1),
    ]
    patched.assert_called_once_with(
        github_access_token=github_access_token,
        query=KARMA_QUERY,
    )


async def test_needs_review(mocker):
    """Assert behavior of needs review"""
    with open(os.path.join(SCRIPT_DIR, "test_needs_review_response.json")) as f:
        payload = json.load(f)
    github_access_token = 'token'

    patched = mocker.async_patch('github.run_query', return_value=payload)
    assert await needs_review(github_access_token) == [
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
    patched.assert_called_once_with(
        github_access_token=github_access_token,
        query=NEEDS_REVIEW_QUERY,
    )


async def test_create_pr(mocker):
    """create_pr should create a pr or raise an exception if the attempt failed"""
    access_token = 'github_access_token'
    org = 'abc'
    repo = 'xyz'
    title = 'title'
    body = 'body'
    head = 'head'
    base = 'base'
    patched = mocker.async_patch('client_wrapper.ClientWrapper.post')
    await create_pr(
        github_access_token=access_token,
        repo_url='https://github.com/{}/{}.git'.format(org, repo),
        title=title,
        body=body,
        head=head,
        base=base,
    )
    endpoint = 'https://api.github.com/repos/{}/{}/pulls'.format(org, repo)
    patched.assert_called_once_with(
        mocker.ANY,
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


async def test_github_auth_headers():
    """github_auth_headers should have appropriate headers for autentication"""
    github_access_token = 'access'
    assert github_auth_headers(github_access_token) == {
        "Authorization": "Bearer {}".format(github_access_token),
        "Accept": "application/vnd.github.v3+json",
    }


async def test_get_org_and_repo():
    """get_org_and_repo should get the GitHub organization and repo from the directory"""
    # I would be fine with testing this on cwd but Travis has a really old version of git that doesn't support
    # get-url
    for git_url in ["git@github.com:mitodl/release-script.git", "https://github.com/mitodl/release-script.git"]:
        assert get_org_and_repo(git_url) == ("mitodl", "release-script")


def _load_status(status):
    """Load statuses from test data"""
    with open(os.path.join(BASE_DIR, "test_data", "statuses_{}.json".format(status))) as f:
        return json.load(f)


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SUCCESS_DATA = _load_status("success")
FAILED_DATA = _load_status("failure")
PENDING_DATA = _load_status("pending")
NO_PR_BUILD_DATA = _load_status("no_pr_builds")


@pytest.mark.parametrize("status_code,status_data, expected_status", [
    [200, SUCCESS_DATA, TRAVIS_SUCCESS],
    [404, [], NO_PR_BUILD],
    [200, [], NO_PR_BUILD],
    [200, FAILED_DATA, TRAVIS_FAILURE],
    [200, PENDING_DATA, TRAVIS_PENDING],
    [200, NO_PR_BUILD_DATA, NO_PR_BUILD],
])
async def test_get_status_of_pr(mocker, status_code, status_data, expected_status):
    """get_status_of_pr should get the status of a PR"""

    org = 'org'
    repo = 'repo'
    token = 'token'
    branch = 'branch'

    patched = mocker.async_patch('client_wrapper.ClientWrapper.get')
    resp = patched.return_value
    resp.status_code = status_code
    resp.json.return_value = status_data
    assert await get_status_of_pr(
        github_access_token=token,
        org=org,
        repo=repo,
        branch=branch,
    ) == expected_status

    if status_code != 404:
        resp.raise_for_status.assert_called_once_with()

    endpoint = "https://api.github.com/repos/{org}/{repo}/commits/{ref}/statuses".format(
        org=org,
        repo=repo,
        ref=branch,
    )
    patched.assert_called_once_with(mocker.ANY, endpoint, headers=github_auth_headers(token))


async def test_fetch_pull_requests_since_date(mocker):  # pylint: disable=too-many-locals
    """fetch_pull_requests_since_date should construct a graphql query and fetch the results of that query"""
    org = "org"
    repo = "repo"
    token = "token"
    cursor = 'some cursor'
    pr_number = 12345
    url = 'http://url.com'
    title = "A PR title"
    body = "PR body"
    updated_in_bounds = datetime(2020, 1, 2, tzinfo=timezone.utc)
    updated_out_bounds = datetime(2019, 1, 1, tzinfo=timezone.utc)
    since = date(2020, 1, 1)

    edge_in_bounds = {
        'cursor': cursor,
        'node': {
            'number': pr_number,
            'url': url,
            'updatedAt': updated_in_bounds.isoformat(),
            'title': title,
            'body': body,
        }
    }
    edge_out_bounds = {
        'cursor': None,
        'node': {
            'number': pr_number,
            'url': url,
            'updatedAt': updated_out_bounds.isoformat(),
            'title': title,
            'body': body,
        }
    }
    result_in_bounds = {'data': {'organization': {'repository': {'pullRequests': {'edges': [edge_in_bounds]}}}}}
    result_out_bounds = {'data': {'organization': {'repository': {'pullRequests': {'edges': [edge_out_bounds]}}}}}

    patched = mocker.async_patch('github.run_query', side_effect=[result_in_bounds, result_out_bounds])

    prs = [pr async for pr in fetch_pull_requests_since_date(
        github_access_token=token,
        org=org,
        repo=repo,
        since=since
    )]
    assert prs == (
        [PullRequest(
            number=pr_number,
            title=title,
            body=body,
            updatedAt=updated_in_bounds.date(),
            org=org,
            repo=repo,
            url=url,
        )]
    )
    patched.assert_any_call(
        github_access_token=token,
        query=make_pull_requests_query(org=org, repo=repo, cursor=None),
    )
    patched.assert_any_call(
        github_access_token=token,
        query=make_pull_requests_query(org=org, repo=repo, cursor=cursor),
    )


async def test_fetch_issues_for_pull_requests(mocker):
    """fetch_issues_for_pull_requests should parse pull request text and look for issue links and numbers"""
    token = "a token"

    pr1 = make_pr(987, "Hey issue #345 and closes #456")
    pr2 = make_pr(989, "Another reference to issue #456")
    issues = {}
    for number in 345, 456:
        issues[number] = make_issue(number)

    def _get_issue(*, issue_number, **kwargs):  # pylint: disable=unused-argument
        """Helper function to look up issue"""
        return issues[issue_number]

    patched = mocker.async_patch('github.get_issue', side_effect=_get_issue)

    prs_and_issues = [tup async for tup in fetch_issues_for_pull_requests(
        github_access_token=token,
        pull_requests=async_gen_wrapper([pr1, pr2]),
    )]
    assert prs_and_issues == [
        (pr1, [
            (issues[345], make_parsed_issue(345, False)),
            (issues[456], make_parsed_issue(456, True)),
        ]),
        (pr2, [
            (issues[456], make_parsed_issue(456, False))
        ])
    ]
    for number in 345, 456:
        patched.assert_any_call(
            github_access_token=token,
            org=TEST_ORG,
            repo=TEST_REPO,
            issue_number=number,
        )


async def test_make_issue_release_notes():
    """make_issue_release_notes should create readable release notes for public consumption"""
    issue123, issue456 = make_issue(123), make_issue(456)
    pr1, pr2 = make_pr(1234, "fixes #123 and related to #456"), make_pr(3456, "Related to #456")
    prs_and_issues = [
        (pr1, [
            (issue123, make_parsed_issue(345, False)),
            (issue456, make_parsed_issue(456, True)),
        ]),
        (pr2, [
            (issue456, make_parsed_issue(456, False))
        ])
    ]

    assert make_issue_release_notes(prs_and_issues) == f"""{issue123.title} (<{issue123.url}|#{issue123.number}>)
{issue456.title} (<{issue456.url}|#{issue456.number}>)
"""


async def test_get_issue(mocker):
    """get_issue should fetch an issue via the REST API"""
    issue = make_issue(12345)
    token = "token"
    issue_json = {
        "title": issue.title,
        "number": issue.number,
        "state": issue.status,
        "updated_at": issue.updatedAt.isoformat(),
        "html_url": issue.url,
    }
    response = mocker.Mock(json=mocker.Mock(return_value=issue_json))
    patched = mocker.async_patch('client_wrapper.ClientWrapper.get', return_value=response)

    assert await get_issue(
        github_access_token=token,
        org=TEST_ORG,
        repo=TEST_REPO,
        issue_number=issue.number,
    ) == issue
    patched.assert_called_once_with(
        mocker.ANY,
        f"https://api.github.com/repos/{TEST_ORG}/{TEST_REPO}/issues/{issue.number}",
        headers=github_auth_headers(token),
    )


async def test_get_issue_but_its_a_pr(mocker):
    """get_issue should return None if it's actually fetching a PR"""
    issue_json = {
        "pull_request": "some pull request info"
    }
    response = mocker.Mock(json=mocker.Mock(return_value=issue_json))
    patched = mocker.async_patch('client_wrapper.ClientWrapper.get', return_value=response)
    token = "token"

    assert await get_issue(
        github_access_token=token,
        org=TEST_ORG,
        repo=TEST_REPO,
        issue_number=1234,
    ) is None
    patched.assert_called_once_with(
        mocker.ANY,
        f"https://api.github.com/repos/{TEST_ORG}/{TEST_REPO}/issues/1234",
        headers=github_auth_headers(token),
    )
