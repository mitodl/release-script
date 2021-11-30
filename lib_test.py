"""Tests for lib"""
from requests import Response, HTTPError
import pytest

from constants import (
    DJANGO,
    FILE_VERSION,
    LIBRARY_TYPE,
    NONE,
    NPM,
    NPM_VERSION,
    PYTHON_VERSION,
    WEB_APPLICATION_TYPE,
)
from lib import (
    get_default_branch,
    get_release_pr,
    get_unchecked_authors,
    load_repos_info,
    match_user,
    next_versions,
    parse_checkmarks,
    parse_text_matching_options,
    reformatted_full_name,
    ReleasePR,
    remove_path_from_url,
    url_with_access_token,
)
from repo_info import RepoInfo
from test_util import async_wrapper, sync_call as call
from test_constants import FAKE_RELEASE_PR_BODY, RELEASE_PR


pytestmark = pytest.mark.asyncio


async def test_parse_checkmarks():
    """parse_checkmarks should look up the Release PR body and return a list of commits"""
    assert parse_checkmarks(FAKE_RELEASE_PR_BODY) == [
        {
            "checked": True,
            "author_name": "Alice Pote",
            "title": "Implemented AutomaticEmail API",
        },
        {
            "checked": False,
            "author_name": "Alice Pote",
            "title": "Unmarked some files as executable",
        },
        {
            "checked": True,
            "author_name": "Nathan Levesque",
            "title": "Fixed seed data for naive timestamps (#2712)",
        },
    ]


@pytest.mark.parametrize("all_prs", [True, False])
@pytest.mark.parametrize("has_pr", [True, False])
@pytest.mark.parametrize("wrong_title", [True, False])
async def test_get_release_pr(mocker, all_prs, has_pr, wrong_title):
    """get_release_pr should grab a release from GitHub's API"""
    org = "org"
    repo = "repo"
    access_token = "access"

    if wrong_title:
        release_pr_json = {**RELEASE_PR, "title": "Some other title"}
    else:
        release_pr_json = RELEASE_PR
    get_pull_request_mock = mocker.async_patch(
        "lib.get_pull_request", return_value=release_pr_json if has_pr else None
    )
    pr = await get_release_pr(
        github_access_token=access_token, org=org, repo=repo, all_prs=all_prs
    )
    get_pull_request_mock.assert_called_once_with(
        github_access_token=access_token,
        org=org,
        repo=repo,
        branch="release-candidate",
        all_prs=all_prs,
    )
    if has_pr and not wrong_title:
        assert pr.body == RELEASE_PR["body"]
        assert pr.url == RELEASE_PR["html_url"]
        assert pr.version == "0.53.3"
        assert pr.number == 234
    else:
        assert pr is None


async def test_no_release_wrong_repo(mocker):
    """If there is no repo accessible, an exception should be raised"""
    response_404 = Response()
    response_404.status_code = 404
    mocker.async_patch("client_wrapper.ClientWrapper.get", return_value=response_404)
    with pytest.raises(HTTPError) as ex:
        await get_release_pr(
            github_access_token="access_token",
            org="org",
            repo="repo",
        )

    assert ex.value.response.status_code == 404


async def test_get_unchecked_authors(mocker):
    """
    get_unchecked_authors should download the PR body, parse it,
    filter out checked authors and leave only unchecked ones
    """
    org = "org"
    repo = "repo"
    access_token = "all-access"

    get_release_pr_mock = mocker.async_patch(
        "lib.get_release_pr",
        return_value=ReleasePR(
            body=FAKE_RELEASE_PR_BODY,
            version="1.2.3",
            url="http://url",
            number=234,
            open=False,
        ),
    )
    unchecked = await get_unchecked_authors(
        github_access_token=access_token,
        org=org,
        repo=repo,
    )
    assert unchecked == {"Alice Pote"}
    get_release_pr_mock.assert_called_once_with(
        github_access_token=access_token,
        org=org,
        repo=repo,
    )


async def test_reformatted_full_name():
    """reformatted_full_name should take the first and last names and make it lowercase"""
    assert reformatted_full_name("") == ""
    assert reformatted_full_name("George") == "george"
    assert reformatted_full_name("X Y Z A B") == "x b"


FAKE_SLACK_USERS = [
    {
        "profile": {
            "real_name": "George Schneeloch",
        },
        "id": "U12345",
    },
    {"profile": {"real_name": "Sar Haidar"}, "id": "U65432"},
    {"profile": {"real_name": "Sarah H"}, "id": "U13986"},
    {"profile": {"real_name": "Tasawer Nawaz"}, "id": "U9876"},
]


async def test_match_users():
    """match_users should use the Levensthein distance to compare usernames"""
    assert match_user(FAKE_SLACK_USERS, "George Schneeloch") == "<@U12345>"
    assert match_user(FAKE_SLACK_USERS, "George Schneelock") == "<@U12345>"
    assert match_user(FAKE_SLACK_USERS, "George") == "<@U12345>"
    assert match_user(FAKE_SLACK_USERS, "sar") == "<@U65432>"
    assert match_user(FAKE_SLACK_USERS, "tasawernawaz") == "<@U9876>"


async def test_url_with_access_token():
    """url_with_access_token should insert the access token into the url"""
    assert (
        url_with_access_token("access", "http://github.com/mitodl/release-script.git")
        == "https://access@github.com/mitodl/release-script.git"
    )


