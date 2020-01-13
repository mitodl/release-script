"""
Checks the deployed version of the app
"""
from async_subprocess import check_output

from release import init_working_dir


async def get_version_tag(*, github_access_token, repo_url, commit_hash):
    """Determines the version tag (or None) of the given commit hash"""
    async with init_working_dir(github_access_token, repo_url) as working_dir:
        output = await check_output(
            ["git", "tag", "-l", "--points-at", commit_hash],
            cwd=working_dir
        )
        return output.decode().strip()
