"""Test version functions"""
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from constants import (
    DJANGO,
    HUGO,
    LIBRARY_TYPE,
    NPM,
    SETUPTOOLS,
    WEB_APPLICATION_TYPE,
)
from repo_info import RepoInfo
from version import (
    get_commit_oneline_message,
    get_version_tag,
    get_project_version,
    UpdateVersionException,
    update_version,
    update_python_version_in_file,
    update_npm_version,
)


pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize("readonly", [True, False])
async def test_update_python_version_settings(test_repo, test_repo_directory, readonly):
    """
    update_python_version should return the old version and replace the appropriate file's text with the new version
    """
    new_version = "9.9.99"
    path = os.path.join(test_repo_directory, "ccxcon/settings.py")

    old_lines = open(path).readlines()

    old_version = await update_version(
        repo_info=test_repo,
        new_version=new_version,
        working_dir=test_repo_directory,
        readonly=readonly,
    )
    assert old_version == "0.2.0"
    new_lines = open(path).readlines()

    assert len(old_lines) == len(new_lines)

    diff_count = 0
    for old_line, new_line in zip(old_lines, new_lines):
        if old_line != new_line:
            diff_count += 1

    assert diff_count == (0 if readonly else 1)

    found_new_version = False
    with open(path) as f:
        for line in f.readlines():
            if line == 'VERSION = "{}"\n'.format(new_version):
                found_new_version = True
                break
    assert found_new_version is not readonly


@pytest.mark.parametrize("readonly", [True, False])
async def test_update_python_version_init(test_repo_directory, test_repo, readonly):
    """If we detect a version in a __init__.py file we should update it properly"""
    old_version = "1.2.3"
    test_repo_directory = Path(test_repo_directory)
    os.unlink(test_repo_directory / "ccxcon" / "settings.py")
    with open(test_repo_directory / "ccxcon" / "__init__.py", "w") as f:
        f.write("__version__ = '{}'".format(old_version))
    new_version = "4.5.6"
    assert (
        await update_version(
            repo_info=test_repo,
            new_version=new_version,
            working_dir=test_repo_directory,
            readonly=readonly,
        )
        == old_version
    )

    found_new_version = False
    with open(test_repo_directory / "ccxcon" / "__init__.py") as f:
        for line in f.readlines():
            if line.strip() == f'__version__ = "{new_version}"':
                found_new_version = True
                break
    assert found_new_version is not readonly


@pytest.mark.parametrize("readonly", [True, False])
async def test_update_python_version_setup(test_repo_directory, test_repo, readonly):
    """If we detect a version in setup.py we should update it properly, if readonly is set"""
    old_version = "0.2.0"
    os.unlink(os.path.join(test_repo_directory, "ccxcon/settings.py"))
    with open(os.path.join(test_repo_directory, "setup.py"), "w") as f:
        f.write(
            """
setup(
    name='pylmod',
    version='0.2.0',
    license='BSD',
    author='MIT ODL Engineering',
    zip_safe=True,
)        """
        )
    new_version = "4.5.6"
    assert (
        await update_version(
            repo_info=test_repo,
            new_version=new_version,
            working_dir=test_repo_directory,
            readonly=readonly,
        )
        == old_version
    )

    found_new_version = False
    with open(os.path.join(test_repo_directory, "setup.py")) as f:
        for line in f.readlines():
            if line.strip() == "version='{}',".format(new_version):
                found_new_version = True
                break
    assert found_new_version is not readonly


@pytest.mark.parametrize("readonly", [True, False])
async def test_update_python_version_missing(test_repo_directory, test_repo, readonly):
    """If there is no version we should return None"""
    os.unlink(os.path.join(test_repo_directory, "ccxcon/settings.py"))
    contents = """
setup(
    name='pylmod',
)        """
    with open(os.path.join(test_repo_directory, "setup.py"), "w") as f:
        f.write(contents)
    with pytest.raises(UpdateVersionException) as ex:
        await update_version(
            repo_info=test_repo,
            new_version="4.5.6",
            working_dir=test_repo_directory,
            readonly=readonly,
        )
    assert ex.value.args[0] == "Unable to find previous version number"


@pytest.mark.parametrize("readonly", [True, False])
async def test_update_python_version_duplicate(
    test_repo_directory, test_repo, readonly
):
    """If there are two detected versions in different files we should raise an exception"""
    contents = """
setup(
    name='pylmod',
    version='1.2.3',
)        """
    with open(os.path.join(test_repo_directory, "setup.py"), "w") as f:
        f.write(contents)
    with pytest.raises(UpdateVersionException) as ex:
        await update_version(
            repo_info=test_repo,
            new_version="4.5.6",
            working_dir=test_repo_directory,
            readonly=readonly,
        )
    assert (
        ex.value.args[0]
        == "Found at least two files with updatable versions: settings.py and setup.py"
    )


@pytest.mark.parametrize("readonly", [True, False])
async def test_update_python_version_duplicate_same_file(
    test_repo_directory, test_repo, readonly
):
    """If there are two detected versions in the same file we should raise an exception"""
    contents = """
setup(
    name='pylmod',
    version='1.2.3',
    version='4.5.6',
)        """
    with open(os.path.join(test_repo_directory, "setup.py"), "w") as f:
        f.write(contents)
    with pytest.raises(UpdateVersionException) as ex:
        await update_version(
            repo_info=test_repo,
            new_version="4.5.6",
            working_dir=test_repo_directory,
            readonly=readonly,
        )
    assert ex.value.args[0] == "Expected only one version for setup.py but found 2"


