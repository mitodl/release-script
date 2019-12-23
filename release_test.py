"""Tests for release script"""
import os
from subprocess import check_call, CalledProcessError
from tempfile import TemporaryDirectory

import pytest

from exception import ReleaseException
from release import (
    any_new_commits,
    create_release_notes,
    dependency_exists,
    DependencyException,
    generate_release_pr,
    GIT_RELEASE_NOTES_PATH,
    init_working_dir,
    release,
    update_release_notes,
    UpdateVersionException,
    update_version,
    update_version_in_file,
    url_with_access_token,
    validate_dependencies,
    verify_new_commits,
)
from version import get_version_tag
from wait_for_deploy import fetch_release_hash


pytestmark = pytest.mark.asyncio


# pylint: disable=redefined-outer-name, unused-argument
async def test_update_version_settings(test_repo):
    """update_version should return the old version and replace the appropriate file's text with the new version"""
    new_version = "9.9.99"
    path = "ccxcon/settings.py"

    old_lines = open(path).readlines()

    old_version = update_version(new_version)
    assert old_version == "0.2.0"
    new_lines = open(path).readlines()

    assert len(old_lines) == len(new_lines)

    diff_count = 0
    for old_line, new_line in zip(old_lines, new_lines):
        if old_line != new_line:
            diff_count += 1

    assert diff_count == 1

    found_new_version = False
    with open(path) as f:
        for line in f.readlines():
            if line == "VERSION = \"{}\"\n".format(new_version):
                found_new_version = True
                break
    assert found_new_version, "Unable to find updated version"


async def test_update_version_init(test_repo):
    """If we detect a version in a __init__.py file we should update it properly"""
    old_version = '1.2.3'
    os.unlink("ccxcon/settings.py")
    with open("ccxcon/__init__.py", "w") as f:
        f.write("__version__ = '{}'".format(old_version))
    new_version = "4.5.6"
    assert update_version(new_version) == old_version

    found_new_version = False
    with open("ccxcon/__init__.py") as f:
        for line in f.readlines():
            if line.strip() == "__version__ = '{}'".format(new_version):
                found_new_version = True
                break
    assert found_new_version, "Unable to find updated version"


async def test_update_version_setup(test_repo):
    """If we detect a version in setup.py we should update it properly"""
    old_version = '0.2.0'
    os.unlink("ccxcon/settings.py")
    with open("setup.py", "w") as f:
        f.write("""
setup(
    name='pylmod',
    version='0.2.0',
    license='BSD',
    author='MIT ODL Engineering',
    zip_safe=True,
)        """)
    new_version = '4.5.6'
    assert update_version(new_version) == old_version

    found_new_version = False
    with open("setup.py") as f:
        for line in f.readlines():
            if line.strip() == "version='{}',".format(new_version):
                found_new_version = True
                break
    assert found_new_version, "Unable to find updated version"


async def test_update_version_missing(test_repo):
    """If there is no version we should return None"""
    os.unlink("ccxcon/settings.py")
    contents = """
setup(
    name='pylmod',
)        """
    with open("setup.py", "w") as f:
        f.write(contents)
    with pytest.raises(UpdateVersionException) as ex:
        update_version("4.5.6")
    assert ex.value.args[0] == "Unable to find previous version number"


async def test_update_version_duplicate(test_repo):
    """If there are two detected versions in different files we should raise an exception"""
    contents = """
setup(
    name='pylmod',
    version='1.2.3',
)        """
    with open("setup.py", "w") as f:
        f.write(contents)
    with pytest.raises(UpdateVersionException) as ex:
        update_version("4.5.6")
    assert ex.value.args[0] == "Found at least two files with updatable versions: settings.py and setup.py"


async def test_update_version_duplicate_same_file(test_repo):
    """If there are two detected versions in the same file we should raise an exception"""
    contents = """
setup(
    name='pylmod',
    version='1.2.3',
    version='4.5.6',
)        """
    with open("setup.py", "w") as f:
        f.write(contents)
    with pytest.raises(UpdateVersionException) as ex:
        update_version("4.5.6")
    assert ex.value.args[0] == "Expected only one version for setup.py but found 2"


async def test_dependency_exists():
    """dependency_exists should check that the command exists on the system"""
    assert await dependency_exists("ls")
    assert not await dependency_exists("xyzzy")


async def test_validate_dependencies(mocker):
    """validate_dependencies should do nothing if all dependencies exist"""
    dependency_exists_stub = mocker.async_patch('release.dependency_exists')
    dependency_exists_stub.return_value = True
    await validate_dependencies()
    for dependency in ('node', 'git', GIT_RELEASE_NOTES_PATH):
        dependency_exists_stub.assert_any_call(dependency)


