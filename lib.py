"""Shared functions for release script Python files"""
import asyncio
from datetime import datetime, timedelta
from difflib import SequenceMatcher
import re
from subprocess import check_output
import sys

import requests

from exception import ReleaseException


def release_manager_name():
    """
    Get the release manager's name, or None if it can't be found

    Returns:
        str: The release manager's name, or None if it can't be found
    """
    lines = check_output(["git", "config", "--global", "-l"]).decode().split("\n")
    for line in lines:
        pieces = line.split("=")
        if len(pieces) == 2 and pieces[0] == 'user.name':
            return pieces[1]
    return None


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
                title = line[start + 1:end].strip()

                commits.append({
                    "checked": checked,
                    "title": title,
                    "author_name": current_name,
                })
    return commits


def get_release_pr(org, repo):
    """
    Look up the release pull request

    Args:
        org (str): The github organization (eg mitodl)
        repo (str): The github repository (eg micromasters)

    Returns:
        dict: The information about the release pull request
    """
    pulls = requests.get("https://api.github.com/repos/{org}/{repo}/pulls".format(
        org=org,
        repo=repo,
    )).json()
    release_pulls = [pull for pull in pulls if pull['head']['ref'] == "release-candidate"]
    if len(release_pulls) == 0:
        return None
    elif len(release_pulls) > 1:
        # Shouldn't happen since we look up by branch
        raise Exception("More than one release pull request open at the same time")

    return release_pulls[0]


def get_release_pr_url(release_pr):
    """
    Look up the URL for the release pull request

    Args:
        release_pr (dict): The release PR info

    Returns:
        str: The URL for the release
    """
    return release_pr['html_url']


def get_release_pr_version(release_pr):
    """
    Get the version for the release PR

    Args:
        release_pr (dict): The release PR info

    Returns:
        str: The version for the release
    """
    title = release_pr['title']
    match = re.match(r'^Release (?P<version>\d+\.\d+\.\d+)$', title)
    if not match:
        raise ReleaseException("Release PR title has an unexpected format")
    return match.group('version')


def get_unchecked_authors(org, repo):
    """
    Returns list of authors who have not yet checked off their checkboxes

    Args:
        org (str): The github organization (eg mitodl)
        repo (str): The github repository (eg micromasters)
    """
    release_pr = get_release_pr(org, repo)
    if not release_pr:
        raise ReleaseException("No release PR found")
    body = release_pr['body']
    commits = parse_checkmarks(body)
    return {commit['author_name'] for commit in commits if not commit['checked']}


def get_org_and_repo(repo_url):
    """
    Get the org and repo from a git repository cloned from github.

    Args:
        repo_url (str): The repository URL

    Returns:
        tuple: (org, repo)
    """
    org, repo = re.match(r'^.*github\.com[:|/](.+)/(.+)\.git', repo_url).groups()
    return org, repo


def next_workday_at_10(now):
    """
    Return time which is 10am the next day, or the following Monday if it lands on the weekend

    Args:
        now (datetime): The current time
    Returns:
        datetime:
            10am the next day or on the following Monday of a weekend
    """
    tomorrow = now + timedelta(days=1)
    next_weekday = tomorrow
    while next_weekday.isoweekday() > 5:
        # If Saturday or Sunday, go to next day
        next_weekday += timedelta(days=1)
    return datetime(next_weekday.year, next_weekday.month, next_weekday.day, 10)


def reformatted_full_name(full_name):
    """
    Make the full name lowercase and split it so we use
    """
    pieces = full_name.lower().split()
    if len(pieces) >= 2:
        return "{} {}".format(pieces[0], pieces[-1])
    elif len(pieces) == 1:
        return pieces[0]
    else:
        return ''


def match_user(slack_users, author_name, threshold=0.6):
    """
    Do a fuzzy match of author name to full name. If it matches, return a formatted Slack handle. Else return original
    full name.

    Args:
        slack_users (list of dict): A list of slack users from their API
        author_name (str): The commit author's full name
        threshold (float): All matches must be at least this high to pass.

    Returns:
        str: The slack markup for the handle of that author.
             If one can't be found, the author's name is returned unaltered.
    """

    lower_author_name = reformatted_full_name(author_name)

    def match_for_user(slack_user):
        """Get match ratio for slack user, or 0 if below threshold"""
        lower_name = reformatted_full_name(slack_user['profile']['real_name'])
        ratio = SequenceMatcher(a=lower_author_name, b=lower_name).ratio()
        if ratio >= threshold:
            return ratio
        else:
            return 0

    slack_matches = [(slack_user, match_for_user(slack_user)) for slack_user in slack_users]
    slack_matches = [(slack_user, match) for (slack_user, match) in slack_matches if match >= threshold]

    if len(slack_matches) > 0:
        matched_user = max(slack_matches, key=lambda pair: pair[1])[0]
        return "<@{id}>".format(id=matched_user['id'])
    else:
        return author_name


async def wait_for_checkboxes(org, repo):
    """
    Wait for checkboxes, polling every 60 seconds

    Args:
        org (str): The github organization (eg mitodl)
        repo (str): The github repository (eg micromasters)
    """
    print("Waiting for checkboxes to be checked. Polling every 60 seconds...")
    error_count = 0
    while True:
        try:
            unchecked_authors = get_unchecked_authors(org, repo)
            if len(unchecked_authors) == 0:
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
