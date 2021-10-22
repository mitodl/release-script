"""Shared functions for release script Python files"""
from collections import namedtuple
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from difflib import SequenceMatcher
import json
import os
import re
from tempfile import TemporaryDirectory
from urllib.parse import urlparse, urlunparse

from dateutil.parser import parse

from async_subprocess import check_call, check_output
from constants import (
    SCRIPT_DIR,
    LIBRARY_TYPE,
    WEB_APPLICATION_TYPE,
    VALID_PACKAGING_TOOL_TYPES,
    VALID_WEB_APPLICATION_TYPES,
)
from exception import ReleaseException
from github import (
    get_pull_request,
    get_org_and_repo,
)
from repo_info import RepoInfo


ReleasePR = namedtuple("ReleasePR", ["version", "url", "body", "number", "open"])


VERSION_RE = r"\d+\.\d+\.\d+"

COMMIT_HASH_RE = r"^[a-z0-9]+$"


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
                title = line[start + 1 : end].strip()

                commits.append(
                    {
                        "checked": checked,
                        "title": title,
                        "author_name": current_name,
                    }
                )
    return commits


async def get_release_pr(*, github_access_token, org, repo, all_prs=False):
    """
    Look up the pull request information for the most recently created release, or return None if it doesn't exist

    Args:
        github_access_token (str): The github access token
        org (str): The github organization (eg mitodl)
        repo (str): The github repository (eg micromasters)
        all_prs (bool):
            If True, look through open and closed PRs. The most recent release PR will be returned.
            If False, look only through open PRs.

    Returns:
        ReleasePR: The information about the release pull request, or None if there is no release PR in progress
    """
    pr = await get_pull_request(
        github_access_token=github_access_token,
        org=org,
        repo=repo,
        branch="release-candidate",
        all_prs=all_prs,
    )
    if pr is None:
        return None

    title = pr["title"]
    match = re.match(r"^Release (?P<version>\d+\.\d+\.\d+)$", title)
    if not match:
        return None
    version = match.group("version")

    return ReleasePR(
        version=version,
        number=pr["number"],
        body=pr["body"],
        url=pr["html_url"],
        open=pr["state"] == "open",
    )


async def get_unchecked_authors(*, github_access_token, org, repo):
    """
    Returns list of authors who have not yet checked off their checkboxes

    Args:
        github_access_token (str): The github access token
        org (str): The github organization (eg mitodl)
        repo (str): The github repository (eg micromasters)

    Returns:
        set[str]: A set of github usernames
    """
    release_pr = await get_release_pr(
        github_access_token=github_access_token,
        org=org,
        repo=repo,
    )
    if not release_pr:
        raise ReleaseException("No release PR found")
    body = release_pr.body
    commits = parse_checkmarks(body)
    return {commit["author_name"] for commit in commits if not commit["checked"]}


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
        return f"{pieces[0]} {pieces[-1]}"
    elif len(pieces) == 1:
        return pieces[0]
    return ""


def format_user_id(user_id):
    """
    Format user id so Slack tags it

    Args:
        user_id (str): A slack user id

    Returns:
        str: A user id in a Slack tag
    """
    return f"<@{user_id}>"


def match_user(slack_users, author_name, threshold=0.8):
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
        real_name = slack_user["profile"]["real_name"]
        lower_name = reformatted_full_name(real_name)

        ratio = SequenceMatcher(a=lower_author_name, b=lower_name).ratio()
        if ratio >= threshold:
            return ratio

        if " " not in lower_author_name:
            lower_name = lower_name.split()[0]
        ratio = SequenceMatcher(a=lower_author_name, b=lower_name).ratio()
        if ratio >= threshold:
            return ratio

        return 0

    slack_matches = [
        (slack_user, match_for_user(slack_user)) for slack_user in slack_users
    ]
    slack_matches = [
        (slack_user, match)
        for (slack_user, match) in slack_matches
        if match >= threshold
    ]

    if slack_matches:
        matched_user = max(slack_matches, key=lambda pair: pair[1])[0]
        return format_user_id(matched_user["id"])
    else:
        return author_name


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
    return f"https://{github_access_token}@github.com/{org}/{repo}.git"


def parse_date(date_string):
    """
    Parse a string into a date object

    Args:
        date_string (str): A date string

    Returns:
        date: A date object
    """
    return parse(date_string).date()


def parse_text_matching_options(valid_options):
    """
    Create a function to validate a string against choices

    Args:
        valid_options (list of str): Valid options for the text
    """

    def validate(text):
        """
        Verify that the string matches one of the options, or else raise an exception

        Args:
            text (str): Some text
        """
        if text not in valid_options:
            raise Exception(
                f"Unexpected option {text}. Valid options: {', '.join(valid_options)}"
            )
        return text

    return validate


