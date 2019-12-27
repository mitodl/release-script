"""Wait for hash on server to match with deployed code"""
import asyncio

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
        raise Exception("Expected release hash from {hash_url} but got: {hash}".format(
            hash_url=hash_url,
            hash=release_hash,
        ))
    return release_hash


async def is_release_deployed(*, github_access_token, repo_url, hash_url, branch):
    """
    Is server finished with the deploy?
    """
    async with init_working_dir(github_access_token, repo_url):
        output = await check_output(["git", "rev-parse", "origin/{}".format(branch)])
        latest_hash = output.decode().strip()
    return await fetch_release_hash(hash_url) == latest_hash


async def wait_for_deploy(*, github_access_token, repo_url, hash_url, watch_branch):
    """
    Wait until server is finished with the deploy

    Args:
        github_access_token (str): A github access token
        repo_url (str): The repository URL which has the latest commit hash to check
        hash_url (str): The deployment URL which has the commit of the deployed app
        watch_branch (str): The branch in the repository which has the latest commit

    Returns:
        bool:
            True if the hashes matched immediately on checking, False if hashes matched only after checking
    """
    async with init_working_dir(github_access_token, repo_url):
        output = await check_output(["git", "rev-parse", "origin/{}".format(watch_branch)])
        latest_hash = output.decode().strip()
    while await fetch_release_hash(hash_url) != latest_hash:
        await asyncio.sleep(30)
