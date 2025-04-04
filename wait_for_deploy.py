"""Wait for hash on server to match with deployed code"""

import asyncio
import json
import logging
import time

from async_subprocess import check_output
from client_wrapper import ClientWrapper
from lib import init_working_dir  # Import from lib.py

log = logging.getLogger(__name__)


async def fetch_release_hash(hash_url, *, expected_version=None):
    """
    Fetch the deployment signal (version or hash) from the release URL, requiring an expected version.

    - If JSON response contains a 'version' key:
        - Checks if it matches `expected_version`. Raises Exception on mismatch.
        - Returns the matching version string as the signal.
    - If JSON response does NOT contain 'version' key OR content is not JSON:
        - Looks for 'hash' key in JSON (if applicable). Returns valid 40-char hash if found.
        - If no 'hash' key or not JSON, treats raw content as hash. Returns if valid 40-char hash.
    - Raises exceptions for version mismatches, invalid hash formats, or if no valid signal is found.

    Args:
        hash_url (str): The URL to fetch the signal from.
        expected_version (str): The version string that is expected. This is mandatory.

    Returns:
        str: The validated deployment signal (either the matching version or a 40-char hash).

    Raises:
        Exception: If version mismatch occurs, hash format is invalid, or no valid signal is found.
    """
    if not expected_version:
        # Ensure expected_version is always provided, as per new requirement.
        raise ValueError("expected_version must be provided to fetch_release_hash")

    client = ClientWrapper()
    response = await client.get(hash_url)
    response.raise_for_status()
    content = response.content.decode().strip()
    data = None
    is_json = False

    try:
        data = json.loads(content)
        if isinstance(data, dict):
            is_json = True
            # --- Version Check ---
            if "version" in data and expected_version is not None:
                deployed_version = str(data["version"]).strip()
                # Since expected_version is mandatory, we always compare if 'version' key exists.
                if deployed_version == expected_version:
                    log.debug(
                        "Found matching version '%s' at %s", deployed_version, hash_url
                    )
                    return deployed_version  # Success: Found expected version
                else:
                    # Version mismatch is always a failure condition if 'version' key is present.
                    raise Exception(
                        f"Version mismatch at {hash_url}: Expected '{expected_version}', but found '{deployed_version}'"
                    )
                # If version key was present, we either returned or raised. We don't proceed to hash check.

            # --- Hash Check (only if 'version' key was NOT found in JSON) ---
            elif "hash" in data:
                release_hash = str(data["hash"]).strip()
                if len(release_hash) == 40:
                    log.debug(
                        "Found hash '%s' in JSON at %s", release_hash[:7], hash_url
                    )
                    return release_hash  # Success: Found hash signal in JSON
                else:
                    # Invalid hash format in JSON is an error
                    raise Exception(
                        f"Invalid hash length ({len(release_hash)}) found in JSON 'hash' key at {hash_url}: '{release_hash}'"
                    )

    except json.JSONDecodeError:
        # Content is not JSON, proceed to treat raw content as hash/signal
        log.debug("Content at %s is not JSON, treating as raw signal.", hash_url)

    # --- Raw Content Check (if not JSON or relevant keys missing/invalid in JSON) ---
    # At this point, we haven't returned a version or a valid JSON hash.
    # Treat the raw content as the signal. It should be a hash.
    release_signal = content
    if len(release_signal) == 40:
        log.debug(
            "Using raw content as hash signal '%s' from %s",
            release_signal[:7],
            hash_url,
        )
        return release_signal  # Success: Found hash signal in raw content
    else:
        # If we got here, the content is not valid JSON with a 'version' key,
        # not valid JSON with a 'hash' key, and not a 40-char raw hash.
        # This is an error condition. Since expected_version is mandatory, the error
        # message reflects that we expected that version but didn't find a valid signal.
        error_message = f"Expected version '{expected_version}' but found invalid signal at {hash_url}. Content: '{release_signal}'"

        # Add context if it was JSON but lacked valid keys
        if is_json:
            error_message += (
                f" (Content was JSON but lacked valid 'version' or 'hash' key: {data})"
            )

        raise Exception(error_message)


async def wait_for_deploy(
    *,
    github_access_token,
    repo_url,
    hash_url,
    watch_branch,
    expected_version,  # Made mandatory
    timeout_seconds=60 * 60,
):  # pylint: disable=too-many-arguments
    """
    Wait until server is finished with the deploy by checking for the expected version.

    Args:
        github_access_token (str): A github access token
        repo_url (str): The repository URL (used only to get the working dir context).
        hash_url (str): The deployment URL which should contain the deployment signal (version or hash).
        watch_branch (str): The branch in the repository (used only to get the latest hash for logging).
        expected_version (str): The version string expected to be found at the hash_url. This is mandatory.
        timeout_seconds (int): The number of seconds to wait before timing out the deploy.

    Returns:
        bool:
            True if the hashes matched, False if the check timed out
    """
    start_time = time.time()

    async with init_working_dir(github_access_token, repo_url) as working_dir:
        output = await check_output(
            ["git", "rev-parse", f"origin/{watch_branch}"], cwd=working_dir
        )
        latest_hash = output.decode().strip()  # Keep for logging context

    # expected_version is now mandatory
    release_signal = expected_version
    log.info(
        "Expecting version '%s' (commit: %s) at %s",
        expected_version,
        latest_hash[:7],
        hash_url,
    )

    while (
        await fetch_release_hash(hash_url, expected_version=expected_version)
        != release_signal  # We always compare against expected_version now
    ):
        if (time.time() - start_time) > timeout_seconds:
            log.info("Timeout waiting for version %s at %s", release_signal, hash_url)
            return False  # Timeout reached
        await asyncio.sleep(30)

    return True
