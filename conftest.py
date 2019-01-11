"""Fixtures for tests"""
from contextlib import contextmanager
import gzip
import os
from shutil import copyfileobj
from tempfile import (
    TemporaryFile,
    TemporaryDirectory,
)
from subprocess import check_call

import pytest
import pytz

from bot import (
    LIBRARY_TYPE,
    WEB_APPLICATION_TYPE,
)
from release import SCRIPT_DIR
from repo_info import RepoInfo


SETUP_PY = """
from setuptools import setup, find_packages

setup(
    name='ccxcon',
    version='0.2.0',
    license='AGPLv3',
    author='MIT ODL Engineering',
    author_email='odl-engineering@mit.edu',
    url='http://github.com/mitodl/ccxcon',
    description="CCX Connector",
    # long_description=README,
    packages=find_packages(),
    classifiers=[
        'Development Status :: 2 - Pre-Alpha',
        'Intended Audience :: Developers',
        'Intended Audience :: Education',
        'Programming Language :: Python',
    ],
    include_package_data=True,
    zip_safe=False,
)
"""


@contextmanager
def _make_temp_repo():
    """
    Create a temporary directory with the test repo, similar to init_working_dir
    but without connecting to the internet
    """
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


WEB_TEST_REPO_INFO = RepoInfo(
    name='doof_repo',
    repo_url='http://github.com/mitodl/doof.git',
    prod_hash_url='http://doof.example.com/hash.txt',
    rc_hash_url='http://doof-rc.example.com/hash.txt',
    channel_id='doof',
    project_type=WEB_APPLICATION_TYPE,
    python2=False,
    python3=True,
    announcements=False,
)


@pytest.fixture
def test_repo():
    """Initialize the testing repo from the gzipped file"""
    with _make_temp_repo():
        yield WEB_TEST_REPO_INFO


LIBRARY_TEST_REPO_INFO = RepoInfo(
    name='lib_repo',
    repo_url='http://github.com/mitodl/doof-lib.git',
    prod_hash_url=None,
    rc_hash_url=None,
    channel_id='doof-lib',
    project_type=LIBRARY_TYPE,
    python2=True,
    python3=False,
    announcements=False,
)


ANNOUNCEMENTS_CHANNEL = RepoInfo(
    name='doof_repo',
    repo_url=None,
    prod_hash_url=None,
    rc_hash_url=None,
    channel_id='announcement_id',
    project_type=None,
    python2=None,
    python3=None,
    announcements=True,
)


@pytest.fixture
def library_test_repo():
    """Initialize the library test repo from the gzipped file"""
    with _make_temp_repo():
        with open("setup.py", "w") as f:
            # Hacky way to convert a web application project to a library
            f.write(SETUP_PY)

        yield LIBRARY_TEST_REPO_INFO


@pytest.fixture
def timezone():
    """ Return a timezone object """
    yield pytz.timezone('America/New_York')
