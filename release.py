#!/usr/bin/env python3
"""Release script for ODL projects"""
import argparse
import asyncio
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
)
from exception import ReleaseException
from github import create_pr
from lib import (
    init_working_dir,
    VERSION_RE,
)


class DependencyException(Exception):
    """Error if dependency is missing"""


class UpdateVersionException(Exception):
    """Error if the old version is invalid or cannot be found, or if there's a duplicate version"""


class VersionMismatchException(Exception):
    """Error if the version is unexpected"""


async def dependency_exists(command):
    """Returns true if a command exists on the system"""
    return await call(["which", command], cwd="/") == 0


async def validate_dependencies():
    """Error if a dependency is missing or invalid"""
    if not await dependency_exists("git"):
        raise DependencyException("Please install git https://git-scm.com/downloads")
    if not await dependency_exists("node"):
        raise DependencyException("Please install node.js https://nodejs.org/")
    if not await dependency_exists(GIT_RELEASE_NOTES_PATH):
        raise DependencyException("Please run 'npm install' first")

    version_output = await check_output(["node", "--version"], cwd="/")
    version = version_output.decode()
    major_version = int(re.match(r"^v(\d+)\.", version).group(1))
    if major_version < 6:
        raise DependencyException("node.js must be version 6.x or higher")


def update_version_in_file(root, filename, new_version):
    """
    Update the version from the file and return the old version if it's found
    """
    version_filepath = os.path.join(root, filename)
    file_lines = []
    update_count = 0
    old_version = None
    with open(version_filepath) as f:
        for line in f.readlines():
            line = line.strip("\n")
            updated_line = line

            if filename == "settings.py":
                regex = r"^VERSION = .*(?P<version>{}).*$".format(VERSION_RE)
                match = re.match(regex, line)
                if match:
                    update_count += 1
                    old_version = match.group("version").strip()
                    updated_line = re.sub(
                        regex, 'VERSION = "{}"'.format(new_version), line
                    )
            elif filename == "__init__.py":
                regex = r"^__version__ ?=.*(?P<version>{}).*".format(VERSION_RE)
                match = re.match(regex, line)
                if match:
                    update_count += 1
                    old_version = match.group("version").strip()
                    updated_line = re.sub(
                        regex, "__version__ = '{}'".format(new_version), line
                    )
            elif filename == "setup.py":
                regex = r"\s*version=.*(?P<version>{}).*".format(VERSION_RE)
                match = re.match(regex, line)
                if match:
                    update_count += 1
                    old_version = match.group("version").strip()
                    updated_line = re.sub(
                        regex, "version='{}',".format(new_version), line
                    )

            file_lines.append("{}\n".format(updated_line))

    if update_count == 1:
        # Replace contents of file with updated version
        with open(version_filepath, "w") as f:
            for line in file_lines:
                f.write(line)
        return old_version
    elif update_count > 1:
        raise UpdateVersionException(
            "Expected only one version for {file} but found {count}".format(
                file=filename, count=update_count,
            )
        )

    # Unable to find old version for this file, but maybe there's another one
    return None


def update_version(new_version, *, working_dir):
    """Update the version from the project and return the old one, or raise an exception if none is found"""
    print("Updating version...")
    exclude_dirs = (
        ".cache",
        ".git",
        ".settings",
    )
    version_files = ("settings.py", "__init__.py", "setup.py")
    found_version_filename = None
    old_version = None
    for version_filename in version_files:
        for root, dirs, filenames in os.walk(working_dir, topdown=True):
            dirs[:] = [d for d in dirs if d not in exclude_dirs]
            if version_filename in filenames:
                version = update_version_in_file(root, version_filename, new_version)
                if version:
                    if not found_version_filename:
                        found_version_filename = version_filename
                        old_version = version
                    else:
                        raise UpdateVersionException(
                            "Found at least two files with updatable versions: {} and {}".format(
                                found_version_filename, version_filename,
                            )
                        )

    if not found_version_filename:
        raise UpdateVersionException("Unable to find previous version number")

    return old_version


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
        with open(release_filename) as f:
            existing_note_lines = f.readlines()
    except FileNotFoundError:
        existing_note_lines = []

    with open(release_filename, "w") as f:
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
    print("Building release...")
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
    print("Generating PR...")

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
    github_access_token, repo_url, new_version, branch=None, commit_hash=None
):
    """
    Run a release

    Args:
        github_access_token (str): The github access token
        repo_url (str): URL for a repo
        new_version (str): The version of the new release
        branch (str): The branch to initialize the release from
        commit_hash (str): Commit hash to cherry pick in case of a hot fix
    """

    await validate_dependencies()
    async with init_working_dir(
        github_access_token, repo_url, branch=branch
    ) as working_dir:
        await check_call(
            ["git", "checkout", "-qb", "release-candidate"], cwd=working_dir
        )
        if commit_hash:
            try:
                await check_call(["git", "cherry-pick", commit_hash], cwd=working_dir)
            except CalledProcessError:
                raise ReleaseException(
                    f"Cherry pick failed for the given hash {commit_hash}"
                )
        old_version = update_version(new_version, working_dir=working_dir)
        if parse_version(old_version) >= parse_version(new_version):
            raise ReleaseException(
                "old version is {old} but the new version {new} is not newer".format(
                    old=old_version, new=new_version,
                )
            )
        base_branch = "release-candidate" if commit_hash else "master"
        await verify_new_commits(old_version, base_branch=base_branch, root=working_dir)
        await update_release_notes(
            old_version, new_version, base_branch=base_branch, root=working_dir
        )
        await build_release(root=working_dir)
        await generate_release_pr(
            github_access_token=github_access_token,
            repo_url=repo_url,
            old_version=old_version,
            new_version=new_version,
            base_branch=base_branch,
            root=working_dir,
        )

    print(f"version {old_version} has been updated to {new_version}")
    print("Go tell engineers to check their work. PR is on the repo.")
    print("After they are done, run the finish_release.py script.")


def main():
    """
    Create a new release
    """
    try:
        github_access_token = os.environ["GITHUB_ACCESS_TOKEN"]
    except KeyError:
        raise Exception("Missing GITHUB_ACCESS_TOKEN")
    parser = argparse.ArgumentParser()
    parser.add_argument("repo_url")
    parser.add_argument("version")
    args = parser.parse_args()

    asyncio.run(
        release(
            github_access_token=github_access_token,
            repo_url=args.repo_url,
            new_version=args.version,
        )
    )


if __name__ == "__main__":
    main()
