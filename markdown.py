"""Markdown parsing functions"""

from collections import namedtuple
import re


ParsedIssue = namedtuple("ParsedIssue", ["issue_number", "closes", "org", "repo"])


def _make_issue_number_regex():
    """Create regex to extract issue number and other useful things"""
    # See https://help.github.com/en/github/writing-on-github/autolinked-references-and-urls

    closes_prefix = r"(?P<closes>(fixes|closes))?(\s+|^)"
    # org and repo are named different because it's not allowed to have two groups named the same in the regex
    # even if they are separated with a |
    prefixes = [
        r"(https://github.com/(?P<org1>[^/\s]+)/(?P<repo1>[^/\s]+)/issues/)",
        r"(?P<org2>[^/\s]+)/(?P<repo2>[^/\s]+)#",
        r"#",
        r"GH-",
    ]
    issue_number_pattern = r"(?P<issue_number>\d+)"
    pattern = f"{closes_prefix}({'|'.join([f'{prefix}' for prefix in prefixes])}){issue_number_pattern}"
    return re.compile(pattern, re.IGNORECASE)


REGEX = _make_issue_number_regex()


def parse_linked_issues(pull_request):
    """
    Parse markdown for linked issues

    Args:
        pull_request (PullRequest): Information about a pull request

    Returns:
        list of ParsedIssue: parsed issue numbers and their context
    """
    parsed_issues = []
    for match in REGEX.finditer(pull_request.body):
        groups = match.groupdict()
        parsed_issues.append(
            ParsedIssue(
                issue_number=int(groups.get("issue_number")),
                # org1 and org2 match different groups in the regex. There should only be one which matches since they
                # are separated with an |.
                # If org or repo are None, that means the issue number was provided without that context, which means
                # it's part of the same org/repo as the pull request.
                org=groups.get("org1") or groups.get("org2") or pull_request.org,
                repo=groups.get("repo1") or groups.get("repo2") or pull_request.repo,
                closes=groups.get("closes") is not None,
            )
        )
    return parsed_issues
