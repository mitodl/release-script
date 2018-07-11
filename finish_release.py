"""Release script to finish the release"""
import argparse
import os
import re

import pytz
from datetime import datetime
from subprocess import (
    check_call,
    check_output,
)

from release import (
    init_working_dir,
    validate_dependencies,
    VersionMismatchException,
)


def merge_release_candidate():
    """Merge release-candidate into release"""
    print("Merge release-candidate into release")
    check_call(['git', 'checkout', '-t', 'origin/release'])
    check_call(['git', 'merge', 'origin/release-candidate'])
    check_call(['git', 'push'])


def check_release_tag(version):
    """Check release version number"""
    print("Check release version number...")
    check_call(['git', 'checkout', 'release-candidate'])
    commit_name = check_output(['git', 'log', '-1', '--pretty=%B']).decode().strip()
    if commit_name != "Release {}".format(version):
        raise VersionMismatchException("Commit name {commit_name} does not match tag number {version}".format(
            commit_name=commit_name,
            version=version,
        ))


def tag_release(version):
    """Add git tag for release"""
    print("Tag release...")
    check_call(['git', 'tag', '-a', '-m', "Release {}".format(version), "v{}".format(version)])
    check_call(['git', 'push', '--follow-tags'])


def set_release_date(version):
    """Sets the release date(s) in RELEASE.rst for any versions missing it"""
    print("Setting release date...")
    check_call(["git", "fetch", "--tags"])
    release_filename = "RELEASE.rst"
    date_format = '%Y-%m-%d'
    with open(release_filename) as f:
        existing_note_lines = [line for line in f.readlines()]

    try:
        with open(release_filename, "w") as f:
            for line in existing_note_lines:
                if line.startswith("Version ") and "Released" not in line:
                    version_match = re.search(r"[0-9\.]+", line)
                    if version_match:
                        version_line = version_match.group(0)
                        version_date = check_output(
                            ["git",  "log",  "-1",  "--format=%ai", 'v{}'.format(version_line)]
                        )
                        localtime = datetime.strptime(version_date.decode('utf-8'), '%Y-%m-%d %H:%M:%S %z\n').\
                            astimezone(pytz.timezone("America/New_York")).strftime(date_format)
                        line = 'Version {} (released {})\n'.format(version_line, localtime)
                f.write(line)
    except:  # pylint:disable=bare-except
        check_call(["git", "checkout", "HEAD", "--", release_filename])
        raise
    check_call(["git", "commit", "-q", release_filename, "-m", "Release date for {}".format(version)])
    check_call(['git', 'push'])


def merge_release():
    """Merge release to master"""
    print("Merge release to master")
    check_call(['git', 'checkout', '-q', 'master'])
    check_call(['git', 'pull'])
    check_call(['git', 'merge', 'release', '--no-edit'])
    check_call(['git', 'push'])


def finish_release(*, github_access_token, repo_url, version):
    """Merge release to master and deploy to production"""

    validate_dependencies()
    with init_working_dir(github_access_token, repo_url):
        check_release_tag(version)
        merge_release_candidate()
        tag_release(version)
        merge_release()
        set_release_date(version)


def main():
    """
    Deploy a release to production
    """
    try:
        github_access_token = os.environ['GITHUB_ACCESS_TOKEN']
    except KeyError:
        raise Exception("Missing GITHUB_ACCESS_TOKEN")

    parser = argparse.ArgumentParser()
    parser.add_argument("repo_url")
    parser.add_argument("version")
    args = parser.parse_args()

    finish_release(
        github_access_token=github_access_token,
        repo_url=args.repo_url,
        version=args.version,
    )


if __name__ == "__main__":
    main()
