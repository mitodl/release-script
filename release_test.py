"""Tests for release script"""
import gzip
import os
from shutil import copyfileobj
from subprocess import check_call
from tempfile import (
    TemporaryDirectory,
    TemporaryFile,
)
from unittest.mock import patch

import pytest

from release import (
    create_release_notes,
    dependency_exists,
    DependencyException,
    GIT_RELEASE_NOTES_PATH,
    init_working_dir,
    SCRIPT_DIR,
    update_release_notes,
    UpdateVersionException,
    update_version,
    update_version_in_file,
    validate_dependencies,
    verify_new_commits,
)


# pylint: disable=redefined-outer-name, unused-argument
@pytest.fixture
def test_repo():
    """Initialize the testing repo from the gzipped file"""
    pwd = os.getcwd()

    try:
        with TemporaryDirectory() as directory:
            os.chdir(directory)
            check_call(["git", "init", "--quiet"])
            with gzip.open(os.path.join(SCRIPT_DIR, "test-repo.gz"), "rb") as test_repo_file:
                # Passing this handle directly to check_call(...) below doesn't work, the data remains
                # compressed. Why read() decompresses the data but passing the file object doesn't:
                # https://bugs.python.org/issue24358
                with TemporaryFile("wb") as temp_file:
                    copyfileobj(test_repo_file, temp_file)
                    temp_file.seek(0)

                    check_call(["git", "fast-import", "--quiet"], stdin=temp_file)
            check_call(["git", "checkout", "--quiet", "master"])
            yield
    finally:
        os.chdir(pwd)


def test_update_version_settings(test_repo):
    """update_version should return the old version and replace the appropriate file's text with the new version"""
    new_version = "9.9.99"
    old_version = update_version(new_version)
    assert old_version == "0.2.0"

    found_new_version = False
    with open("ccxcon/settings.py") as f:
        for line in f.readlines():
            if line.strip() == "VERSION = \"{}\"".format(new_version):
                found_new_version = True
                break
    assert found_new_version, "Unable to find updated version"


def test_update_version_init(test_repo):
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


def test_update_version_setup(test_repo):
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


def test_update_version_missing(test_repo):
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


def test_update_version_duplicate(test_repo):
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


def test_update_version_duplicate_same_file(test_repo):
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


def test_dependency_exists():
    """dependency_exists should check that the command exists on the system"""
    assert dependency_exists("ls")
    assert not dependency_exists("xyzzy")


def test_checkout():
    """checkout should change the """


def test_validate_dependencies():
    """validate_dependencies should raise an exception if a dependency is missing or invalid"""
    with patch('release.dependency_exists', return_value=True) as dependency_exists_stub:
        validate_dependencies()
    for dependency in ('node', 'git', GIT_RELEASE_NOTES_PATH):
        dependency_exists_stub.assert_any_call(dependency)

        with patch(
            'release.dependency_exists',
            # the cell-var-from-loop warning can be ignored because this function is executed
            # immediately after its definition
            side_effect=lambda _dependency: _dependency != dependency,  # pylint: disable=cell-var-from-loop
        ), pytest.raises(DependencyException):
            validate_dependencies()


@pytest.mark.parametrize("filename,line", [
    ('settings.py', 'VERSION = \"0.34.56\"'),
    ('__init__.py', '__version__ = \'0.34.56\''),
])
def test_update_version_in_file(filename, line):
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
def test_validate_node_version(major):
    """validate_dependencies should check that the major node.js version is new enough"""
    node_version = "v{}.2.1".format(major).encode()

    with patch(
        'release.dependency_exists', return_value=True,
    ), patch(
        'release.check_output', return_value=node_version,
    ):
        if major >= 6:
            validate_dependencies()
        else:
            with pytest.raises(DependencyException):
                validate_dependencies()


def test_init_working_dir(test_repo):
    """init_working_dir should initialize a valid git repo, and clean up after itself"""
    with init_working_dir(os.path.abspath(".git")) as other_directory:
        os.chdir(other_directory)
        check_call(["git", "status"])
    assert not os.path.exists(other_directory)


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
def test_create_release_notes(test_repo, with_checkboxes):
    """create_release_notes should create release notes for a particular release, possibly with checkboxes"""
    make_empty_commit("initial", "initial commit")
    check_call(["git", "tag", "v0.0.1"])
    make_empty_commit("User 1", "Commit #1")
    make_empty_commit("User 2", "Commit #2")
    make_empty_commit("User 2", "Commit #3")

    notes = create_release_notes("0.0.1", with_checkboxes=with_checkboxes)
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


def test_update_release_notes(test_repo):
    """update_release_notes should update the existing release notes and add new notes for the new commits"""
    check_call(["git", "checkout", "master"])
    check_call(["git", "tag", "v0.2.0"])

    make_empty_commit("User 1", "Before")
    check_call(["git", "tag", "v0.3.0"])
    update_release_notes("0.2.0", "0.3.0")

    make_empty_commit("User 2", "After 1")
    make_empty_commit("User 2", "After 2")
    make_empty_commit("User 3", "After 3")
    update_release_notes("0.3.0", "0.4.0")

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


def test_update_release_notes_initial(test_repo):
    """If RELEASE.rst doesn't exist update_release_notes should create it"""
    check_call(["git", "checkout", "master"])
    check_call(["git", "tag", "v0.2.0"])

    make_empty_commit("User 1", "A commit between 2 and 3")
    check_call(["git", "tag", "v0.3.0"])
    os.unlink("RELEASE.rst")
    update_release_notes("0.2.0", "0.3.0")

    assert open("RELEASE.rst").read() == """Release Notes
=============

Version 0.3.0
-------------

- A commit between 2 and 3

"""


def test_verify_new_commits(test_repo):
    """verify_new_commits should error if there is no commit to put in the release"""
    check_call(["git", "tag", "v0.0.1"])
    check_call(["git", "checkout", "master"])

    with pytest.raises(Exception) as ex:
        verify_new_commits("0.0.1")
    assert ex.value.args[0] == 'No new commits to put in release'
    make_empty_commit("User 1", "  Release 0.0.1  ")
    # No exception
    verify_new_commits("0.0.1")
