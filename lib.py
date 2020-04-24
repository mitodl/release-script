"""Shared functions for release script Python files"""
from collections import namedtuple
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
import json
import os
import re
from tempfile import TemporaryDirectory

from dateutil.parser import parse

from async_subprocess import call, check_call, check_output
from constants import SCRIPT_DIR, WEB_APPLICATION_TYPE
from exception import ReleaseException
from github import (
    get_pull_request,
    get_org_and_repo,
)
from repo_info import RepoInfo


ReleasePR = namedtuple("ReleasePR", ['version', 'url', 'body'])


VERSION_RE = r'\d+\.\d+\.\d+'

COMMIT_HASH_RE = r'^[a-z0-9]+$'


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


async def get_release_pr(*, github_access_token, org, repo):
    """
    Look up the pull request information for a release, or return None if it doesn't exist

    Args:
        github_access_token (str): The github access token
        org (str): The github organization (eg mitodl)
        repo (str): The github repository (eg micromasters)

    Returns:
        ReleasePR: The information about the release pull request, or None if there is no release PR in progress
    """
    pr = await get_pull_request(
        github_access_token=github_access_token,
        org=org,
        repo=repo,
        branch='release-candidate',
    )
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


def match_user(slack_users, author_name):
    """
    Do an exact match of author name to full name. If it matches, return a formatted Slack handle. Else return original
    full name.

    Args:
        slack_users (list of dict): A list of slack users from their API
        author_name (str): The commit author's full name

    Returns:
        str: The slack markup for the handle of that author.
             If one can't be found, the author's name is returned unaltered.
    """

    lower_author_name = reformatted_full_name(author_name)

    def matches_user(slack_user):
        """Return true if there's a slack match"""
        real_name = slack_user['profile']['real_name_normalized']
        lower_name = reformatted_full_name(real_name)

        return lower_name == lower_author_name

    for user in slack_users:
        if matches_user(user):
            return format_user_id(user['id'])

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


@asynccontextmanager
async def virtualenv(python_interpreter, env):
    """
    Create a virtualenv and work within its context
    """
    with TemporaryDirectory() as virtualenv_dir:
        await check_call(["virtualenv", virtualenv_dir, "-p", python_interpreter], env=env, cwd=virtualenv_dir)

        # Figure out what environment variables we need to set
        output_bytes = await check_output(
            ". {}; env".format(os.path.join(virtualenv_dir, "bin", "activate")),
            shell=True,
            cwd=virtualenv_dir,
        )
        output = output_bytes.decode()
        yield virtualenv_dir, dict(line.split("=", 1) for line in output.splitlines())


async def upload_to_pypi(*, repo_info, testing, version, github_access_token):  # pylint: disable=too-many-locals
    """
    Upload a version of a project to PYPI

    Args:
        repo_info (RepoInfo): The repository info
        testing (bool): If true upload to the testing server, else upload to production
        version (str): The version of the project to upload
        github_access_token (str): The github access token
    """
    branch = "v{}".format(version)
    # Set up environment variables for uploading to pypi or pypitest
    twine_env = {
        'TWINE_USERNAME': os.environ['PYPITEST_USERNAME'] if testing else os.environ['PYPI_USERNAME'],
        'TWINE_PASSWORD': os.environ['PYPITEST_PASSWORD'] if testing else os.environ['PYPI_PASSWORD'],
    }

    # This is the python interpreter to use for creating the source distribution or wheel
    # In particular if a wheel is specific to one version of python we need to use that interpreter to create it.
    python = "python3" if repo_info.python3 else "python2"

    async with init_working_dir(github_access_token, repo_info.repo_url, branch=branch) as working_dir:
        async with virtualenv("python3", None) as (_, outer_environ):
            # Heroku has both Python 2 and 3 installed but the system libraries aren't configured for our use,
            # so make a virtualenv.
            async with virtualenv(python, outer_environ) as (virtualenv_dir, environ):
                # Use the virtualenv binaries to act within that environment
                python_path = os.path.join(virtualenv_dir, "bin", "python")
                pip_path = os.path.join(virtualenv_dir, "bin", "pip")
                twine_path = os.path.join(virtualenv_dir, "bin", "twine")

                # Install dependencies. wheel is needed for Python 2. twine uploads the package.
                await check_call([pip_path, "install", "wheel", "twine"], env=environ, cwd=working_dir)

                # Create source distribution and wheel.
                await call([python_path, "setup.py", "sdist"], env=environ, cwd=working_dir)
                universal = ["--universal"] if repo_info.python2 and repo_info.python3 else []
                build_wheel_args = [python_path, "setup.py", "bdist_wheel", *universal]
                await call(build_wheel_args, env=environ, cwd=working_dir)
                dist_files = os.listdir(os.path.join(working_dir, "dist"))
                if len(dist_files) != 2:
                    raise Exception("Expected to find one tarball and one wheel in directory")
                dist_paths = [os.path.join("dist", name) for name in dist_files]

                # Upload to pypi
                testing_args = ["--repository-url", "https://test.pypi.org/legacy/"] if testing else []
                await check_call(
                    [twine_path, "upload", *testing_args, *dist_paths],
                    env={
                        **environ,
                        **twine_env,
                    }, cwd=working_dir
                )


def load_repos_info(channel_lookup):
    """
    Load repo information from JSON and looks up channel ids for each repo

    Args:
        channel_lookup (dict): Map of channel names to channel ids

    Returns:
        list of RepoInfo: Information about the repositories
    """
    with open(os.path.join(SCRIPT_DIR, "repos_info.json")) as f:
        repos_info = json.load(f)
        return [
            RepoInfo(
                name=repo_info['name'],
                repo_url=repo_info.get('repo_url'),
                rc_hash_url=(
                    repo_info['rc_hash_url'] if repo_info.get('project_type') == WEB_APPLICATION_TYPE else None
                ),
                prod_hash_url=(
                    repo_info['prod_hash_url'] if repo_info.get('project_type') == WEB_APPLICATION_TYPE else None
                ),
                channel_id=channel_lookup[repo_info['channel_name']],
                project_type=repo_info.get('project_type'),
                python2=repo_info.get('python2'),
                python3=repo_info.get('python3'),
                announcements=repo_info.get('announcements'),
            ) for repo_info in repos_info['repos']
        ]


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


@asynccontextmanager
async def init_working_dir(github_access_token, repo_url, *, branch=None):
    """Create a new directory with an empty git repo"""
    if branch is None:
        branch = 'master'

    url = url_with_access_token(github_access_token, repo_url)
    with TemporaryDirectory() as directory:
        # from http://stackoverflow.com/questions/2411031/how-do-i-clone-into-a-non-empty-directory
        await check_call(["git", "init", "-q"], cwd=directory)
        await check_call(["git", "config", "push.default", "simple"], cwd=directory)
        await check_call(["git", "remote", "add", "origin", url], cwd=directory)
        await check_call(["git", "fetch", "--tags", "-q"], cwd=directory)
        await check_call(["git", "checkout", branch, "-q"], cwd=directory)

        yield directory
