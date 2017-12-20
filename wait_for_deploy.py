"""Wait for hash on server to match with deployed code"""
import argparse
import asyncio
import os
from subprocess import check_output

import requests

from release import (
    init_working_dir,
    validate_dependencies,
)


def fetch_release_hash(hash_url):
    """Fetch the hash from the release"""
    response = requests.get(hash_url)
    response.raise_for_status()
    release_hash = response.content.decode().strip()
    if len(release_hash) != 40:
        raise Exception("Expected release hash from {hash_url} but got: {hash}".format(
            hash_url=hash_url,
            hash=release_hash,
        ))
    return release_hash


async def wait_for_deploy(github_access_token, repo_url, hash_url, watch_branch):
    """Wait until server is finished with the deploy"""
    validate_dependencies()

    with init_working_dir(github_access_token, repo_url):
        latest_hash = check_output(["git", "rev-parse", "origin/{}".format(watch_branch)]).decode().strip()
    print("Polling {url} for {hash}...".format(url=hash_url, hash=latest_hash))
    while fetch_release_hash(hash_url) != latest_hash:
        await asyncio.sleep(30)
        print(".", end='')
    print("Hashes match, deployment was successful!")


def main():
    """
    Deploy a release to production
    """
    try:
        github_access_token = os.environ['GITHUB_ACCESS_TOKEN']
    except KeyError:
        raise Exception("Missing GITHUB_ACCESS_TOKEN")

    parser = argparse.ArgumentParser()
    parser.add_argument("repo_url")
    parser.add_argument(
        "hash_url",
        help="a hash URL containing the deployed git hash version. "
             "For example, for micromasters https://micromasters-rc.herokuapp.com/static/hash.txt"
    )
    parser.add_argument("watch_branch", help="a branch whose latest commit will match the deployed hash")
    args = parser.parse_args()

    if not args.hash_url.startswith("https"):
        raise Exception("You must specify a hash URL to compare the deployed git hash version")

    loop = asyncio.get_event_loop()
    loop.run_until_complete(
        wait_for_deploy(
            github_access_token=github_access_token,
            repo_url=args.repo_url,
            hash_url=args.hash_url,
            watch_branch=args.watch_branch,
        )
    )
    loop.close()


if __name__ == "__main__":
    main()