@pytest.mark.parametrize("dependency", ['node', 'git', GIT_RELEASE_NOTES_PATH])
async def test_validate_dependencies_failure(mocker, dependency):
    """validate_dependencies should raise an exception if a dependency is missing or invalid"""
    dependency_exists_stub = mocker.async_patch('release.dependency_exists')
    # the cell-var-from-loop warning can be ignored because this function is executed
    # immediately after its definition
    dependency_exists_stub.side_effect = (
        lambda _dependency: _dependency != dependency  # pylint: disable=cell-var-from-loop
    )

    with pytest.raises(DependencyException):
        await validate_dependencies()

    dependency_exists_stub.assert_any_call(dependency)


@pytest.mark.parametrize("filename,line", [
    ('settings.py', 'VERSION = \"0.34.56\"'),
    ('__init__.py', '__version__ = \'0.34.56\''),
])
async def test_update_version_in_file(filename, line):
    """update_version_in_file should update the version in the file and return the old version, if found"""
    with TemporaryDirectory() as base:
        with open(os.path.join(base, filename), "w") as f:
            f.write("text")
        retrieved_version = update_version_in_file(base, filename, "0.123.456")
        assert retrieved_version is None

        with open(os.path.join(base, filename), "w") as f:
            f.write(line)

        retrieved_version = update_version_in_file(base, filename, "0.123.456")
        assert retrieved_version == "0.34.56"


@pytest.mark.parametrize("major", [3, 4, 5, 6, 7, 8])
async def test_validate_node_version(mocker, major):
    """validate_dependencies should check that the major node.js version is new enough"""
    node_version = "v{}.2.1".format(major).encode()

    dependency_exists_stub = mocker.async_patch('release.dependency_exists')
    dependency_exists_stub.return_value = True
    check_output_stub = mocker.async_patch('release.check_output')
    check_output_stub.return_value = node_version
    if major >= 6:
        await validate_dependencies()
    else:
        with pytest.raises(DependencyException):
            await validate_dependencies()


@pytest.mark.parametrize("branch", [None, "branchy"])
async def test_init_working_dir(mocker, branch):
    """init_working_dir should initialize a valid git repo, and clean up after itself"""
    repo_url = "https://github.com/mitodl/release-script.git"
    access_token = 'fake_access_token'
    check_call_mock = mocker.async_patch('release.check_call')
    async with init_working_dir(
            access_token, repo_url, branch=branch,
    ) as other_directory:
        assert os.path.exists(other_directory)
    assert not os.path.exists(other_directory)

    calls = check_call_mock.call_args_list
    assert [call[0][0] for call in calls] == [
        ['git', 'init', '-q'],
        ['git', 'remote', 'add', 'origin', url_with_access_token(access_token, repo_url)],
        ['git', 'fetch', '--tags', '-q'],
        ['git', 'checkout', "master" if branch is None else branch, '-q'],
    ]


async def test_init_working_dir_real():
    """make sure init_working_dir can pull and checkout a real repo"""
    # the fake access token won't matter here since this operation is read-only
    repo_url = "https://github.com/mitodl/release-script.git"
    access_token = ''
    async with init_working_dir(
            access_token, repo_url,
    ) as other_directory:
        assert os.path.exists(other_directory)
        check_call(["git", "status"])
    assert not os.path.exists(other_directory)


async def test_gitconfig():
    """make sure we have a valid gitconfig file"""
    with TemporaryDirectory() as directory:
        check_call(["git", "init"], cwd=directory)
        with open(os.path.join(directory, ".git", "config"), "w") as new_config:
            with open(os.path.join(".gitconfig")) as old_config:
                new_config.write(old_config.read())
        check_call(["git", "status"], cwd=directory)


def make_empty_commit(user, message):
    """Helper function to create an empty commit as a particular user"""
    check_call(["git", "config", "user.email", "{}@example.com".format(user)])
    check_call(["git", "config", "user.name", user])
    check_call(["git", "commit", "--allow-empty", "-m", message])


def assert_starts_with(lines, expected):
    """Helper method to assert that each line starts with the line in the expected list"""
    assert len(lines) == len(expected)
    for i, line in enumerate(lines):
        assert line.startswith(expected[i])


