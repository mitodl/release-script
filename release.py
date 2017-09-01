#!/usr/bin/env python3
"""Release script for ODL projects"""
import argparse
from contextlib import contextmanager
import re
from subprocess import (
    call,
    check_call,
    check_output,
    PIPE,
)
from tempfile import TemporaryDirectory
import os

from pkg_resources import parse_version


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


class DependencyException(Exception):
    """Error if dependency is missing"""


class OldVersionException(Exception):
    """Error if the old version is invalid or cannot be found"""


class VersionMismatchException(Exception):
    """Error if the version is unexpected"""


def dependency_exists(command):
    """Returns true if a command exists on the system"""
    return call(["which", command], stdout=PIPE) == 0


@contextmanager
def init_working_dir(repo_url):
    """Create a new directory with an empty git repo"""
    pwd = os.getcwd()
    try:
        with TemporaryDirectory() as directory:
            os.chdir(directory)
            # from http://stackoverflow.com/questions/2411031/how-do-i-clone-into-a-non-empty-directory
            check_call(["git", "init"])
            check_call(["git", "remote", "add", "origin", repo_url])
            check_call(["git", "fetch"])
            check_call(["git", "checkout", "-t", "origin/master"])
            yield directory
    finally:
        os.chdir(pwd)


def validate_dependencies():
    """Error if a dependency is missing or invalid"""
    print("Validating dependencies...")

    if not dependency_exists("hub"):
        raise DependencyException('Please install hub https://hub.github.com/')
    if not dependency_exists("git"):
        raise DependencyException('Please install git https://git-scm.com/downloads')
    if not dependency_exists("git-release-notes"):
        raise DependencyException('Please install git-release-notes https://www.npmjs.com/package/git-release-notes')
    if not dependency_exists("node"):
        raise DependencyException('Please install node.js https://nodejs.org/')

    version = check_output(["node", "--version"]).decode()
    major_version = int(re.match(r'^v(\d+)\.', version).group(1))
    if major_version < 6:
        raise DependencyException("node.js must be version 6.x or higher")


def parse_version_from_line(line):
    """Parse version number from line and return it, or return None if it can't be parsed"""
    # copied from release.sh, this should be cleaned up
    line_lower = line.lower()
    if "version" not in line_lower:
        return None
    line_lower = line_lower.replace(" =", " ").replace('"', ' ').replace("'", " ")
    pieces = line_lower.split()
    if len(pieces) > 1:
        return pieces[1]
    else:
        return None


def update_version_in_file(root, filename, new_version):
    """
    Update the version from the file and return the old version if it's found
    """
    version_filepath = os.path.join(root, filename)
    file_lines = []
    updated = False
    old_version = None
    with open(version_filepath) as f:
        for line in f.readlines():
            line_lower = line.lower()
            version = parse_version_from_line(line_lower)
            if version is not None and not updated:
                old_version = version
                updated = True
                if filename == "settings.py":
                    updated_line = re.sub(
                        "VERSION = .*",
                        "VERSION = \"{version}\"".format(version=new_version),
                        line,
                    )
                elif filename == "__init__.py":
                    updated_line = re.sub(
                        "__version__ ?=.*# pragma: no cover",
                        "__version__ = '{version}'  # pragma: no cover".format(version=new_version),
                        line,
                    )
                elif filename == "setup.py":
                    updated_line = re.sub(
                        "version=.*",
                        "version='{version},'".format(version=new_version),
                        line,
                    )
                else:
                    # Shouldn't get here
                    raise OldVersionException("Unexpected file")
                file_lines.append(updated_line)
            else:
                file_lines.append(line)

    if updated:
        # Replace contents of file with updated version
        with open(version_filepath, "w") as f:
            for line in file_lines:
                f.write(line)
        return old_version

    # Unable to find old version for this file, but maybe there's another one


def update_version(new_version):
    """Update the version from the project and return the old one, or raise an exception if none is found"""
    print("Updating version...")
    version_files = ('settings.py', '__init__.py', 'setup.py')
    for version_filename in version_files:
        for root, _, filenames in os.walk("."):
            if version_filename in filenames:
                result = update_version_in_file(root, version_filename, new_version)
                if result:
                    return result

    raise OldVersionException("Unable to find previous version number")


def create_release_notes(old_version, with_checkboxes):
    """Returns the release note text for the commits made for this version"""
    if with_checkboxes:
        filename = "release_notes.ejs"
    else:
        filename = "release_notes_rst.ejs"

    return check_output([
        "git-release-notes",
        "v{}..master".format(old_version),
        os.path.join(SCRIPT_DIR, "util", filename),
    ]).decode()


def verify_new_commits(old_version):
    """Check if there are new commits to release"""
    if int(check_output(["git", "rev-list", "--count", "v{}..master".format(old_version)])) == 0:
        raise Exception("No new commits to put in release")


def update_release_notes(old_version, new_version):
    """Updates RELEASE.rst and commits it"""
    print("Updating release notes...")

    release_notes = create_release_notes(old_version, with_checkboxes=False)

    release_filename = "RELEASE.rst"
    try:
        with open(release_filename) as f:
            existing_note_lines = [line for line in f.readlines()]
    except FileNotFoundError:
        existing_note_lines = []

    with open(release_filename, "w") as f:
        f.write("Release notes\n")
        f.write("=============\n")
        f.write("\n")
        version_line = "Version {}".format(new_version)
        f.write("{}\n".format(version_line))
        f.write("{}\n".format("-" * len(version_line)))
        f.write("\n")
        f.write("\n")
        f.write(release_notes)
        f.write("\n")

        # skip first four lines which contain the header we are replacing
        for old_line in existing_note_lines[-4:]:
            f.write(old_line)

    check_call(["git", "add", release_filename])
    check_call(["git", "commit", "-q", "--all", "--message", "Release {}".format(new_version)])


def build_release():
    """Deploy the release candidate"""
    print("Building release...")
    check_call(["git", "push", "--force", "-q", "origin", "release-candidate:release-candidate"])


def generate_release_pr(old_version, new_version):
    """Make a release pull request for the deployed release-candidate branch"""
    print("Generating PR...")

    checklist_file = "release-notes-checklist"
    with open(checklist_file, "w") as f:
        f.write("Release {}\n".format(new_version))
        f.write("\n")

        f.write(create_release_notes(old_version, with_checkboxes=True))

    check_call(["hub", "pull-request", "-b", "release", "-h", "release-candidate", "-F", checklist_file])


def release(repo_url, new_version):
    """Run a release"""

    validate_dependencies()

    with init_working_dir(repo_url):
        check_call(["git", "checkout", "-qb", "release-candidate"])
        old_version = update_version(new_version)
        if parse_version(old_version) >= parse_version(new_version):
            raise Exception("old version is {old} but the new version {new} is not newer".format(
                old=old_version,
                new=new_version,
            ))
        verify_new_commits(old_version)
        update_release_notes(old_version, new_version)
        build_release()
        generate_release_pr(old_version, new_version)

    print("version {old_version} has been updated to {new_version}".format(
        old_version=old_version,
        new_version=new_version,
    ))
    print("Go tell engineers to check their work. PR is on the repo.")
    print("After they are done, run the finish_release.py script.")


def main():
    """
    Create a new release
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("repo_url")
    parser.add_argument("version")
    args = parser.parse_args()

    release(repo_url=args.repo_url, new_version=args.version)


if __name__ == "__main__":
    main()
