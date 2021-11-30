"""
General versioning functions
"""
import json
import os
from pathlib import Path
import re

from async_subprocess import check_output
from constants import (
    FILE_VERSION,
    NPM_VERSION,
    PYTHON_VERSION,
)
from exception import UpdateVersionException
from lib import init_working_dir, VERSION_RE


async def get_version_tag(*, github_access_token, repo_url, commit_hash):
    """
    Determines the version tag (or None) of the given commit hash

    Args:
        github_access_token (str): The access token
        repo_url (str): The URL for the git repo of the project
        commit_hash (str): The commit hash where we expect to find a tag with the version number
    """
    async with init_working_dir(github_access_token, repo_url) as working_dir:
        output = await check_output(
            ["git", "tag", "-l", "--points-at", commit_hash], cwd=working_dir
        )
        return output.decode().strip()


async def get_commit_oneline_message(*, github_access_token, repo_url, commit_hash):
    """
    Get the git commit message plus a piece of the hash for display purposes

    Args:
        github_access_token (str): The access token
        repo_url (str): The URL for the git repo of the project
        commit_hash (str): The commit hash where we expect to find a tag with the version number
    """
    async with init_working_dir(github_access_token, repo_url) as working_dir:
        output = await check_output(
            ["git", "log", "--oneline", f"{commit_hash}^1..{commit_hash}", "--"],
            cwd=working_dir,
        )
        return output.decode().strip()


def update_python_version_in_file(*, root, filename, new_version, readonly):
    """
    Update the version from the file and return the old version if it's found.

    Args:
        root (str): The directory with the file
        filename (str): The file within that directory
        new_version (str): The new version to insert into the file
        readonly (bool): If true, don't actually write changes to the file, just return the old version if found

    Returns:
        str:
            Return the old version that the file used to have before this function updated that file. If the
            file doesn't seem to match the version pattern, return None.
    """
    version_filepath = os.path.join(root, filename)
    file_lines = []
    update_count = 0
    old_version = None
    with open(version_filepath, "r", encoding="utf-8") as f:
        for line in f.readlines():
            line = line.strip("\n")
            updated_line = line

            if filename == "settings.py":
                regex = fr"^VERSION = .*(?P<version>{VERSION_RE}).*$"
                match = re.match(regex, line)
                if match:
                    update_count += 1
                    old_version = match.group("version").strip()
                    updated_line = re.sub(regex, f'VERSION = "{new_version}"', line)
            elif filename == "__init__.py":
                regex = fr"^__version__ ?=.*(?P<version>{VERSION_RE}).*"
                match = re.match(regex, line)
                if match:
                    update_count += 1
                    old_version = match.group("version").strip()
                    updated_line = re.sub(regex, f'__version__ = "{new_version}"', line)
            elif filename == "setup.py":
                regex = fr"(?P<spaces>\s*)version=(?P<quote>.*)(?P<version>{VERSION_RE})(?P<after>.*)"
                match = re.match(regex, line)
                if match:
                    update_count += 1
                    old_version = match.group("version").strip()
                    updated_line = re.sub(
                        regex,
                        f"{match.group('spaces')}version={match.group('quote')}{new_version}{match.group('after')}",
                        line,
                    )

            file_lines.append(f"{updated_line}\n")

    if update_count == 1:
        # Replace contents of file with updated version
        if not readonly:
            with open(version_filepath, "w", encoding="utf-8") as f:
                for line in file_lines:
                    f.write(line)
        return old_version
    elif update_count > 1:
        raise UpdateVersionException(
            f"Expected only one version for {filename} but found {update_count}"
        )

    # Unable to find old version for this file, but maybe there's another one
    return None


def update_python_version(*, new_version, working_dir, readonly):
    """
    Update the version from the project and return the old one, or raise an exception if none is found

    Args:
        new_version (str): The new version to insert into the file
        working_dir (str): The project directory
        readonly (bool): If true, return the old version if found but don't actually write changes to any files

    Returns:
        str:
            If the right file was found, replace the old version with the new one, then return the old version.
            If no file is found, or if two or more files match, raise an exception.
    """
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
                version = update_python_version_in_file(
                    root=root,
                    filename=version_filename,
                    new_version=new_version,
                    readonly=readonly,
                )
                if version:
                    if not found_version_filename:
                        found_version_filename = version_filename
                        old_version = version
                    else:
                        raise UpdateVersionException(
                            f"Found at least two files with updatable versions: {found_version_filename} and {version_filename}"
                        )

    if not found_version_filename:
        raise UpdateVersionException("Unable to find previous version number")

    return old_version


async def update_npm_version(*, new_version, working_dir, readonly):
    """
    Update NPM package version. Note that this does not tag or make any commit to git; this is handled separately.

    Args:
        new_version (str): The new version
        working_dir (str): The directory of the package
        readonly (bool): If true, return the old version if found but don't actually write changes to any files

    Returns:
        str:
            The old version which has been successfully replaced with the new version.
            On error, an exception will raise.
    """
    with open(Path(working_dir) / "package.json", "r", encoding="utf-8") as f:
        old_version = json.load(f)["version"]
    if not readonly:
        await check_output(
            ["npm", "--no-git-tag-version", "version", new_version], cwd=working_dir
        )
    return old_version


async def update_version_file(*, new_version, working_dir, readonly):
    """
    Update a VERSION file.

    Args:
        new_version (str): The new version
        working_dir (str): The directory of the library
        readonly (bool): If true, return the old version if found but don't actually write changes to any files

    Returns:
        str:
            The old version which has been successfully replaced with the new version.
            On error, an exception will raise.
    """
    old_version = None
    version_file = Path(working_dir) / "VERSION"
    if version_file.is_file():
        with open(version_file, "r", encoding="utf-8") as f:
            old_version = f.readline().strip()
        if not readonly:
            with open(version_file, "w", encoding="utf-8") as f:
                f.write(new_version)
    return old_version


async def get_project_version(*, repo_info, working_dir):
    """
    Look up the version of a project from the project instance in the working directory

    Args:
        repo_info (RepoInfo): Repository info
        working_dir (str or Path): Where the project was recently checked out
    """
    return await update_version(
        repo_info=repo_info, new_version="9.9.9", working_dir=working_dir, readonly=True
    )


async def update_version(*, repo_info, new_version, working_dir, readonly):
    """
    Update the version in the project if necessary, depending on project and packaging type.

    Args:
        repo_info (RepoInfo): Repo info
        new_version (str): The new version
        working_dir (str): The directory with the project
        readonly (bool): If true, return the old version if found but don't actually write changes to any files

    Returns:
        str:
            The old version which has been successfully replaced with the new version.
            On failure, an exception will be raised.
    """
    if repo_info.versioning_strategy == PYTHON_VERSION:
        return update_python_version(
            new_version=new_version, working_dir=working_dir, readonly=readonly
        )
    elif repo_info.versioning_strategy == NPM_VERSION:
        return await update_npm_version(
            new_version=new_version, working_dir=working_dir, readonly=readonly
        )
    elif repo_info.versioning_strategy == FILE_VERSION:
        return await update_version_file(
            new_version=new_version, working_dir=working_dir, readonly=readonly
        )
