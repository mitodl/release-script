#!/usr/bin/env python3
import argparse
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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("repo")
    parser.add_argument("version")
    parser.add_argument("--org", default="mitodl")
    parser.add_argument("--wait", default=False, action='store_true')
    args = parser.parse_args()

    if args.wait:
        print("Waiting for checkboxes to be checked. Polling every 60 seconds...")
        while True:
            body = get_release_pr(args.org, args.repo, args.version)
            commits = parse_checkmarks(body)
            all_checked = all(commit['checked'] for commit in commits)
            if all_checked:
                break

            time.sleep(60)
            print(".", end='')
            sys.stdout.flush()
        print("All checkboxes are now checked")
    else:
        body = get_release_pr(args.org, args.repo, args.version)
        commits = parse_checkmarks(body)
        unchecked_authors = {commit['author_name'] for commit in commits if not commit['checked']}
        if unchecked_authors:
            print("Unchecked authors: {}".format(", ".join(unchecked_authors)))
            sys.exit(1)

if __name__ == "__main__":
    main()
