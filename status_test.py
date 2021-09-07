"""Tests for statuses"""
import pytest


from constants import (
    ALL_CHECKBOXES_CHECKED,
    BLOCKED,
    BLOCKER,
    BLOCKER_LABELS,
    DEPLOYING_TO_RC,
    DEPLOYING_TO_PROD,
    DEPLOYED_TO_PROD,
    FREEZE_RELEASE,
    LIBRARY_PR_WAITING_FOR_MERGE,
    RELEASE_BLOCKER,
    RELEASE_LABELS,
    WAITING_FOR_CHECKBOXES,
)
from github import get_org_and_repo
from lib import ReleasePR
from status import (
    status_for_repo_last_pr,
    status_for_repo_new_commits,
    format_status_for_repo,
)
from test_util import (
    async_context_manager_yielder,
)


pytestmark = pytest.mark.asyncio
GITHUB_TOKEN = "github-token"


@pytest.mark.parametrize(
    "has_new_commits, status, expected",
    [
        [True, None, "*new commits*"],
        [False, None, ""],
        [True, ALL_CHECKBOXES_CHECKED, f"{ALL_CHECKBOXES_CHECKED}🔔 *new commits*"],
        [False, ALL_CHECKBOXES_CHECKED, f"{ALL_CHECKBOXES_CHECKED}🔔"],
        [True, DEPLOYED_TO_PROD, "*new commits*"],
        [False, DEPLOYED_TO_PROD, ""],
        [True, DEPLOYING_TO_PROD, f"{DEPLOYING_TO_PROD}🕰️ *new commits*"],
        [False, DEPLOYING_TO_PROD, f"{DEPLOYING_TO_PROD}🕰️"],
        [True, DEPLOYING_TO_RC, f"{DEPLOYING_TO_RC}🕰️ *new commits*"],
        [False, DEPLOYING_TO_RC, f"{DEPLOYING_TO_RC}🕰️"],
        [True, FREEZE_RELEASE, f"{FREEZE_RELEASE}❌ *new commits*"],
        [False, FREEZE_RELEASE, f"{FREEZE_RELEASE}❌"],
        [True, BLOCKED, f"{BLOCKED}❌ *new commits*"],
        [False, BLOCKED, f"{BLOCKED}❌"],
        [True, BLOCKER, f"{BLOCKER}❌ *new commits*"],
        [False, BLOCKER, f"{BLOCKER}❌"],
        [True, RELEASE_BLOCKER, f"{RELEASE_BLOCKER}❌ *new commits*"],
        [False, RELEASE_BLOCKER, f"{RELEASE_BLOCKER}❌"],
        [
            True,
            LIBRARY_PR_WAITING_FOR_MERGE,
            f"{LIBRARY_PR_WAITING_FOR_MERGE}🔔 *new commits*",
        ],
        [False, LIBRARY_PR_WAITING_FOR_MERGE, f"{LIBRARY_PR_WAITING_FOR_MERGE}🔔"],
        [True, WAITING_FOR_CHECKBOXES, f"{WAITING_FOR_CHECKBOXES}🕰️ *new commits*"],
        [False, WAITING_FOR_CHECKBOXES, f"{WAITING_FOR_CHECKBOXES}🕰️"],
    ],
)
def test_format_status_for_repo(has_new_commits, status, expected):
    """format_status_for_repo should create an appropriate description given a status and if there are new commits"""
    assert (
        format_status_for_repo(current_status=status, has_new_commits=has_new_commits)
        == expected
    )


@pytest.mark.parametrize(
    "has_release_pr, is_library_project, is_open, labels, expected",
    [
        [False, False, False, [], None],
        [True, True, True, [], LIBRARY_PR_WAITING_FOR_MERGE],
        [True, True, False, [], None],
        [True, False, False, [], None],
        [True, False, False, [WAITING_FOR_CHECKBOXES, BLOCKED], BLOCKED],
        [True, False, False, [BLOCKED, WAITING_FOR_CHECKBOXES], BLOCKED],
        *[
            [True, False, False, [label], label]
            for label in [*BLOCKER_LABELS, *RELEASE_LABELS]
        ],
    ],
)
async def test_status_for_repo_last_pr(
    mocker,
    test_repo,
    library_test_repo,
    has_release_pr,
    is_library_project,
    is_open,
    labels,
    expected,
):  # pylint: disable=too-many-arguments
    """status_for_repo_last_pr should get the status for the most recent PR for a project"""
    release_pr = ReleasePR("1.2.3", "http://example.com", "body", 12, is_open)
    get_release_pr_mock = mocker.async_patch(
        "status.get_release_pr", return_value=release_pr if has_release_pr else None
    )
    get_labels_mock = mocker.async_patch("status.get_labels", return_value=labels)

    repo_info = library_test_repo if is_library_project else test_repo
    org, repo = get_org_and_repo(repo_info.repo_url)
    assert (
        await status_for_repo_last_pr(
            github_access_token=GITHUB_TOKEN, repo_info=repo_info
        )
        == expected
    )

    get_release_pr_mock.assert_called_once_with(
        github_access_token=GITHUB_TOKEN,
        org=org,
        repo=repo,
        all_prs=True,
    )
    if not is_library_project and has_release_pr:
        get_labels_mock.assert_called_once_with(
            github_access_token=GITHUB_TOKEN,
            repo_url=repo_info.repo_url,
            pr_number=release_pr.number,
        )
    else:
        assert get_labels_mock.called is False


@pytest.mark.parametrize("has_commits", [True, False])
async def test_status_for_repo_new_commits(
    mocker, test_repo, test_repo_directory, has_commits
):
    """status_for_repo_new_commits should check if there are new commits"""
    init_mock = mocker.patch(
        "status.init_working_dir",
        side_effect=async_context_manager_yielder(test_repo_directory),
    )
    get_project_version_mock = mocker.async_patch("status.get_project_version")
    get_default_branch_mock = mocker.async_patch("status.get_default_branch")
    new_commits_mock = mocker.async_patch(
        "status.any_new_commits", return_value=has_commits
    )
    assert (
        await status_for_repo_new_commits(
            github_access_token=GITHUB_TOKEN,
            repo_info=test_repo,
        )
        == has_commits
    )

    init_mock.assert_called_once_with(GITHUB_TOKEN, test_repo.repo_url)
    get_project_version_mock.assert_called_once_with(
        repo_info=test_repo, working_dir=test_repo_directory
    )
    get_default_branch_mock.assert_called_once_with(test_repo_directory)
    new_commits_mock.assert_called_once_with(
        get_project_version_mock.return_value,
        base_branch=get_default_branch_mock.return_value,
        root=test_repo_directory,
    )
