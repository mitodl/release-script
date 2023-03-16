"""Wait for hash on server to match with deployed code"""
import asyncio
import time

from async_subprocess import check_output
from client_wrapper import ClientWrapper
from release import init_working_dir


async def fetch_release_hash(hash_url):
    """Fetch the hash from the release"""
    client = ClientWrapper()
    response = await client.get(hash_url)
    response.raise_for_status()
    release_hash = response.content.decode().strip()
    if len(release_hash) != 40:
        raise Exception(
            f"Expected release hash from {hash_url} but got: {release_hash}"
        )
    return release_hash


async def wait_for_deploy(
    *, github_access_token, repo_url, hash_url, watch_branch, timeout_seconds=60 * 60
):
    """
    Wait until server is finished with the deploy

    Args:
        github_access_token (str): A github access token
        repo_url (str): The repository URL which has the latest commit hash to check
        hash_url (str): The deployment URL which has the commit of the deployed app
        watch_branch (str): The branch in the repository which has the latest commit
        timeout_seconds (int): The number of seconds to wait before timing out the deploy

    Returns:
        bool:
            True if the hashes matched, False if the check timed out
    """
    start_time = time.time()

    async with init_working_dir(github_access_token, repo_url) as working_dir:
        output = await check_output(
            ["git", "rev-parse", f"origin/{watch_branch}"], cwd=working_dir
        )
        latest_hash = output.decode().strip()
    while await fetch_release_hash(hash_url) != latest_hash:
        if (time.time() - start_time) > timeout_seconds:
            return False
        await asyncio.sleep(30)

    return True
