"""Release script to finish the release"""
import argparse
import asyncio
import os
import re
from datetime import datetime

from async_subprocess import (
    check_call,
    check_output,
)
from release import (
    init_working_dir,
    validate_dependencies,
    VersionMismatchException,
)


async def merge_release_candidate():
    """Merge release-candidate into release"""
    print("Merge release-candidate into release")
    await check_call(['git', 'checkout', 'release'])
    await check_call(['git', 'merge', 'release-candidate', '--no-edit'])
    await check_call(['git', 'push'])


async def check_release_tag(version):
    """Check release version number"""
    print("Check release version number...")
    await check_call(['git', 'checkout', 'release-candidate'])
    log_output = await check_output(['git', 'log', '-1', '--pretty=%B'])
    commit_name = log_output.decode().strip()
    if commit_name != "Release {}".format(version):
        raise VersionMismatchException("Commit name {commit_name} does not match tag number {version}".format(
            commit_name=commit_name,
            version=version,
        ))


async def tag_release(version):
    """Add git tag for release"""
    print("Tag release...")
    await check_call(['git', 'tag', '-a', '-m', "Release {}".format(version), "v{}".format(version)])
    await check_call(['git', 'push', '--follow-tags'])


async def set_release_date(version, timezone):
    """Sets the release date(s) in RELEASE.rst for any versions missing it"""
    print("Setting release date...")
    release_filename = "RELEASE.rst"
    if not os.path.isfile(release_filename):
        return
    date_format = "%B %d, %Y"
    await check_call(["git", "fetch", "--tags"])
    await check_call(['git', 'checkout', 'release-candidate'])

    with open(release_filename) as f:
        existing_note_lines = [line for line in f.readlines()]

    with open(release_filename, "w") as f:
        for line in existing_note_lines:
            if line.startswith("Version ") and "Released" not in line:
                version_match = re.search(r"[0-9\.]+", line)
                if version_match:
                    version_line = version_match.group(0)
                    if version_line == version:
                        localtime = datetime.now().strftime(date_format)
                    else:
                        version_output = await check_output(
                            ["git", "log", "-1", "--format=%ai", "v{}".format(version_line)]
                        )
                        version_date = version_output.rstrip()
                        localtime = datetime.strptime(version_date.decode("utf-8"), "%Y-%m-%d %H:%M:%S %z").\
                            astimezone(timezone).strftime(date_format)
                    line = "Version {} (Released {})\n".format(version_line, localtime)
            f.write(line)

    await check_call(["git", "commit", "-q", release_filename, "-m", "Release date for {}".format(version)])


async def merge_release():
    """Merge release to master"""
    print("Merge release to master")
    await check_call(['git', 'checkout', '-q', 'master'])
    await check_call(['git', 'pull'])
    await check_call(['git', 'merge', 'release', '--no-edit'])
    await check_call(['git', 'push'])


async def finish_release(*, github_access_token, repo_url, version, timezone):
    """Merge release to master and deploy to production"""

    await validate_dependencies()
    async with init_working_dir(github_access_token, repo_url):
        await check_release_tag(version)
        await set_release_date(version, timezone)
        await merge_release_candidate()
        await tag_release(version)
        await merge_release()


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

    asyncio.run(finish_release(
        github_access_token=github_access_token,
        repo_url=args.repo_url,
        version=args.version,
        timezone=args.timezone
    ))


if __name__ == "__main__":
    main()