@pytest.mark.parametrize("with_checkboxes", [True, False])
async def test_create_release_notes(test_repo, with_checkboxes):
    """create_release_notes should create release notes for a particular release, possibly with checkboxes"""
    make_empty_commit("initial", "initial commit")
    check_call(["git", "tag", "v0.0.1"])
    make_empty_commit("User 1", "Commit #1")
    make_empty_commit("User 2", "Commit #2")
    make_empty_commit("User 2", "Commit #3")

    notes = await create_release_notes("0.0.1", with_checkboxes=with_checkboxes, base_branch="master")
    lines = notes.split("\n")
    if with_checkboxes:
        assert_starts_with(lines, [
            "## User 2",
            "  - [ ] Commit #3",
            "  - [ ] Commit #2",
            "",
            "## User 1",
            "  - [ ] Commit #1",
            "",
        ])
    else:
        assert_starts_with(lines, [
            '- Commit #3',
            '- Commit #2',
            '- Commit #1',
            "",
        ])


@pytest.mark.parametrize("with_checkboxes", [True, False])
async def test_create_release_notes_empty(test_repo, with_checkboxes):
    """create_release_notes should return a string saying there are no new commits"""
    make_empty_commit("initial", "initial commit")
    check_call(["git", "tag", "v0.0.1"])

    notes = await create_release_notes("0.0.1", with_checkboxes=with_checkboxes, base_branch="master")
    assert notes == "No new commits"


@pytest.mark.parametrize("with_checkboxes", [True, False])
async def test_create_release_notes_amp(test_repo, with_checkboxes):
    """create_release_notes should not escape html entities"""
    make_empty_commit("initial", "initial commit")
    check_call(["git", "tag", "v0.0.1"])
    make_empty_commit("User 1", "Commit & ' \"")

    notes = await create_release_notes("0.0.1", with_checkboxes=with_checkboxes, base_branch="master")
    assert "Commit & \' \"" in notes


@pytest.mark.parametrize("has_commits", [True, False])
async def test_any_new_commits(test_repo, has_commits):
    """any_new_commits should return a bool value saying whether there are new commits or not"""
    make_empty_commit("initial", "initial commit")
    check_call(["git", "tag", "v0.0.1"])

    if has_commits:
        make_empty_commit("User 1", "After 1")
    check_call(["git", "tag", "v0.0.2"])

    assert await any_new_commits("0.0.1", base_branch="master") is has_commits


async def test_update_release_notes(test_repo):
    """update_release_notes should update the existing release notes and add new notes for the new commits"""
    check_call(["git", "checkout", "master"])
    check_call(["git", "tag", "v0.2.0"])

    make_empty_commit("User 1", "Before")
    check_call(["git", "tag", "v0.3.0"])
    await update_release_notes("0.2.0", "0.3.0", base_branch="master")

    make_empty_commit("User 2", "After 1")
    make_empty_commit("User 2", "After 2")
    make_empty_commit("User 3", "After 3")
    await update_release_notes("0.3.0", "0.4.0", base_branch="master")

    assert open("RELEASE.rst").read() == """Release Notes
=============

Version 0.4.0
-------------

- After 3
- After 2
- After 1
- Release 0.3.0

Version 0.3.0
-------------

- Before

Version 0.2.0
-------------

- Added missing release_notes template files.
- Changed to ``django-server-status``.
- Added logging message for webhooks with non-200 responses.
- Removed ``dredd``, removed unused HTTP methods from API, added unit tests.
- Added generator script for life-like data.
- Implemented receiving JSON on ``create-ccx`` endpoint.
- Added support for course modules.
- Fixed ``requests`` installation.
- Added additional logging.
- Incoming requests send uuids, not course ids.
- Included the course/module's instance in webhook.
- disabled SSL being necessary for celery.
- Added status.
- Enabled ``redis`` in the web container.
- Made webhook fixes.
- Added API endpoint to create ccxs on edX.
- Now fetching module listing through course structure api.

Version 0.1.0
-------------

- Initial release
"""


async def test_update_release_notes_initial(test_repo):
    """If RELEASE.rst doesn't exist update_release_notes should create it"""
    check_call(["git", "checkout", "master"])
    check_call(["git", "tag", "v0.2.0"])

    make_empty_commit("User 1", "A commit between 2 and 3")
    check_call(["git", "tag", "v0.3.0"])
    os.unlink("RELEASE.rst")
    await update_release_notes("0.2.0", "0.3.0", base_branch="master")

    assert open("RELEASE.rst").read() == """Release Notes
=============

Version 0.3.0
-------------

- A commit between 2 and 3

"""


