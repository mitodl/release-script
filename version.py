"""
Checks the deployed version of the app
"""
from subprocess import check_output

from release import init_working_dir


def get_version_tag(github_access_token, repo_url, commit_hash):
    """Determines the version tag (or None) of the given commit hash"""
    with init_working_dir(github_access_token, repo_url):
        return check_output(["git", "tag", "-l", "--points-at", commit_hash]).decode().strip()
