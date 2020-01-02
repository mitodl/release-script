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


async def merge_release_candidate(*, root):
    """Merge release-candidate into release"""
    print("Merge release-candidate into release")
    await check_call(['git', 'checkout', 'release'], cwd=root)
    await check_call(['git', 'merge', 'release-candidate', '--no-edit'], cwd=root)
    await check_call(['git', 'push'], cwd=root)


async def check_release_tag(version, *, root):
    """Check release version number"""
    print("Check release version number...")
    await check_call(['git', 'checkout', 'release-candidate'], cwd=root)
    log_output = await check_output(['git', 'log', '-1', '--pretty=%B'], cwd=root)
    commit_name = log_output.decode().strip()
    if commit_name != "Release {}".format(version):
        raise VersionMismatchException("Commit name {commit_name} does not match tag number {version}".format(
            commit_name=commit_name,
            version=version,
        ))


async def tag_release(version, *, root):
    """Add git tag for release"""
    print("Tag release...")
    await check_call(['git', 'tag', '-a', '-m', "Release {}".format(version), "v{}".format(version)], cwd=root)
    await check_call(['git', 'push', '--follow-tags'], cwd=root)


async def set_release_date(version, timezone, *, root):
    """Sets the release date(s) in RELEASE.rst for any versions missing it"""
    release_filename = os.path.join(root, "RELEASE.rst")
    if not os.path.isfile(release_filename):
        return
    date_format = "%B %d, %Y"
    await check_call(["git", "fetch", "--tags"], cwd=root)
    await check_call(['git', 'checkout', 'release-candidate'], cwd=root)

    with open(release_filename) as f:
        existing_note_lines = f.readlines()

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
                            ["git", "log", "-1", "--format=%ai", "v{}".format(version_line)],
                            cwd=root,
                        )
                        version_date = version_output.rstrip()
                        localtime = datetime.strptime(version_date.decode("utf-8"), "%Y-%m-%d %H:%M:%S %z").\
                            astimezone(timezone).strftime(date_format)
                    line = "Version {} (Released {})\n".format(version_line, localtime)
            f.write(line)

    await check_call(["git", "commit", "-q", release_filename, "-m", "Release date for {}".format(version)], cwd=root)


async def merge_release(*, root):
    """Merge release to master"""
    print("Merge release to master")
    await check_call(['git', 'checkout', '-q', 'master'], cwd=root)
    await check_call(['git', 'pull'], cwd=root)
    await check_call(['git', 'merge', 'release', '--no-edit'], cwd=root)
    await check_call(['git', 'push'], cwd=root)


async def finish_release(*, github_access_token, repo_url, version, timezone):
    """Merge release to master and deploy to production"""

    await validate_dependencies()
    async with init_working_dir(github_access_token, repo_url) as working_dir:
        await check_release_tag(version, root=working_dir)
        await set_release_date(version, timezone, root=working_dir)
        await merge_release_candidate(root=working_dir)
        await tag_release(version, root=working_dir)
        await merge_release(root=working_dir)


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
