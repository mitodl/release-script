"""
General versioning functions
"""
import json
import os
from pathlib import Path
import re

from async_subprocess import check_output
from constants import (
    DJANGO,
    LIBRARY_TYPE,
    NPM,
    SETUPTOOLS,
    WEB_APPLICATION_TYPE,
)
from exception import UpdateVersionException
from lib import init_working_dir, VERSION_RE


async def get_version_tag(*, github_access_token, repo_url, commit_hash):
    """Determines the version tag (or None) of the given commit hash"""
    async with init_working_dir(github_access_token, repo_url) as working_dir:
        output = await check_output(
            ["git", "tag", "-l", "--points-at", commit_hash],
            cwd=working_dir
        )
        return output.decode().strip()


def update_python_version_in_file(*, root, filename, new_version):
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
                    old_version = match.group('version').strip()
                    updated_line = re.sub(regex, "VERSION = \"{}\"".format(new_version), line)
            elif filename == "__init__.py":
                regex = r"^__version__ ?=.*(?P<version>{}).*".format(VERSION_RE)
                match = re.match(regex, line)
                if match:
                    update_count += 1
                    old_version = match.group('version').strip()
                    updated_line = re.sub(regex, "__version__ = '{}'".format(new_version), line)
            elif filename == "setup.py":
                regex = r"\s*version=.*(?P<version>{}).*".format(VERSION_RE)
                match = re.match(regex, line)
                if match:
                    update_count += 1
                    old_version = match.group('version').strip()
                    updated_line = re.sub(regex, "version='{}',".format(new_version), line)

            file_lines.append("{}\n".format(updated_line))

    if update_count == 1:
        # Replace contents of file with updated version
        with open(version_filepath, "w") as f:
            for line in file_lines:
                f.write(line)
        return old_version
    elif update_count > 1:
        raise UpdateVersionException("Expected only one version for {file} but found {count}".format(
            file=filename,
            count=update_count,
        ))

    # Unable to find old version for this file, but maybe there's another one
    return None


def update_python_version(*, new_version, working_dir):
    """Update the version from the project and return the old one, or raise an exception if none is found"""
    exclude_dirs = ('.cache', '.git', '.settings', )
    version_files = ('settings.py', '__init__.py', 'setup.py')
    found_version_filename = None
    old_version = None
    for version_filename in version_files:
        for root, dirs, filenames in os.walk(working_dir, topdown=True):
            dirs[:] = [d for d in dirs if d not in exclude_dirs]
            if version_filename in filenames:
                version = update_python_version_in_file(root=root, filename=version_filename, new_version=new_version)
                if version:
                    if not found_version_filename:
                        found_version_filename = version_filename
                        old_version = version
                    else:
                        raise UpdateVersionException(
                            "Found at least two files with updatable versions: {} and {}".format(
                                found_version_filename,
                                version_filename,
                            )
                        )

    if not found_version_filename:
        raise UpdateVersionException("Unable to find previous version number")

    return old_version


async def update_npm_version(*, new_version, working_dir):
    """
    Update NPM package version. Note that this does not tag or make any commit to git; this is handled separately.

    Args:
        new_version (str): The new version
        working_dir (str): The directory of the package

    Returns:
        str:
            The old version which has been successfully replaced with the new version.
            On error, an exception will raise.
    """
    with open(Path(working_dir) / "package.json", "r") as f:
        old_version = json.load(f)["version"]
    await check_output(["npm", "--no-git-tag-version", "version", new_version], cwd=working_dir)
    return old_version


async def update_version(*, repo_info, new_version, working_dir):
    """
    Update the version in the project if necessary, depending on project and packaging type.

    Args:
        repo_info (RepoInfo): Repo info
        new_version (str): The new version
        working_dir (str): The directory with the project

    Returns:
        str:
            The old version which has been successfully replaced with the new version.
            On failure, an exception will be raised.
    """
    if repo_info.project_type == WEB_APPLICATION_TYPE:
        if repo_info.web_application_type == DJANGO:
            return update_python_version(new_version=new_version, working_dir=working_dir)
        # do nothing for Hugo
    elif repo_info.project_type == LIBRARY_TYPE:
        if repo_info.packaging_tool == SETUPTOOLS:
            return update_python_version(new_version=new_version, working_dir=working_dir)
        elif repo_info.packaging_tool == NPM:
            return await update_npm_version(new_version=new_version, working_dir=working_dir)
