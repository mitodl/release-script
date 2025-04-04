"""Wait for hash on server to match with deployed code"""

import asyncio
import json
import logging
import time

from async_subprocess import check_output
from client_wrapper import ClientWrapper
from lib import init_working_dir # Import from lib.py
from version import get_version_tag

log = logging.getLogger(__name__)


async def fetch_release_hash(hash_url, *, expected_version=None):
    """
    Fetch the hash from the release URL.

    Handles both plain text hash responses and JSON responses containing a 'hash' key.
    """
    client = ClientWrapper()
    response = await client.get(hash_url)
    response.raise_for_status()
    content = response.content.decode().strip()
    release_hash = None

    try:
        data = json.loads(content)
        if isinstance(data, dict):
            # If we expect a specific version, check it first
            if expected_version and "version" in data:
                deployed_version = str(data["version"]).strip()
                if deployed_version != expected_version:
                    raise Exception(
                        f"Version mismatch at {hash_url}: Expected '{expected_version}', but found '{deployed_version}'"
                    )
            # If version matches (or wasn't checked), get the hash
            if "hash" in data:
                release_hash = str(data["hash"]).strip()
    except json.JSONDecodeError:
        # Content is not JSON, treat it as a plain hash
        pass

    if release_hash is None:
        # Fallback: Treat the entire content as the hash if JSON parsing failed
        # or the 'hash' key wasn't found.
        release_hash = content

    if len(release_hash) != 40:
        # Validate the final hash string
        raise Exception(
            f"Expected a 40-character release hash from {hash_url} but got: '{release_hash}'"
        )
    return release_hash


async def wait_for_deploy(
    *,
    github_access_token,
    repo_url,
    hash_url,
    watch_branch,
    expected_version,
    timeout_seconds=60 * 60,
):
    """
    Wait until server is finished with the deploy

    Args:
        github_access_token (str): A github access token
        repo_url (str): The repository URL which has the latest commit hash to check
        hash_url (str): The deployment URL which has the commit of the deployed app
        watch_branch (str): The branch in the repository which has the latest commit
        expected_version (str or None): The version string expected to be found at the hash_url, or None to skip version check.
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

    if expected_version:
        log.info(f"Expecting version '{expected_version}' for hash {latest_hash[:7]}")
    else:
        log.info(f"No specific version expected for hash {latest_hash[:7]}. Proceeding without version check.")

    while True:
        try:
            current_hash = await fetch_release_hash(hash_url, expected_version=expected_version)
            if current_hash == latest_hash:
                log.info(f"Hash {latest_hash[:7]} confirmed at {hash_url}")
                break # Hashes match, deploy successful
            else:
                log.info(f"Waiting for hash {latest_hash[:7]} at {hash_url}, currently {current_hash[:7]}")
        except Exception as e: # pylint: disable=broad-except
            log.error(f"Error checking deploy status at {hash_url}: {e}")
            # Optionally, decide if specific errors should stop the wait

        if (time.time() - start_time) > timeout_seconds:
            log.error(f"Timeout waiting for hash {latest_hash[:7]} at {hash_url}")
            return False # Timeout reached
        await asyncio.sleep(30)

    return True
