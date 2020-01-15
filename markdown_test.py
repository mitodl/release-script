"""Tests for markdown parser"""
import pytest

from github import PullRequest
from markdown import parse_linked_issues, ParsedIssue


ORG = "default_org"
REPO = "default_repo"


@pytest.mark.parametrize("input_text, expected_output", [
    # Linked issues should be parsed, even ending with comma
    [" see issue https://github.com/jlord/sheetsee.js/issues/26, which is ", [
        ParsedIssue(issue_number=26, org="jlord", repo="sheetsee.js", closes=False),
    ]],
    # Test that closes will close an issue, and a lack of close will not close it
    ["Closes #9876543, related to #76543, fixes #44", [
        ParsedIssue(issue_number=9876543, org=ORG, repo=REPO, closes=True),
        ParsedIssue(issue_number=76543, org=ORG, repo=REPO, closes=False),
        ParsedIssue(issue_number=44, org=ORG, repo=REPO, closes=True),
    ]],
    # Test that #xx and org/repo#xx can coexist and not be parsed as each other
    ["see #769, mitodl/mitxpro#94 and mitodl/open-discussions#76, and also #123 for more info", [
        ParsedIssue(issue_number=769, org=ORG, repo=REPO, closes=False),
        ParsedIssue(issue_number=94, org="mitodl", repo="mitxpro", closes=False),
        ParsedIssue(issue_number=76, org="mitodl", repo="open-discussions", closes=False),
        ParsedIssue(issue_number=123, org=ORG, repo=REPO, closes=False),
    ]],
    # No issue links should be parsed
    ["nothing to see here", []],
    # Parse GH-
    ["We don't use issue links like GH-543", [
        ParsedIssue(issue_number=543, org=ORG, repo=REPO, closes=False)
    ]],
    # ignore issues which are links
    ["Catch buffer overruns [#4104](https://github-redirect.dependabot.com/python-pillow/Pillow/issues/4104)", []],
    # start issue at beginning of string
    ["#654 is the issue", [
        ParsedIssue(issue_number=654, org=ORG, repo=REPO, closes=False),
    ]]
])
def test_parser(input_text, expected_output):
    """Test that parser is producing expected output"""
    pr = PullRequest(
        body=input_text,
        number=1234,
        title="title",
        updatedAt=None,
        org=ORG,
        repo=REPO,
        url=f"https://github.com/{ORG}/{REPO}.git",
    )
    assert parse_linked_issues(pr) == expected_output
