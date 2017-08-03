"""Release script to finish the release"""
import argparse
from subprocess import (
    check_call,
    check_output,
)

from release import (
    init_working_dir,
    validate_dependencies,
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
    check_call(['git', 'checkout', '-t', 'origin/release-candidate'])
    commit_name = check_output(['git', 'log', '-1', '--pretty=%B']).decode()
    if commit_name != "Release {}".format(version):
        raise Exception("ERROR: Commit name {commit_name} does not match tag number {version}".format(
            commit_name=commit_name,
            version=version,
        ))


def tag_release(version):
    """Add git tag for release"""
    print("Tag release...")
    check_call(['git', 'tag', '-a', '-m', "Release {}".format(version), "v{}".format(version)])
    check_call(['git', 'push', '--follow-tags'])


def merge_release():
    """Merge release to master"""
    print("Merge release to master")
    check_call(['git', 'checkout', '-q', 'master'])
    check_call(['git', 'pull'])
    check_call(['git', 'merge', 'release', '--no-edit'])
    check_call(['git', 'push'])


def finish_release(repo_url, version):
    """Merge release to master and deploy to production"""

    validate_dependencies()
    with init_working_dir(repo_url):
        check_release_tag(version)
        merge_release_candidate()
        tag_release(version)
        merge_release()


def main():
    """
    Deploy a release to production
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("repo_url")
    parser.add_argument("version")
    args = parser.parse_args()

    finish_release(repo_url=args.repo_url, version=args.version)


if __name__ == "__main__":
    main()
