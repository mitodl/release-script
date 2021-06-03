"""Tests for github functions"""
import json
import os
from urllib.parse import quote

import pytest

from constants import SCRIPT_DIR
from github import (
    add_label,
    create_pr,
    delete_label,
    get_labels,
    get_org_and_repo,
    get_pull_request,
    github_auth_headers,
    needs_review,
    NEEDS_REVIEW_QUERY,
)
from test_constants import RELEASE_PR


pytestmark = pytest.mark.asyncio


async def test_needs_review(mocker):
    """Assert behavior of needs review"""
    with open(os.path.join(SCRIPT_DIR, "test_needs_review_response.json")) as f:
        payload = json.load(f)
    github_access_token = "token"

    patched = mocker.async_patch("github.run_query", return_value=payload)
    assert await needs_review(github_access_token) == [
        (
            "release-script",
            "Add PR karma",
            "https://github.com/mitodl/release-script/pull/88",
        ),
        (
            "release-script",
            "Add codecov integration",
            "https://github.com/mitodl/release-script/pull/85",
        ),
        (
            "release-script",
            "Add repo name to certain doof messages",
            "https://github.com/mitodl/release-script/pull/83",
        ),
        (
            "cookiecutter-djangoapp",
            "Don't reference INSTALLED_APPS directly",
            "https://github.com/mitodl/cookiecutter-djangoapp/pull/104",
        ),
        (
            "cookiecutter-djangoapp",
            "Refactor docker-compose setup",
            "https://github.com/mitodl/cookiecutter-djangoapp/pull/101",
        ),
        (
            "cookiecutter-djangoapp",
            "Use application LOG_LEVEL environment variable for celery workers",
            "https://github.com/mitodl/cookiecutter-djangoapp/pull/103",
        ),
        (
            "micromasters",
            "Log failed send_automatic_email and update_percolate_memberships",
            "https://github.com/mitodl/micromasters/pull/3707",
        ),
        (
            "open-discussions",
            "split post display into two components",
            "https://github.com/mitodl/open-discussions/pull/331",
        ),
        (
            "edx-platform",
            "Exposed option to manage static asset imports for studio import",
            "https://github.com/mitodl/edx-platform/pull/41",
        ),
    ]
    patched.assert_called_once_with(
        github_access_token=github_access_token,
        query=NEEDS_REVIEW_QUERY,
    )


async def test_create_pr(mocker):
    """create_pr should create a pr or raise an exception if the attempt failed"""
    access_token = "github_access_token"
    org = "abc"
    repo = "xyz"
    title = "title"
    body = "body"
    head = "head"
    base = "base"
    patched = mocker.async_patch("client_wrapper.ClientWrapper.post")
    await create_pr(
        github_access_token=access_token,
        repo_url="https://github.com/{}/{}.git".format(org, repo),
        title=title,
        body=body,
        head=head,
        base=base,
    )
    endpoint = "https://api.github.com/repos/{}/{}/pulls".format(org, repo)
    patched.assert_called_once_with(
        mocker.ANY,
        endpoint,
        headers={
            "Authorization": "Bearer {}".format(access_token),
            "Accept": "application/vnd.github.v3+json",
        },
        data=json.dumps(
            {
                "title": title,
                "body": body,
                "head": head,
                "base": base,
            }
        ),
    )


async def test_github_auth_headers():
    """github_auth_headers should have appropriate headers for autentication"""
    github_access_token = "access"
    assert github_auth_headers(github_access_token) == {
        "Authorization": "Bearer {}".format(github_access_token),
        "Accept": "application/vnd.github.v3+json",
    }


async def test_get_org_and_repo():
    """get_org_and_repo should get the GitHub organization and repo from the directory"""
    for git_url in [
        "git@github.com:mitodl/release-script.git",
        "https://github.com/mitodl/release-script.git",
    ]:
        assert get_org_and_repo(git_url) == ("mitodl", "release-script")


BASE_DIR = os.path.dirname(os.path.abspath(__file__))


