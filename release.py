#!/usr/bin/env python3
"""Release script for ODL projects"""
import re
import os
from subprocess import CalledProcessError

from pkg_resources import parse_version

from async_subprocess import (
    call,
    check_call,
    check_output,
)
from constants import (
    GIT_RELEASE_NOTES_PATH,
    SCRIPT_DIR,
    YARN_PATH,
)
from exception import (
    DependencyException,
    ReleaseException,
)
from github import create_pr
from lib import (
    get_default_branch,
    init_working_dir,
)
from version import update_version


async def dependency_exists(command):
    """Returns true if a command exists on the system"""
    return await call(["which", command], cwd="/") == 0


async def validate_dependencies():
    """Error if a dependency is missing or invalid"""
    if not await dependency_exists("git"):
        raise DependencyException("Please install git https://git-scm.com/downloads")
    if not await dependency_exists("node"):
        raise DependencyException("Please install node.js https://nodejs.org/")
    if not await dependency_exists(
        GIT_RELEASE_NOTES_PATH
    ) or not await dependency_exists(YARN_PATH):
        raise DependencyException("Please run 'npm install' first")

    version_output = await check_output(["node", "--version"], cwd="/")
    version = version_output.decode()
    major_version = int(re.match(r"^v(\d+)\.", version).group(1))
    if major_version < 6:
        raise DependencyException("node.js must be version 6.x or higher")


async def any_new_commits(version, *, base_branch, root):
    """
    Return true if there are any new commits since a release

    Args:
        version (str): A version string
        base_branch (str): The branch to compare against
        root (str): The project root directory

    Returns:
        bool: True if there are new commits
    """
    output = await check_output(
        ["git", "rev-list", "--count", f"v{version}..{base_branch}", "--"], cwd=root
    )
    return int(output) != 0


async def create_release_notes(old_version, with_checkboxes, *, base_branch, root):
    """
    Returns the release note text for the commits made for this version

    Args:
        old_version (str): The starting version of the range of commits
        with_checkboxes (bool): If true, create the release notes with spaces for checkboxes
        base_branch (str): The base branch to compare against
        root (str): The project root directory

    Returns:
        str: The release notes
    """
    if with_checkboxes:
        filename = "release_notes.ejs"
    else:
        filename = "release_notes_rst.ejs"

    if not await any_new_commits(old_version, base_branch=base_branch, root=root):
        return "No new commits"

    output = await check_output(
        [
            GIT_RELEASE_NOTES_PATH,
            f"v{old_version}..{base_branch}",
            os.path.join(SCRIPT_DIR, "util", filename),
        ],
        cwd=root,
    )
    return "{}\n".format(output.decode().strip())


async def verify_new_commits(old_version, *, base_branch, root):
    """Check if there are new commits to release"""
    if not await any_new_commits(old_version, base_branch=base_branch, root=root):
        raise ReleaseException("No new commits to put in release")


async def update_release_notes(old_version, new_version, *, base_branch, root):
    """Updates RELEASE.rst and commits it"""
    release_notes = await create_release_notes(
        old_version, with_checkboxes=False, base_branch=base_branch, root=root
    )

    release_filename = os.path.join(root, "RELEASE.rst")
    try:
        with open(release_filename, "r", encoding="utf-8") as f:
            existing_note_lines = f.readlines()
    except FileNotFoundError:
        existing_note_lines = []

    with open(release_filename, "w", encoding="utf-8") as f:
        f.write("Release Notes\n")
        f.write("=============\n")
        f.write("\n")
        version_line = "Version {}".format(new_version)
        f.write("{}\n".format(version_line))
        f.write("{}\n".format("-" * len(version_line)))
        f.write("\n")
        f.write(release_notes)
        f.write("\n")

        # skip first four lines which contain the header we are replacing
        for old_line in existing_note_lines[3:]:
            f.write(old_line)

    await check_call(["git", "add", release_filename], cwd=root)
    await check_call(
        ["git", "commit", "-q", "--all", "--message", f"Release {new_version}"],
        cwd=root,
    )


async def build_release(*, root):
    """Deploy the release candidate"""
    await check_call(
        [
            "git",
            "push",
            "--force",
            "-q",
            "origin",
            "release-candidate:release-candidate",
        ],
        cwd=root,
    )


async def generate_release_pr(
    *, github_access_token, repo_url, old_version, new_version, base_branch, root
):
    """
    Make a release pull request for the deployed release-candidate branch

    Args:
        github_access_token (str): The github access token
        repo_url (str): URL for the repo
        old_version (str): The previous release version
        new_version (str): The version of the new release
        base_branch (str): The base branch to compare against
        root (str): The project root directory
    """
    await create_pr(
        github_access_token=github_access_token,
        repo_url=repo_url,
        title="Release {version}".format(version=new_version),
        body=await create_release_notes(
            old_version, with_checkboxes=True, base_branch=base_branch, root=root
        ),
        head="release-candidate",
        base="release",
    )


async def release(
    *, github_access_token, repo_info, new_version, branch=None, commit_hash=None
):
    """
    Run a release

    Args:
        github_access_token (str): The github access token
        repo_info (RepoInfo): RepoInfo for a repo
        new_version (str): The version of the new release
        branch (str): The branch to initialize the release from
        commit_hash (str): Commit hash to cherry pick in case of a hot fix
    """

    await validate_dependencies()
    async with init_working_dir(
        github_access_token, repo_info.repo_url, branch=branch
    ) as working_dir:
        default_branch = await get_default_branch(working_dir)
        await check_call(
            ["git", "checkout", "-qb", "release-candidate"], cwd=working_dir
        )
        if commit_hash:
            try:
                await check_call(["git", "cherry-pick", commit_hash], cwd=working_dir)
            except CalledProcessError as ex:
                raise ReleaseException(
                    f"Cherry pick failed for the given hash {commit_hash}"
                ) from ex
        old_version = await update_version(
            repo_info=repo_info,
            new_version=new_version,
            working_dir=working_dir,
            readonly=False,
        )
        if parse_version(old_version) >= parse_version(new_version):
            raise ReleaseException(
                "old version is {old} but the new version {new} is not newer".format(
                    old=old_version,
                    new=new_version,
                )
            )
        base_branch = "release-candidate" if commit_hash else default_branch
        await verify_new_commits(old_version, base_branch=base_branch, root=working_dir)
        await update_release_notes(
            old_version, new_version, base_branch=base_branch, root=working_dir
        )
        await build_release(root=working_dir)
        return await generate_release_pr(
            github_access_token=github_access_token,
            repo_url=repo_info.repo_url,
            old_version=old_version,
            new_version=new_version,
            base_branch=base_branch,
            root=working_dir,
        )