@asynccontextmanager
async def virtualenv(python_interpreter, env):
    """
    Create a virtualenv and work within its context
    """
    with TemporaryDirectory() as virtualenv_dir:
        await check_call(
            ["virtualenv", virtualenv_dir, "-p", python_interpreter],
            env=env,
            cwd=virtualenv_dir,
        )

        # Figure out what environment variables we need to set
        output_bytes = await check_output(
            f". {os.path.join(virtualenv_dir, 'bin', 'activate')}; env",
            shell=True,
            cwd=virtualenv_dir,
        )
        output = output_bytes.decode()
        yield virtualenv_dir, dict(
            line.split("=", 1) for line in output.splitlines() if "=" in line
        )


def load_repos_info(channel_lookup):
    """
    Load repo information from JSON and looks up channel ids for each repo

    Args:
        channel_lookup (dict): Map of channel names to channel ids

    Returns:
        list of RepoInfo: Information about the repositories
    """
    with open(os.path.join(SCRIPT_DIR, "repos_info.json"), "r", encoding="utf-8") as f:
        repos_info = json.load(f)

    infos = [
        RepoInfo(
            name=repo_info["name"],
            repo_url=repo_info["repo_url"],
            ci_hash_url=(
                repo_info["ci_hash_url"]
                if repo_info.get("project_type") == WEB_APPLICATION_TYPE
                else None
            ),
            rc_hash_url=(
                repo_info["rc_hash_url"]
                if repo_info.get("project_type") == WEB_APPLICATION_TYPE
                else None
            ),
            prod_hash_url=(
                repo_info["prod_hash_url"]
                if repo_info.get("project_type") == WEB_APPLICATION_TYPE
                else None
            ),
            channel_id=channel_lookup[repo_info["channel_name"]],
            project_type=repo_info.get("project_type"),
            web_application_type=repo_info.get("web_application_type"),
            packaging_tool=repo_info.get("packaging_tool"),
        )
        for repo_info in repos_info["repos"]
        if repo_info.get("repo_url")
    ]

    # some basic validation for sanity checking
    for info in infos:
        if info.project_type == WEB_APPLICATION_TYPE:
            if info.web_application_type not in VALID_WEB_APPLICATION_TYPES:
                raise Exception(
                    f"Unexpected web application type {info.web_application_type} for {info.name}"
                )
        elif info.project_type == LIBRARY_TYPE:
            if info.packaging_tool not in VALID_PACKAGING_TOOL_TYPES:
                raise Exception(
                    f"Unexpected packaging tool {info.packaging_tool} for {info.name}"
                )

    return infos


def next_versions(version):
    """
    Create the next minor and patch versions from existing version

    Args:
        version (str): A version string which is already validated

    Returns:
        (str, str): A new version with the minor version incremented, and the same with the patch version incremented
    """
    old_major, old_minor, patch_version = version.split(".")
    new_minor = f"{old_major}.{int(old_minor) + 1}.0"
    new_patch = f"{old_major}.{old_minor}.{int(patch_version) + 1}"
    return new_minor, new_patch


async def get_default_branch(repository_path):
    """
    Look up the default branch for a repository (usually master or main)

    Args:
        repository_path (str): The path of the repository
    """
    output = (
        await check_output(["git", "remote", "show", "origin"], cwd=repository_path)
    ).decode()
    head_branch_line = [line for line in output.splitlines() if "HEAD branch" in line]
    return head_branch_line[0].rsplit(": ", maxsplit=1)[1]


@asynccontextmanager
async def init_working_dir(github_access_token, repo_url, *, branch=None):
    """Create a new directory with an empty git repo"""
    url = url_with_access_token(github_access_token, repo_url)
    with TemporaryDirectory() as directory:
        # from http://stackoverflow.com/questions/2411031/how-do-i-clone-into-a-non-empty-directory
        await check_call(["git", "init", "-q"], cwd=directory)
        await check_call(["git", "config", "push.default", "simple"], cwd=directory)
        await check_call(["git", "remote", "add", "origin", url], cwd=directory)
        await check_call(["git", "fetch", "--tags", "-q"], cwd=directory)

        if branch is None:
            branch = await get_default_branch(directory)

        await check_call(["git", "checkout", branch, "-q"], cwd=directory)

        yield directory


def remove_path_from_url(url):
    """
    Remove everything after the path from the URL.

    Args:
        url (str): The URL

    Returns:
        str:
            The URL without a path.
            For example https://example:1234/a/path/?query=param#fragment would become
            https://example:1234/
    """
    parsed = urlparse(url)
    # The docs recommend _replace: https://docs.python.org/3/library/urllib.parse.html#urllib.parse.urlparse
    updated = parsed._replace(path="", query="", fragment="")
    return urlunparse(updated)
