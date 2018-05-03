#!/usr/bin/env python3
"""Wait for all checkboxes to get checked off"""
import argparse
import asyncio
import os
import sys

from lib import get_unchecked_authors


async def wait_for_checkboxes(*, github_access_token, org, repo):
    """
    Wait for checkboxes, polling every 60 seconds

    Args:
        github_access_token (str): The github access token
        org (str): The github organization (eg mitodl)
        repo (str): The github repository (eg micromasters)
    """
    print("Waiting for checkboxes to be checked. Polling every 60 seconds...")
    error_count = 0
    while True:
        try:
            unchecked_authors = get_unchecked_authors(
                github_access_token=github_access_token,
                org=org,
                repo=repo,
            )
            if not unchecked_authors:
                break

        except Exception as exception:  # pylint: disable=broad-except
            sys.stderr.write("Error: {}".format(exception))
            error_count += 1
            if error_count >= 5:
                raise

        await asyncio.sleep(60)
        print(".", end='')
        sys.stdout.flush()
    print("All checkboxes are now checked")


def main():
    """Wait for all checkboxes to get checked off"""
    try:
        github_access_token = os.environ['GITHUB_ACCESS_TOKEN']
    except KeyError:
        raise Exception("Missing GITHUB_ACCESS_TOKEN")

    parser = argparse.ArgumentParser()
    parser.add_argument("repo")
    parser.add_argument("--org", default="mitodl")
    args = parser.parse_args()

    if "." in args.repo or "/" in args.repo:
        raise Exception("repo is just the repo name, not a URL or directory (ie 'micromasters')")

    loop = asyncio.get_event_loop()
    loop.run_until_complete(wait_for_checkboxes(
        github_access_token=github_access_token,
        org=args.org,
        repo=args.repo,
    ))
    loop.close()


if __name__ == "__main__":
    main()
