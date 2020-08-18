"""Wait for Travis to finish the build"""
import asyncio

from constants import (
    NO_PR_BUILD,
    TRAVIS_FAILURE,
    TRAVIS_SUCCESS,
)
from github import get_status_of_pr


async def wait_for_travis(*, github_access_token, org, repo, branch):
    """Wait for the PR status to become good"""
    status = await get_status_of_pr(
        github_access_token=github_access_token, org=org, repo=repo, branch=branch
    )

    # If status is none we should try just once more. Maybe the PR is not yet created.
    if status in (TRAVIS_FAILURE, TRAVIS_SUCCESS):
        return status

    # Wait 30 seconds then try again
    await asyncio.sleep(30)

    while True:
        status = await get_status_of_pr(
            github_access_token=github_access_token, org=org, repo=repo, branch=branch
        )
        if status in (TRAVIS_FAILURE, NO_PR_BUILD, TRAVIS_SUCCESS):
            return status

        # Wait 30 seconds then try again
        await asyncio.sleep(30)
