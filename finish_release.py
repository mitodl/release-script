"""Release script to finish the release"""
import os
import re
from datetime import datetime
from pathlib import Path

from async_subprocess import (
    call,
    check_call,
    check_output,
)
from constants import GO, NPM
from exception import VersionMismatchException
from github import get_org_and_repo
from lib import (
    get_default_branch,
    get_pr_ref,
    get_release_pr,
)
from release import (
    init_working_dir,
    validate_dependencies,
)


async def merge_release_candidate(*, root):
    """Merge release-candidate into release"""
    await check_call(['git', 'checkout', 'release'], cwd=root)
    await check_call(['git', 'merge', 'release-candidate', '--no-edit'], cwd=root)
    await check_call(['git', 'push'], cwd=root)


async def check_release_tag(version, *, root):
    """Check release version number"""
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
    default_branch = await get_default_branch(root)

    await check_call(['git', 'checkout', '-q', default_branch], cwd=root)
    await check_call(['git', 'pull'], cwd=root)
    await check_call(['git', 'merge', 'release', '--no-edit'], cwd=root)
    await check_call(['git', 'push'], cwd=root)


def update_go_mod(*, path, version, repo_url):
    """
    Update go.mod, replacing the original git tag with our own copy

    Args:
        path (str or Path): The path to the go.mod file
        version (str): The new version for the referenced go module
        repo_url (str): The URL for the repository to be referenced in go.mod

    Returns:
        bool: True if an updated file was written, False otherwise
    """
    org, repo = get_org_and_repo(repo_url)
    with open(path) as f:
        old_lines = f.readlines()

    lines = [
        (
            f"require github.com/{org}/{repo} v{version} // indirect\n"
            if line.startswith("require ") else line
        ) for line in old_lines
    ]

    if old_lines != lines:
        with open(path, "w") as f:
            f.write("".join(lines))
        return True
    return False


async def update_other_repo_and_commit(*, github_access_token, new_version, repo_info, update_other_repo, pull_request):
    """
    After a release we sometimes want to update another repository to reference the newly released code.
    This checks out the other repository, attempts to update the reference to a new version,
    and commits and pushes that update.

    Args:
        github_access_token (str): A token to access github APIs
        new_version (str): The new version of the finished release
        repo_info (RepoInfo): The repository info for the finished release
        update_other_repo (UpdateOtherRepo): Info for the project to update
        pull_request (ReleasePR): The release PR
    """
    name = repo_info.name
    other_repo_url = update_other_repo.repo_info.repo_url
    async with init_working_dir(github_access_token, other_repo_url) as other_repo_path:
        other_repo_path = Path(other_repo_path)
        packaging_tool = update_other_repo.packaging_tool
        if packaging_tool == NPM:
            # This doesn't handle npm install but I don't think we have any packages that need that
            await check_call(
                ["yarn", "add", f"{repo_info.name}@{new_version}"],
                cwd=other_repo_path
            )
        elif packaging_tool == GO:
            update_go_mod(
                path=other_repo_path / "go.mod",
                version=new_version,
                repo_url=repo_info.repo_url,
            )
        else:
            raise Exception(f"Unsupported packaging tool ${packaging_tool}")

        changed = (await call(
            ["git", "diff", "--exit-code"],
            cwd=other_repo_path,
        ) != 0)
        if changed:
            await check_call(
                ["git", "add", "."],
                cwd=other_repo_path,
            )
            pr_ref = get_pr_ref(pull_request.url)
            await check_call(
                ["git", "commit", "-m", f"Update {name} to {new_version} ({pr_ref})"],
                cwd=other_repo_path,
            )
            await check_call(["git", "push"], cwd=other_repo_path)


async def finish_release(
    *, github_access_token, repo_info, version, timezone
):
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
        org, repo = get_org_and_repo(repo_info.repo_url)
        pr = await get_release_pr(
            github_access_token=github_access_token,
            org=org,
            repo=repo,
        )
        await check_release_tag(version, root=working_dir)
        await set_release_date(version, timezone, root=working_dir)
        await merge_release_candidate(root=working_dir)
        await tag_release(version, root=working_dir)
        await merge_release(root=working_dir)

        for update_other_repo in repo_info.update_other_repos:
            await update_other_repo_and_commit(
                github_access_token=github_access_token,
                new_version=version,
                repo_info=repo_info,
                update_other_repo=update_other_repo,
                pull_request=pr,
            )
