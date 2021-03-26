"""Functions for publishing"""
import os
from pathlib import Path

from async_subprocess import (
    call,
    check_call,
)
from constants import (
    NPM,
    SETUPTOOLS,
)
from lib import (
    init_working_dir,
    virtualenv,
)


async def upload_to_pypi(project_dir):
    """
    Upload a version of a project to PYPI

    Args:
        project_dir (str): The project directory
    """
    async with virtualenv("python3", None) as (_, outer_environ):
        # Heroku has both Python 2 and 3 installed but the system libraries aren't configured for our use,
        # so make a virtualenv.
        async with virtualenv("python3", outer_environ) as (virtualenv_dir, environ):
            # Use the virtualenv binaries to act within that environment
            pip_path = os.path.join(virtualenv_dir, "bin", "pip")

            # Install dependencies. wheel is needed for Python 2. twine uploads the package.
            await check_call([pip_path, "install", "twine"], env=environ, cwd=project_dir)
            await upload_with_twine(
                project_dir=project_dir, virtualenv_dir=virtualenv_dir, environ=environ
            )


async def upload_with_twine(*, project_dir, virtualenv_dir, environ):  # pylint: disable=too-many-locals
    """
    Upload a version of a project to PYPI

    Args:
        project_dir (str): The location of the project to upload
        virtualenv_dir (str): The virtualenv directory where twine will be installed
        environ (dict): The environment variables to run twine with
    """
    # Set up environment variables for uploading to pypi or pypitest
    twine_env = {
        'TWINE_USERNAME': os.environ['PYPI_USERNAME'],
        'TWINE_PASSWORD': os.environ['PYPI_PASSWORD'],
    }

    python_path = os.path.join(virtualenv_dir, "bin", "python")
    twine_path = os.path.join(virtualenv_dir, "bin", "twine")

    # Create source distribution and wheel.
    await call([python_path, "setup.py", "sdist"], env=environ, cwd=project_dir)
    await call([python_path, "setup.py", "bdist_wheel"], env=environ, cwd=project_dir)
    dist_files = os.listdir(os.path.join(project_dir, "dist"))
    if len(dist_files) != 2:
        raise Exception("Expected to find one tarball and one wheel in directory")
    dist_paths = [os.path.join("dist", name) for name in dist_files]

    # Upload to pypi
    await check_call(
        [twine_path, "upload", *dist_paths],
        env={
            **environ,
            **twine_env,
        }, cwd=project_dir
    )


async def upload_to_npm(*, project_dir, npm_token):
    """
    Publish a package to the npm registry

    Args:
        project_dir (str): The project directory
        npm_token (str): A token to access the npm registry
    """
    with open(Path(project_dir) / ".npmrc", "w") as f:
        f.write(f"//registry.npmjs.org/:_authToken={npm_token}")

    await check_call(["npm", "install"], cwd=project_dir)
    await check_call(["npm", "publish", "--production=false"], cwd=project_dir)


async def publish(*, repo_info, version, github_access_token, npm_token):
    """
    Publish a package to the appropriate repository

    Args:
        repo_info (RepoInfo): The repository info
        version (str): The version of the project to upload
        github_access_token (str): The github access token
        npm_token (str): The NPM token
    """
    branch = f"v{version}"
    async with init_working_dir(github_access_token, repo_info.repo_url, branch=branch) as working_dir:
        if repo_info.packaging_tool == NPM:
            await upload_to_npm(
                npm_token=npm_token,
                project_dir=working_dir,
            )
        elif repo_info.packaging_tool == SETUPTOOLS:
            await upload_to_pypi(
                project_dir=working_dir,
            )
        else:
            raise Exception(f"Unexpected value for packaging tool {repo_info.packaging_tool} for {repo_info.name}")
