"""Get release status of a repository"""
from constants import (
    BLOCKER_LABELS,
    BLOCKER,
    DEPLOYED_TO_PROD,
    LIBRARY_TYPE,
    LIBRARY_PR_WAITING_FOR_MERGE,
    RELEASE_LABELS,
    STATUS_EMOJIS,
    WAITING_FOR_CHECKBOXES,
)
from github import (
    get_labels,
    get_org_and_repo,
)
from lib import (
    get_default_branch,
    get_release_pr,
    init_working_dir,
)
from release import any_new_commits
from version import get_project_version


async def status_for_repo_last_pr(*, github_access_token, repo_info):
    """
    Calculate release status for the most recent PR

    The return value will be one of:

      ALL_CHECKBOXES_CHECKED - All checkboxes are checked off and the release is ready to merge
      DEPLOYED_TO_PROD - The release has been successfully deployed to production
      DEPLOYING_TO_PROD - The release is in the process of being deployed to production
      DEPLOYING_TO_RC - The pull request is in the middle of deploying to RC
      FREEZE_RELEASE - The release is frozen, so it should be ignored until that github label is removed
      LIBRARY_WAITING_FOR_RELEASE - There is a release PR for a library, waiting on the release manager to merge
      WAITING_FOR_CHECKBOXES - The bot is polling regularly to check if all checkboxes are checked off

    Or None if there is no previous release, or something unexpected happened.

    Args:
        github_access_token (str): The github access token
        repo_info (RepoInfo): Repository info

    Returns:
        str or None: A status string
    """
    org, repo = get_org_and_repo(repo_info.repo_url)
    release_pr = await get_release_pr(
        github_access_token=github_access_token,
        org=org,
        repo=repo,
        all_prs=True,
    )
    if release_pr:
        if repo_info.project_type == LIBRARY_TYPE:
            if release_pr.open:
                return LIBRARY_PR_WAITING_FOR_MERGE
        else:
            labels = {
                label.lower()
                for label in await get_labels(
                    github_access_token=github_access_token,
                    repo_url=repo_info.repo_url,
                    pr_number=release_pr.number,
                )
            }
            for label in BLOCKER_LABELS:
                if label.lower() in labels:
                    return label.lower() if release_pr.open else None

            if not release_pr.open and WAITING_FOR_CHECKBOXES.lower() in labels:
                # If a PR is closed and the label is 'waiting for checkboxes', just ignore it
                # Maybe a user closed the PR, or the label was incorrectly updated
                return None

            for label in RELEASE_LABELS:
                if label.lower() in labels:
                    return label.lower()

    return None


async def status_for_repo_new_commits(*, github_access_token, repo_info):
    """
    Check if there are new commits to be part of a release

    Args:
        github_access_token (str): The github access token
        repo_info (RepoInfo): Repository info

    Returns:
        bool:
            Whether or not there are new commits
    """
    async with init_working_dir(github_access_token, repo_info.repo_url) as working_dir:
        last_version = await get_project_version(
            repo_info=repo_info, working_dir=working_dir
        )
        default_branch = await get_default_branch(working_dir)
        return await any_new_commits(
            last_version, base_branch=default_branch, root=working_dir
        )


def format_status_for_repo(*, current_status, has_new_commits):
    """
    Adds formatting to render a status

    Args:
        current_status (str): The status of the most recent PR for the repo
        has_new_commits (bool): Whether there are new commits to release
    """
    new_status_string = "*new commits*" if has_new_commits else ""
    current_status_string = (
        current_status if current_status and current_status != DEPLOYED_TO_PROD else ""
    )
    emoji = STATUS_EMOJIS.get(current_status, "")
    return f"{current_status_string}{emoji} {new_status_string}".strip()