async def test_get_version_tag(mocker):
    """
    get_version_tag should return the git hash of the directory
    """
    a_hash = b"hash"
    mocker.async_patch("version.check_output", return_value=a_hash)
    assert (
        await get_version_tag(
            github_access_token="github",
            repo_url="http://github.com/mitodl/doof.git",
            commit_hash="commit",
        )
        == a_hash.decode()
    )


async def test_get_commit_oneline_message(mocker):
    """
    get_commit_oneline_message should return the commit message and a piece of the commit hash
    """
    message = b"abc123 A useful pull request was merged (#143)"
    mocker.async_patch("version.check_output", return_value=message)
    assert (
        await get_commit_oneline_message(
            github_access_token="github",
            repo_url="http://github.com/mitodl/doof.git",
            commit_hash="commit",
        )
        == message.decode()
    )


@pytest.mark.parametrize("readonly", [True, False])
@pytest.mark.parametrize(
    "filename,line, expected_output",
    [
        ("settings.py", 'VERSION = "0.34.56"\n', 'VERSION = "0.123.456"\n'),
        ("__init__.py", "__version__ = '0.34.56'\n", '__version__ = "0.123.456"\n'),
        ("setup.py", '    version="0.34.56",\n', '    version="0.123.456",\n'),
    ],
)
async def test_update_python_version_in_file(filename, line, expected_output, readonly):
    """update_python_version_in_file should update the version in the file and return the old version, if found"""
    old_version = "0.34.56"
    new_version = "0.123.456"
    with TemporaryDirectory() as base:
        path = Path(base) / filename
        with open(path, "w") as f:
            f.write("text")
        retrieved_version = update_python_version_in_file(
            root=base, filename=filename, new_version=new_version, readonly=readonly
        )
        assert retrieved_version is None

        with open(path, "w") as f:
            f.write(line)

        retrieved_version = update_python_version_in_file(
            root=base, filename=filename, new_version=new_version, readonly=readonly
        )
        assert retrieved_version == old_version

        with open(path) as f:
            lines = f.readlines()

        if readonly:
            assert new_version not in "\n".join(lines)
        else:
            version_line = [line for line in lines if new_version in line][0]
            assert version_line == expected_output


@pytest.mark.parametrize("readonly", [True, False])
async def test_update_npm_version(readonly):
    """update version for an npm package"""
    old_version = "0.76.54"
    new_version = "0.99.99"

    with TemporaryDirectory() as working_dir:
        package_json_path = Path(working_dir) / "package.json"
        with open(package_json_path, "w") as f:
            json.dump({"version": old_version}, f)

        received = await update_npm_version(
            new_version=new_version, working_dir=working_dir, readonly=readonly
        )
        assert received == old_version
        with open(package_json_path) as f:
            assert json.load(f) == {"version": old_version if readonly else new_version}


# pylint: disable=too-many-arguments
@pytest.mark.parametrize("readonly", [True, False])
@pytest.mark.parametrize(
    "project_type, packaging_tool, web_application_type, expected_python, expected_js",
    [
        [WEB_APPLICATION_TYPE, None, DJANGO, True, False],
        [WEB_APPLICATION_TYPE, None, HUGO, False, True],
        [LIBRARY_TYPE, SETUPTOOLS, None, True, False],
        [LIBRARY_TYPE, NPM, None, False, True],
    ],
)
async def test_update_version(
    mocker,
    test_repo,
    project_type,
    packaging_tool,
    web_application_type,
    expected_python,
    expected_js,
    readonly,
):
    """Call update_version on project"""
    repo_info = RepoInfo(
        **{
            **test_repo._asdict(),
            "project_type": project_type,
            "packaging_tool": packaging_tool,
            "web_application_type": web_application_type,
        }
    )
    new_version = "12.34.56"
    working_dir = "/tmp/a/directory"

    update_py_mock = mocker.patch("version.update_python_version")
    update_js_mock = mocker.async_patch("version.update_npm_version")

    await update_version(
        repo_info=repo_info,
        new_version=new_version,
        working_dir=working_dir,
        readonly=readonly,
    )

    if expected_python:
        update_py_mock.assert_called_once_with(
            new_version=new_version,
            working_dir=working_dir,
            readonly=readonly,
        )
    else:
        assert update_py_mock.called is False

    if expected_js:
        update_js_mock.assert_called_once_with(
            new_version=new_version,
            working_dir=working_dir,
            readonly=readonly,
        )
    else:
        assert update_js_mock.called is False


async def test_get_project_version(mocker, test_repo):
    """
    get_project_version should return the latest version without making modifications
    """
    update_version_mock = mocker.async_patch("version.update_version")
    working_dir = "/tmp"
    await get_project_version(repo_info=test_repo, working_dir=working_dir)
    update_version_mock.assert_called_once_with(
        repo_info=test_repo, new_version="9.9.9", working_dir=working_dir, readonly=True
    )