async def test_load_repos_info(mocker):
    """
    load_repos_info should match channels with repositories
    """
    json_load = mocker.patch(
        "lib.json.load",
        autospec=True,
        return_value={
            "repos": [
                {
                    "name": "bootcamp-ecommerce",
                    "repo_url": "https://github.com/mitodl/bootcamp-ecommerce.git",
                    "ci_hash_url": "https://bootcamp-ecommerce-ci.herokuapp.com/static/hash.txt",
                    "rc_hash_url": "https://bootcamp-ecommerce-rc.herokuapp.com/static/hash.txt",
                    "prod_hash_url": "https://bootcamp-ecommerce.herokuapp.com/static/hash.txt",
                    "channel_name": "bootcamp-eng",
                    "project_type": WEB_APPLICATION_TYPE,
                    "web_application_type": DJANGO,
                    "versioning_strategy": PYTHON_VERSION,
                },
                {
                    "name": "bootcamp-ecommerce-library",
                    "repo_url": "https://github.com/mitodl/bootcamp-ecommerce-library.git",
                    "channel_name": "bootcamp-library",
                    "project_type": LIBRARY_TYPE,
                    "packaging_tool": NPM,
                    "versioning_strategy": NPM_VERSION,
                },
                {
                    "name": "ocw-hugo-projects",
                    "repo_url": "https://github.com/mitodl/ocw-hugo-projects.git",
                    "channel_name": "ocw-hugo-projects",
                    "project_type": "library",
                    "packaging_tool": "none",
                    "versioning_strategy": FILE_VERSION,
                },
            ]
        },
    )

    expected_web_application = RepoInfo(
        name="bootcamp-ecommerce",
        repo_url="https://github.com/mitodl/bootcamp-ecommerce.git",
        ci_hash_url="https://bootcamp-ecommerce-ci.herokuapp.com/static/hash.txt",
        rc_hash_url="https://bootcamp-ecommerce-rc.herokuapp.com/static/hash.txt",
        prod_hash_url="https://bootcamp-ecommerce.herokuapp.com/static/hash.txt",
        channel_id="bootcamp_channel_id",
        project_type=WEB_APPLICATION_TYPE,
        web_application_type=DJANGO,
        packaging_tool=None,
        versioning_strategy=PYTHON_VERSION,
    )
    expected_npm_library = RepoInfo(
        name="bootcamp-ecommerce-library",
        repo_url="https://github.com/mitodl/bootcamp-ecommerce-library.git",
        ci_hash_url=None,
        rc_hash_url=None,
        prod_hash_url=None,
        channel_id="bootcamp_library_channel_id",
        project_type=LIBRARY_TYPE,
        web_application_type=None,
        packaging_tool=NPM,
        versioning_strategy=NPM_VERSION,
    )
    expected_file_library = RepoInfo(
        name="ocw-hugo-projects",
        repo_url="https://github.com/mitodl/ocw-hugo-projects.git",
        ci_hash_url=None,
        rc_hash_url=None,
        prod_hash_url=None,
        channel_id="ocw_hugo_channel_id",
        project_type=LIBRARY_TYPE,
        web_application_type=None,
        packaging_tool=NONE,
        versioning_strategy=FILE_VERSION,
    )

    assert (
        load_repos_info(
            {
                "bootcamp-eng": "bootcamp_channel_id",
                "bootcamp-library": "bootcamp_library_channel_id",
                "ocw-hugo-projects": "ocw_hugo_channel_id",
            }
        )
        == [expected_web_application, expected_npm_library, expected_file_library]
    )
    assert json_load.call_count == 1


async def test_next_versions():
    """next_versions should return a tuple of the updated minor and patch versions"""
    assert next_versions("1.2.3") == ("1.3.0", "1.2.4")


async def test_async_wrapper(mocker):
    """async_wrapper should convert a sync function into a trivial async function"""
    func = mocker.Mock()
    async_func = async_wrapper(func)
    await async_func()
    await async_func()
    assert func.call_count == 2


async def test_async_patch(mocker):
    """async_patch should patch with an async function"""
    mocked = mocker.async_patch("lib_test.call")
    mocked.return_value = 123
    assert await call(["ls"], cwd="/") == 123
    assert await call(["ls"], cwd="/") == 123


@pytest.mark.parametrize(
    "url,expected",
    [
        ["https://www.example.com", "https://www.example.com"],
        ["http://mit.edu/a/path", "http://mit.edu"],
        ["http://example.com:5678/?query=params#included", "http://example.com:5678"],
    ],
)
def test_remove_path_from_url(url, expected):
    """remove_path_from_url should only keep the scheme, port, and host parts of the URL"""
    assert remove_path_from_url(url) == expected


def test_parse_text_matching_options():
    """
    parse_text_matching_options should create a function to return the same text if it matches one of the options
    """
    assert parse_text_matching_options(["abc", "xyz"])("xyz") == "xyz"
    assert parse_text_matching_options(["abc", "xyz"])("abc") == "abc"


def test_parse_text_matching_options_error():
    """
    parse_text_matching_options should error if the text does not match an option
    """
    with pytest.raises(Exception) as ex:
        parse_text_matching_options(["abc", "xyz"])("def")
    assert ex.value.args[0] == "Unexpected option def. Valid options: abc, xyz"


async def test_get_default_branch(test_repo_directory):
    """
    get_default_branch should get master or main, depending on the default branch in the repository
    """
    assert await get_default_branch(test_repo_directory) == "master"
