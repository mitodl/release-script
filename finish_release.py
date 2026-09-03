"""Release script to finish the release"""

from async_subprocess import (
    call,
    check_call,
    check_output,
)
from exception import ReleaseException, VersionMismatchException
from lib import get_commit_hash, get_default_branch, tag_exists
from release import (
    init_working_dir,
    validate_dependencies,
)


async def merge_release_candidate(*, root):
    """Merge release-candidate into release"""
    await check_call(["git", "checkout", "release"], cwd=root)
    await check_call(["git", "merge", "release-candidate", "--no-edit"], cwd=root)
    await check_call(["git", "push"], cwd=root)


async def check_release_tag(version, *, root):
    """Check release version number"""
    await check_call(["git", "checkout", "release-candidate"], cwd=root)
    log_output = await check_output(["git", "log", "-1", "--pretty=%B"], cwd=root)
    commit_name = log_output.decode().strip()
    if commit_name != f"Release {version}":
        raise VersionMismatchException(
            f"Commit name {commit_name} does not match tag number {version}"
        )


async def verify_release_tag(version, *, root):
    """
    Check that an existing release tag actually identifies the release being finished

    Tags are immutable, so a tag pointing at unrelated code cannot be corrected here.
    Fail rather than finish a release whose version tag identifies the wrong commit.

    Args:
        version (str): The version of the release
        root (str): The path to the repository
    """
    tag = f"v{version}"
    tag_commit = await get_commit_hash(tag, root=root)
    rc_commit = await get_commit_hash("release-candidate", root=root)
    if tag_commit == rc_commit:
        return

    # A tag created while finishing the release lands on the release merge commit
    # instead, so accept any tag that contains the release
    contains_release = (
        await call(
            ["git", "merge-base", "--is-ancestor", rc_commit, tag_commit], cwd=root
        )
        == 0
    )
    if not contains_release:
        raise ReleaseException(
            f"Tag {tag} points at {tag_commit}, which does not contain the "
            f"release-candidate commit {rc_commit}. Tags are immutable, so this "
            f"release cannot be finished under this version number."
        )


async def tag_release(version, *, root):
    """
    Add git tag for release, unless the release candidate was already tagged when it
    was cut

    Web application projects are tagged when the release candidate is cut, so the tag is
    normally already here and is verified rather than recreated. Library projects, and
    release candidates cut before tagging moved earlier, have no tag yet.

    Args:
        version (str): The version of the release
        root (str): The path to the repository
    """
    if await tag_exists(version, root=root):
        await verify_release_tag(version, root=root)
    else:
        await check_call(
            ["git", "tag", "-a", "-m", f"Release {version}", f"v{version}"],
            cwd=root,
        )
    await check_call(["git", "push", "--follow-tags"], cwd=root)


async def merge_release(*, root):
    """Merge release to master"""
    default_branch = await get_default_branch(root)

    await check_call(["git", "checkout", "-q", default_branch], cwd=root)
    await check_call(["git", "pull"], cwd=root)
    await check_call(["git", "merge", "release", "--no-edit"], cwd=root)
    await check_call(["git", "push"], cwd=root)


async def finish_release(*, github_access_token, repo_info, version):
    """
    Merge release to master and deploy to production

    Args:
        github_access_token (str): Github access token
        repo_info (RepoInfo): The info of the project being released
        version (str): The new version of the release
    """

    await validate_dependencies()
    async with init_working_dir(github_access_token, repo_info.repo_url) as working_dir:
        await check_release_tag(version, root=working_dir)
        await merge_release_candidate(root=working_dir)
        await tag_release(version, root=working_dir)
        await merge_release(root=working_dir)