async def test_verify_new_commits(test_repo):
    """verify_new_commits should error if there is no commit to put in the release"""
    check_call(["git", "tag", "v0.0.1"])
    check_call(["git", "checkout", "master"])

    with pytest.raises(Exception) as ex:
        await verify_new_commits("0.0.1", base_branch="master")
    assert ex.value.args[0] == 'No new commits to put in release'
    make_empty_commit("User 1", "  Release 0.0.1  ")
    # No exception
    await verify_new_commits("0.0.1", base_branch="master")


async def test_generate_release_pr(mocker, test_repo):
    """generate_release_pr should create a PR"""
    access_token = 'access_token'
    repo_url = 'http://repo.url.fake/'
    old_version = '1.2.3'
    new_version = '4.5.6'
    body = 'body'

    create_pr_mock = mocker.async_patch('release.create_pr')
    create_release_notes_mock = mocker.async_patch('release.create_release_notes', return_value=body)
    await generate_release_pr(
        github_access_token=access_token,
        repo_url=repo_url,
        old_version=old_version,
        new_version=new_version,
        base_branch="master",
    )
    create_pr_mock.assert_called_once_with(
        github_access_token=access_token,
        repo_url=repo_url,
        title="Release {}".format(new_version),
        body=body,
        head="release-candidate",
        base="release",
    )
    create_release_notes_mock.assert_called_once_with(old_version, with_checkboxes=True, base_branch="master")


async def test_fetch_release_hash(mocker):
    """
    fetch_release_hash should download the release hash at the URL
    """
    sha1_hash = b"X" * 40
    url = 'a_url'
    get_mock = mocker.async_patch('client_wrapper.ClientWrapper.get', return_value=mocker.Mock(
        content=sha1_hash
    ))
    assert await fetch_release_hash(url) == sha1_hash.decode()
    get_mock.assert_called_once_with(mocker.ANY, url)
    get_mock.return_value.raise_for_status.assert_called_once_with()


async def test_get_version_tag(mocker):
    """
    get_version_tag should return the git hash of the directory
    """
    a_hash = b'hash'
    mocker.async_patch('version.check_output', return_value=a_hash)
    assert await get_version_tag('github', 'http://github.com/mitodl/doof.git', 'commit') == a_hash.decode()


@pytest.mark.parametrize("hotfix_hash", ["", "abcdef"])
async def test_release(mocker, hotfix_hash):
    """release should perform a release"""
    token = "token"
    repo_url = 'http://github.com/fake/repo.git'
    old_version = "6.5.4"
    new_version = '9.8.7'
    branch = 'branch'
    base_branch = "release-candidate" if hotfix_hash else "master"

    validate_mock = mocker.async_patch('release.validate_dependencies')
    check_call_mock = mocker.async_patch('release.check_call')
    verify_mock = mocker.async_patch('release.verify_new_commits')
    update_release_mock = mocker.async_patch('release.update_release_notes')
    update_version_mock = mocker.patch('release.update_version', return_value=old_version)
    generate_mock = mocker.async_patch('release.generate_release_pr')

    await release(
        github_access_token=token,
        repo_url=repo_url,
        new_version=new_version,
        branch=branch,
        commit_hash=hotfix_hash
    )

    validate_mock.assert_called_once_with()
    generate_mock.assert_called_once_with(
        github_access_token=token,
        repo_url=repo_url,
        old_version=old_version,
        new_version=new_version,
        base_branch=base_branch,
    )
    verify_mock.assert_called_once_with(old_version, base_branch=base_branch)
    update_release_mock.assert_called_once_with(old_version, new_version, base_branch=base_branch)
    update_version_mock.assert_called_once_with(new_version)
    check_call_mock.assert_any_call(["git", "checkout", "-qb", "release-candidate"])
    if hotfix_hash:
        check_call_mock.assert_any_call(["git", "cherry-pick", hotfix_hash])
    check_call_mock.assert_any_call(
        ["git", "push", "--force", "-q", "origin", "release-candidate:release-candidate"]
    )


async def test_release_failed_cherry_pick(mocker):
    """release should raise an exception if the cherry pick fails"""
    commit_hash = "does_not_exist"

    def fake_check_call(args):
        if args[1] == "cherry-pick":
            raise CalledProcessError(128, "git")

    mocker.async_patch('release.check_call', side_effect=fake_check_call)

    with pytest.raises(ReleaseException) as ex:
        await release(
            github_access_token="token",
            repo_url="http://github.com/repo/url.git",
            new_version="9.8.7",
            branch="branch",
            commit_hash=commit_hash
        )

    assert ex.value.args[0] == f'Cherry pick failed for the given hash {commit_hash}'
