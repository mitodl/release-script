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
    init_working_dir,
    parse_version_from_line,
    update_version,
    update_version_in_file,
    validate_dependencies,
)


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


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


def test_update_version(test_repo):
    """update_version should return the old version and replace the appropriate file's text with the new version"""
    new_version = "9.9.99"
    old_version = update_version(new_version)
    assert old_version == "0.2.0"

    found_new_version = False
    with open("ccxcon/settings.py") as f:
        for line in f.readlines():
            if line.startswith("VERSION = \"{}\"".format(new_version)):
                found_new_version = True
                break
    assert found_new_version, "Unable to find updated version"


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
    for dependency in ('node', 'hub', 'git', 'git-release-notes'):
        dependency_exists_stub.assert_any_call(dependency)

        with patch(
            'release.dependency_exists',
            # the cell-var-from-loop warning can be ignored because this function is executed
            # immediately after its definition
            side_effect=lambda _dependency: _dependency != dependency,  # pylint: disable=cell-var-from-loop
        ), pytest.raises(DependencyException):
            validate_dependencies()


def test_parse_version_from_line():
    """parse_version_from_line should parse version from the line in the file"""
    assert parse_version_from_line("version = '0.34.56'") == "0.34.56"
    assert parse_version_from_line("VERSION=\"0.34.56\"") == "0.34.56"


@pytest.mark.parametrize("filename,line", [
    ('settings.py', 'VERSION = \"0.34.56\"'),
    ('__init__.py', '__version__ = \'0.34.56\''),
    ('setup.py', 'version=\'0.34.56\',')
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


@pytest.mark.parametrize("with_checkboxes", [True, False])
def test_create_release_notes(test_repo, with_checkboxes):
    """create_release_notes should create release notes for a particular release, possibly with checkboxes"""
    make_empty_commit("initial", "initial commit")
    check_call(["git", "tag", "v0.0.1"])
    make_empty_commit("User 1", "Commit #1")
    make_empty_commit("User 2", "Commit #2")
    make_empty_commit("User 2", "Commit #3")

    lines = create_release_notes("0.0.1", with_checkboxes=with_checkboxes).split("\n")
    lines = [line for line in lines if line]
    if with_checkboxes:
        assert "## User 2" in lines[0]
        assert "- [ ] Commit #3" in lines[1]
        assert "- [ ] Commit #2" in lines[2]
        assert "## User 1" in lines[3]
        assert "- [ ] Commit #1" in lines[4]
    else:
        assert lines == [
            '- Commit #3',
            '- Commit #2',
            '- Commit #1',
        ]