NEEDS_REVIEW_LABEL_JSON = {
    "id": 324682350,
    "node_id": "MDU6TGFiZWwzMjQ2ODIzNTA=",
    "url": "https://api.github.com/repos/mitodl/release-script/labels/Needs%20review",
    "name": "Needs review",
    "color": "fef2c0",
    "default": False,
    "description": None,
}
TESTING_LABEL_JSON = {
    "id": 2994207717,
    "node_id": "MDU6TGFiZWwyOTk0MjA3NzE3",
    "url": "https://api.github.com/repos/mitodl/release-script/labels/testing",
    "name": "testing",
    "color": "ededed",
    "default": False,
    "description": None,
}


async def test_get_labels(mocker):
    """get_labels should retrieve labels from github"""
    response = mocker.Mock(
        json=mocker.Mock(return_value=[NEEDS_REVIEW_LABEL_JSON, TESTING_LABEL_JSON])
    )
    patched = mocker.async_patch(
        "client_wrapper.ClientWrapper.get", return_value=response
    )
    token = "token"
    org = "mitodl"
    repo = "release-script"
    repo_url = f"git@github.com:{org}/{repo}.git"
    pr_number = 1234

    assert await get_labels(
        github_access_token=token, repo_url=repo_url, pr_number=pr_number
    ) == [NEEDS_REVIEW_LABEL_JSON["name"], TESTING_LABEL_JSON["name"]]
    patched.assert_called_once_with(
        mocker.ANY,
        f"https://api.github.com/repos/{org}/{repo}/issues/{pr_number}/labels",
        headers=github_auth_headers(token),
    )
    response.raise_for_status.assert_called_once_with()


async def test_add_label(mocker):
    """add_label should add a new label on a pr"""
    response = mocker.Mock()
    patched = mocker.async_patch(
        "client_wrapper.ClientWrapper.post", return_value=response
    )
    token = "token"
    org = "mitodl"
    repo = "release-script"
    repo_url = f"git@github.com:{org}/{repo}.git"
    pr_number = 1234
    label = "new label"

    await add_label(
        github_access_token=token,
        repo_url=repo_url,
        pr_number=pr_number,
        label=label,
    )
    patched.assert_called_once_with(
        mocker.ANY,
        f"https://api.github.com/repos/{org}/{repo}/issues/{pr_number}/labels",
        json={"labels": [label]},
        headers=github_auth_headers(token),
    )
    response.raise_for_status.assert_called_once_with()


@pytest.mark.parametrize(
    "status, expected_raise_for_status", [[200, True], [400, True], [404, False]]
)
async def test_delete_label(mocker, status, expected_raise_for_status):
    """delete_label should remove a label from a pr"""
    response = mocker.Mock(status_code=status)
    patched = mocker.async_patch(
        "client_wrapper.ClientWrapper.delete", return_value=response
    )
    token = "token"
    org = "mitodl"
    repo = "release-script"
    repo_url = f"git@github.com:{org}/{repo}.git"
    pr_number = 1234
    label = "existing label"

    await delete_label(
        github_access_token=token,
        repo_url=repo_url,
        pr_number=pr_number,
        label=label,
    )
    patched.assert_called_once_with(
        mocker.ANY,
        f"https://api.github.com/repos/{org}/{repo}/issues/{pr_number}/labels/{quote(label)}",
        headers=github_auth_headers(token),
    )
    assert response.raise_for_status.called is expected_raise_for_status


@pytest.mark.parametrize("all_prs", [True, False])
@pytest.mark.parametrize("has_pr", [True, False])
async def test_get_pull_request(mocker, all_prs, has_pr):
    """get_pull_request should fetch a pull request from GitHub's API"""
    org = "org"
    repo = "repo"
    access_token = "access"
    branch = "release-candidate"

    get_mock = mocker.async_patch(
        "client_wrapper.ClientWrapper.get",
        return_value=mocker.Mock(
            json=mocker.Mock(return_value=[RELEASE_PR] if has_pr else [])
        ),
    )
    response = await get_pull_request(
        github_access_token=access_token,
        org=org,
        repo=repo,
        branch=branch,
        all_prs=all_prs,
    )
    assert response == (RELEASE_PR if has_pr else None)
    get_mock.return_value.raise_for_status.assert_called_once_with()
    state = "all" if all_prs else "open"
    get_mock.assert_called_once_with(
        mocker.ANY,
        f"https://api.github.com/repos/{org}/{repo}/pulls?state={state}&head={org}:{branch}&per_page=1",
        headers=github_auth_headers(access_token),
    )
