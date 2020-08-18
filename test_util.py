"""Utility functions for testing"""
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime, timezone
import gzip
import os
from shutil import copyfileobj
from tempfile import (
    TemporaryFile,
    TemporaryDirectory,
)
import subprocess

from constants import SCRIPT_DIR
from github import Issue, PullRequest
from markdown import ParsedIssue


TEST_ORG = "test-org"
TEST_REPO = "test-repo"


def sync_check_call(*args, cwd, **kwargs):
    """Helper function which enforces cwd argument"""
    return subprocess.check_call(*args, cwd=cwd, **kwargs)


def sync_call(*args, cwd, **kwargs):
    """Helper function which enforces cwd argument"""
    return subprocess.call(*args, cwd=cwd, **kwargs)


@contextmanager
def make_test_repo():
    """
    Create a temporary directory with the test repo, similar to init_working_dir
    but without connecting to the internet
    """
    with TemporaryDirectory() as directory:
        sync_check_call(["git", "init", "--quiet"], cwd=directory)
        with gzip.open(
            os.path.join(SCRIPT_DIR, "test-repo.gz"), "rb"
        ) as test_repo_file:
            # Passing this handle directly to check_call(...) below doesn't work, the data remains
            # compressed. Why read() decompresses the data but passing the file object doesn't:
            # https://bugs.python.org/issue24358
            with TemporaryFile("wb") as temp_file:
                copyfileobj(test_repo_file, temp_file)
                temp_file.seek(0)

                sync_check_call(
                    ["git", "fast-import", "--quiet"], stdin=temp_file, cwd=directory
                )
        sync_check_call(["git", "checkout", "--quiet", "master"], cwd=directory)
        yield directory


def async_wrapper(mocked):
    """Wrap sync functions with a simple async wrapper"""

    async def async_func(*args, **kwargs):
        return mocked(*args, **kwargs)

    return async_func


def async_context_manager_yielder(value):
    """Simple async context manager which yields a value"""

    @asynccontextmanager
    async def async_context_manager(*args, **kwargs):  # pylint: disable=unused-argument
        yield value

    return async_context_manager


async def async_gen_wrapper(iterable):
    """Helper method to convert an iterable to an async iterable"""
    for item in iterable:
        yield item


def make_issue(number):
    """Helper method to create a fake Issue and ParsedIssue given a number"""
    return Issue(
        number=number,
        title=f"Issue {number}",
        status="closed",
        org=TEST_ORG,
        repo=TEST_REPO,
        updatedAt=datetime(2019, 6, 5, tzinfo=timezone.utc),
        url="http://b.net/example/uri",
    )


def make_parsed_issue(number, closes):
    """Helper method to create a fake ParsedIssue given a number"""
    return ParsedIssue(
        issue_number=number, closes=closes, org=TEST_ORG, repo=TEST_REPO,
    )


def make_pr(number, body):
    """Helper method to create a fake PullRequest"""
    return PullRequest(
        body=body,
        title="PR title",
        number=number,
        org=TEST_ORG,
        repo=TEST_REPO,
        url="http://a.net/example/url",
        updatedAt=datetime(2020, 1, 1, tzinfo=timezone.utc).date(),
    )
