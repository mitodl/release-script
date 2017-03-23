#!/usr/bin/env python3
import argparse
import asyncio
from datetime import (
    datetime,
    timedelta,
)
import requests
import time
import sys


def parse_checkmarks(body):
    """
    Parse PR message with checkboxes

    Args:
        body (str): The text of the pull request

    Returns:
        list of dict:
            A list of commits with a dict like:
                {
                    "checked": whether the author checked off their box
                    "author_name": The author's name
                    "title": The title of the commit
                }
    """
    commits = []
    current_name = None

    for line in body.split("\n"):
        if line.startswith("## "):
            current_name = line[3:].strip()
        elif line.startswith("  - ["):
            checked = False
            if line.startswith("  - [x]"):
                checked = True
            start = line.find("]")
            end = line.rfind("([")
            if start != -1 and end != -1:
                title = line[start:end].strip()

                commits.append({
                    "checked": checked,
                    "title": title,
                    "author_name": current_name,
                })
    return commits


def get_release_pr(org, repo, version):
    """
    Look up the release pull request

    Args:
        org (str): The github organization (eg mitodl)
        repo (str): The github repository (eg micromasters)
        version (str): A version string used to match the PR title

    Returns:
        str: The text of the pull request
    """
    pulls = requests.get("https://api.github.com/repos/{org}/{repo}/pulls".format(
        org=org,
        repo=repo,
    )).json()
    release_pulls = [pull for pull in pulls if pull['title'] == "Release {}".format(version)]
    if len(release_pulls) == 0:
        raise Exception("No release pull request on server")
    elif len(release_pulls) > 1:
        raise Exception("Too many release pull requests")

    return release_pulls[0]['body']


def get_unchecked_authors(org, repo, version):
    """
    Returns list of authors who have not yet checked off their checkboxes

    Args:
        org (str): The github organization (eg mitodl)
        repo (str): The github repository (eg micromasters)
        version (str): A version string used to match the PR title
    """
    body = get_release_pr(org, repo, version)
    commits = parse_checkmarks(body)
    return {commit['author_name'] for commit in commits if not commit['checked']}


async def wait_for_checkboxes(org, repo, version):
    """
    Wait for checkboxes, polling every 60 seconds

    Args:
        org (str): The github organization (eg mitodl)
        repo (str): The github repository (eg micromasters)
        version (str): A version string used to match the PR title
    """
    print("Waiting for checkboxes to be checked. Polling every 60 seconds...")
    while True:
        unchecked_authors = get_unchecked_authors(org, repo, version)
        if len(unchecked_authors) == 0:
            break

        await asyncio.sleep(60)
        print(".", end='')
        sys.stdout.flush()
    print("All checkboxes are now checked")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("repo")
    parser.add_argument("version")
    parser.add_argument("--org", default="mitodl")
    parser.add_argument("--wait", default=False, action='store_true')
    args = parser.parse_args()

    if args.wait:
        loop = asyncio.get_event_loop()
        loop.run_until_complete(wait_for_checkboxes(args.org, args.repo, args.version))
        loop.close()
    else:
        unchecked_authors = get_unchecked_authors(args.org, args.repo, args.version)
        if unchecked_authors:
            print("Unchecked authors: {}".format(", ".join(unchecked_authors)))
            sys.exit(1)

if __name__ == "__main__":
    main()
