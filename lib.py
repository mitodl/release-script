"""Shared functions for release script Python files"""
import asyncio
from collections import namedtuple
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
import re
import sys

from dateutil.parser import parse

from exception import ReleaseException
from github import (
    get_pull_request,
    get_org_and_repo,
)


ReleasePR = namedtuple("ReleasePR", ['version', 'url', 'body'])


VERSION_RE = r'\d+\.\d+\.\d+'


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


def get_release_pr(github_access_token, org, repo):
    """
    Look up the pull request information for a release, or return None if it doesn't exist

    Args:
        github_access_token (str): The github access token
        org (str): The github organization (eg mitodl)
        repo (str): The github repository (eg micromasters)

    Returns:
        ReleasePR: The information about the release pull request, or None if there is no release PR in progress
    """
    pr = get_pull_request(github_access_token, org, repo, 'release-candidate')
    if pr is None:
        return None

    title = pr['title']
    match = re.match(r'^Release (?P<version>\d+\.\d+\.\d+)$', title)
    if not match:
        raise ReleaseException("Release PR title has an unexpected format")
    version = match.group('version')

    return ReleasePR(
        version=version,
        body=pr['body'],
        url=pr['html_url'],
    )


def get_unchecked_authors(github_access_token, org, repo):
    """
    Returns list of authors who have not yet checked off their checkboxes

    Args:
        github_access_token (str): The github access token
        org (str): The github organization (eg mitodl)
        repo (str): The github repository (eg micromasters)
    """
    release_pr = get_release_pr(github_access_token, org, repo)
    if not release_pr:
        raise ReleaseException("No release PR found")
    body = release_pr.body
    commits = parse_checkmarks(body)
    return {commit['author_name'] for commit in commits if not commit['checked']}


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
    return datetime(
        year=next_weekday.year,
        month=next_weekday.month,
        day=next_weekday.day,
        hour=10,
        tzinfo=now.tzinfo,
    )


def reformatted_full_name(full_name):
    """
    Make the full name lowercase and split it so we can more easily calculate its similarity

    Args:
        full_name (str): The user's full name

    Returns:
        str: The name in lowercase, removing the middle names
    """
    pieces = full_name.lower().split()
    if len(pieces) >= 2:
        return "{} {}".format(pieces[0], pieces[-1])
    elif len(pieces) == 1:
        return pieces[0]
    else:
        return ''


def format_user_id(user_id):
    """
    Format user id so Slack tags it

    Args:
        user_id (str): A slack user id

    Returns:
        str: A user id in a Slack tag
    """
    return "<@{id}>".format(id=user_id)


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
        return format_user_id(matched_user['id'])
    else:
        return author_name


async def wait_for_checkboxes(github_access_token, org, repo):
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
            unchecked_authors = get_unchecked_authors(github_access_token, org, repo)
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


def now_in_utc():
    """
    Returns:
        Returns current datetime in UTC
    """
    return datetime.now(tz=timezone.utc)


def url_with_access_token(github_access_token, repo_url):
    """
    Inserts the access token into the URL

    Returns:
        str: The URL formatted with an access token
    """
    org, repo = get_org_and_repo(repo_url)
    return "https://{token}@github.com/{org}/{repo}.git".format(
        token=github_access_token,
        org=org,
        repo=repo,
    )


def parse_date(date_string):
    """
    Parse a string into a date object

    Args:
        date_string (str): A date string

    Returns:
        date: A date object
    """
    return parse(date_string).date()
