"""
Test package uploading functions
"""
import os
from pathlib import Path
import subprocess

import pytest

from constants import (
    NPM,
    SETUPTOOLS,
)
from lib import virtualenv
from publish import upload_with_twine, upload_to_npm, upload_to_pypi, publish
from repo_info import RepoInfo
from test_util import async_context_manager_yielder


pytestmark = pytest.mark.asyncio


# pylint: disable=unused-argument
async def test_upload_with_twine(mocker, library_test_repo, library_test_repo_directory):
    """upload_with_twine should create a dist based on a version and upload to pypi or pypitest"""

    twine_env = {
        'PYPI_USERNAME': 'user',
        'PYPI_PASSWORD': 'pass',
    }

    mocker.patch.dict('os.environ', twine_env, clear=False)

    def _call(command, *args, **kwargs):
        """assert things about the call"""
        if not command[0].endswith("twine"):
            return subprocess.call(command, *args, **kwargs)

        assert kwargs['cwd'] == library_test_repo_directory
        env = kwargs['env']
        assert env['TWINE_USERNAME'] == twine_env['PYPI_USERNAME']
        assert env['TWINE_PASSWORD'] == twine_env['PYPI_PASSWORD']
        assert command[1] == "upload"
        assert len([name for name in command[-2:] if name.endswith(".whl")]) == 1
        assert len([name for name in command[-2:] if name.endswith(".tar.gz")]) == 1
        return 0

    async with virtualenv("python3", os.environ) as (virtualenv_dir, environ):
        call_mock = mocker.async_patch('async_subprocess.call', side_effect=_call)
        await upload_with_twine(
            project_dir=library_test_repo_directory, virtualenv_dir=virtualenv_dir, environ=environ
        )
    assert call_mock.call_count == 1


async def test_upload_to_npm(mocker, test_repo_directory, library_test_repo):
    """upload_to_npm should set a token then run npm publish to upload to the repository"""
    npm_token = 'npm-token'
    recorded_commands = []

    def _call(command, *, cwd, **kwargs):
        """check that the token was written correctly"""
        with open(Path(cwd) / ".npmrc") as f:
            assert f.read() == f"//registry.npmjs.org/:_authToken={npm_token}"

        recorded_commands.append(command)
        return 0

    call_mock = mocker.async_patch('async_subprocess.call', side_effect=_call)

    await upload_to_npm(project_dir=test_repo_directory, npm_token=npm_token)
    assert call_mock.call_count == 2
    assert recorded_commands == [["npm", "install", "--production=false"], ["npm", "publish"]]


async def test_upload_to_pypi(mocker, test_repo_directory, library_test_repo):
    """upload_to_pypi should call upload_with_twine"""
    twine_mocked = mocker.async_patch('publish.upload_with_twine')
    await upload_to_pypi(test_repo_directory)
    assert twine_mocked.call_count == 1


@pytest.mark.parametrize("packaging_tool", [NPM, SETUPTOOLS])
async def test_publish(mocker, test_repo_directory, library_test_repo, packaging_tool):
    """publish should call upload_to_pypi or upload_to_npm depending on the packaging_tool"""
    upload_to_pypi_mocked = mocker.async_patch('publish.upload_to_pypi')
    upload_to_npm_mocked = mocker.async_patch('publish.upload_to_npm')

    library_test_repo = RepoInfo(
        **{
            **library_test_repo._asdict(),
            "packaging_tool": packaging_tool,
        }
    )
    github_access_token = "git hub"
    npm_token = "npm token"
    version = '9.8.7'
    working_dir = "/a/working/dir"
    init_mock = mocker.patch(
        'publish.init_working_dir', side_effect=async_context_manager_yielder(working_dir)
    )
    await publish(
        repo_info=library_test_repo,
        github_access_token=github_access_token,
        npm_token=npm_token,
        version=version,
    )
    init_mock.assert_called_once_with(github_access_token, library_test_repo.repo_url, branch=f"v{version}")

    if packaging_tool == SETUPTOOLS:
        assert upload_to_npm_mocked.called is False
        upload_to_pypi_mocked.assert_called_once_with(project_dir=working_dir)
    elif packaging_tool == NPM:
        assert upload_to_pypi_mocked.called is False
        upload_to_npm_mocked.assert_called_once_with(
            project_dir=working_dir,
            npm_token=npm_token,
        )
