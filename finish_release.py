"""Release script to finish the release"""
import os
import re
from datetime import datetime

from async_subprocess import (
    check_call,
    check_output,
)
from exception import VersionMismatchException
from lib import get_default_branch
from release import (
    init_working_dir,
    validate_dependencies,
)


async def merge_release_candidate(*, root):
    """Merge release-candidate into release"""
    await check_call(["git", "checkout", "release"], cwd=root)
    await check_call(["git", "merge", "release-candidate", "--no-edit"], cwd=root)
    await check_call(["git", "push"], cwd=root)


async def check_release_tag(version, *, root):
    """Check release version number"""
    await check_call(["git", "checkout", "release-candidate"], cwd=root)
    log_output = await check_output(["git", "log", "-1", "--pretty=%B"], cwd=root)
    commit_name = log_output.decode().strip()
    if commit_name != "Release {}".format(version):
        raise VersionMismatchException(
            "Commit name {commit_name} does not match tag number {version}".format(
                commit_name=commit_name,
                version=version,
            )
        )


async def tag_release(version, *, root):
    """Add git tag for release"""
    await check_call(
        ["git", "tag", "-a", "-m", "Release {}".format(version), "v{}".format(version)],
        cwd=root,
    )
    await check_call(["git", "push", "--follow-tags"], cwd=root)


async def set_release_date(version, timezone, *, root):
    """Sets the release date(s) in RELEASE.rst for any versions missing it"""
    release_filename = os.path.join(root, "RELEASE.rst")
    if not os.path.isfile(release_filename):
        return
    date_format = "%B %d, %Y"
    await check_call(["git", "fetch", "--tags"], cwd=root)
    await check_call(["git", "checkout", "release-candidate"], cwd=root)

    with open(release_filename, "r", encoding="utf-8") as f:
        existing_note_lines = f.readlines()

    with open(release_filename, "w", encoding="utf-8") as f:
        for line in existing_note_lines:
            if line.startswith("Version ") and "Released" not in line:
                version_match = re.search(r"[0-9\.]+", line)
                if version_match:
                    version_line = version_match.group(0)
                    if version_line == version:
                        localtime = datetime.now().strftime(date_format)
                    else:
                        version_output = await check_output(
                            [
                                "git",
                                "log",
                                "-1",
                                "--format=%ai",
                                "v{}".format(version_line),
                            ],
                            cwd=root,
                        )
                        version_date = version_output.rstrip()
                        localtime = (
                            datetime.strptime(
                                version_date.decode("utf-8"), "%Y-%m-%d %H:%M:%S %z"
                            )
                            .astimezone(timezone)
                            .strftime(date_format)
                        )
                    line = "Version {} (Released {})\n".format(version_line, localtime)
            f.write(line)

    await check_call(
        [
            "git",
            "commit",
            "-q",
            release_filename,
            "-m",
            "Release date for {}".format(version),
        ],
        cwd=root,
    )


async def merge_release(*, root):
    """Merge release to master"""
    default_branch = await get_default_branch(root)

    await check_call(["git", "checkout", "-q", default_branch], cwd=root)
    await check_call(["git", "pull"], cwd=root)
    await check_call(["git", "merge", "release", "--no-edit"], cwd=root)
    await check_call(["git", "push"], cwd=root)


async def finish_release(*, github_access_token, repo_info, version, timezone):
    """
    Merge release to master and deploy to production

    Args:
        github_access_token (str): Github access token
        repo_info (RepoInfo): The info of the project being released
        version (str): The new version of the release
        timezone (any): Some timezone object to set the proper release datetime string
    """

    await validate_dependencies()
    async with init_working_dir(github_access_token, repo_info.repo_url) as working_dir:
        await check_release_tag(version, root=working_dir)
        await set_release_date(version, timezone, root=working_dir)
        await merge_release_candidate(root=working_dir)
        await tag_release(version, root=working_dir)
        await merge_release(root=working_dir)
