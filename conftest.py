"""Fixtures for tests"""
import os

import pytest
import pytz

from bot import (
    LIBRARY_TYPE,
    WEB_APPLICATION_TYPE,
)
from repo_info import RepoInfo
from test_util import make_test_repo
from test_util import async_wrapper


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


# pylint: disable=redefined-outer-name, unused-argument
@pytest.fixture
def test_repo_directory():
    """Helper function to make a repo for testing"""
    with make_test_repo() as working_dir:
        yield working_dir


@pytest.fixture
def test_repo(test_repo_directory):
    """Initialize the testing repo from the gzipped file"""
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
def library_test_repo(test_repo_directory):
    """Initialize the library test repo from the gzipped file"""
    with open(os.path.join(test_repo_directory, "setup.py"), "w") as f:
        # Hacky way to convert a web application project to a library
        f.write(SETUP_PY)

    yield LIBRARY_TEST_REPO_INFO


@pytest.fixture
def timezone():
    """ Return a timezone object """
    yield pytz.timezone('America/New_York')


@pytest.fixture
def mocker(mocker):  # pylint: disable=redefined-outer-name
    """Override to add async_patch"""

    def async_patch(*args, **kwargs):
        """Add a helper function to patch with an async wrapped function, which is returned"""
        mocked = mocker.Mock(**kwargs)
        mocker.patch(*args, new_callable=lambda: async_wrapper(mocked))
        return mocked

    mocker.async_patch = async_patch
    return mocker
