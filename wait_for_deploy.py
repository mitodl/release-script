"""Wait for hash on server to match with deployed code"""
import argparse
import requests
from subprocess import check_output
import time

from release import (
    init_working_dir,
    validate_dependencies,
)


def fetch_release_hash(hash_url):
    """Fetch the hash from the release"""
    release_hash = requests.get(hash_url).content.decode().strip()
    if len(release_hash) != 40:
        raise Exception("Expected release hash from {hash_url} but got: {hash}".format(
            hash_url=hash_url,
            hash=release_hash,
        ))
    return release_hash


def wait_for_deploy(repo_url, hash_url, watch_branch):
    """Wait until server is finished with the deploy"""
    validate_dependencies()

    with init_working_dir(repo_url):
        latest_hash = check_output(["git", "rev-parse", watch_branch]).decode().strip()
    print("Looking for {}...".format(latest_hash))
    while fetch_release_hash(hash_url) != latest_hash:
        time.sleep(30)
        print(".", end='')
    print("Hashes match, deployment was successful!")


def main():
    """
    Deploy a release to production
    """
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

    wait_for_deploy(repo_url=args.repo_url, hash_url=args.hash_url, watch_branch=args.watch_branch)


if __name__ == "__main__":
    main()
