"""Functions interacting with github"""

from collections import defaultdict, namedtuple
import json
import re
import logging

from dateutil.parser import parse
from requests.exceptions import HTTPError

from client_wrapper import ClientWrapper
from constants import NO_PR_BUILD
from markdown import parse_linked_issues

log = logging.getLogger(__name__)


PullRequest = namedtuple("PullRequest", ["number", "title", "body", "updatedAt", "org", "repo", "url"])
Issue = namedtuple("Issue", ["number", "title", "status", "org", "repo", "updatedAt", "url"])


KARMA_QUERY = """
query {

  organization(login:"mitodl") {
    repositories(first: 20, orderBy: {
      field: PUSHED_AT,
      direction: DESC
    }) {
      nodes {
        name
        pullRequests(first: 100, states: [MERGED], orderBy: {
          field: UPDATED_AT
          direction: DESC,
        }) {
          nodes {
            updatedAt
            mergedAt
            assignees(first: 3) {
              nodes {
                login
                name
              }
            }
          }
        }
      }
    }
  }
}
"""


NEEDS_REVIEW_QUERY = """
query {
  organization(login:"mitodl") {
    repositories(first: 20, orderBy: {
      field: PUSHED_AT,
      direction: DESC
    }) {
      nodes {
        name
        pullRequests(first: 100, states: [OPEN], orderBy: {
          field: UPDATED_AT
          direction: DESC,
        }) {
          nodes {
            title
            url
            labels(first: 3) {
              nodes {
                name
              }
            }
            assignees(first: 1) {
              nodes {
                login
              }
            }
          }
        }
      }
    }
  }
}
"""


def make_pull_requests_query(*, org, repo, cursor):
    """
    Construct a GraphQL query getting the text of the last 100 most recently updated pull requests

    Args:
        org (str): The github org
        repo (str): The github repo
        cursor (str or None): If set, the cursor to start from for pagination
    """
    cursor_param = f", after: \"{cursor}\"" if cursor is not None else ""
    return f"""
query {{
  organization(login: "{org}") {{
    repository(name: "{repo}") {{
      pullRequests(first: 100{cursor_param}, states: [MERGED], orderBy: {{
        field: UPDATED_AT
        direction: DESC,
      }}) {{
        edges {{
          cursor
          node {{
            number
            body
            updatedAt
            url
            title
          }}
        }}
      }}
    }}
  }}
}}
    """


async def run_query(*, github_access_token, query):
    """
    Run a query using Github graphql API

    Args:
        github_access_token (str): A github access token
        query (str): A graphql query to run

    Returns:
        dict: The results of the query
    """
    endpoint = "https://api.github.com/graphql"
    query = json.dumps({"query": query})
    client = ClientWrapper()
    resp = await client.post(endpoint, data=query, headers={
        "Authorization": "Bearer {}".format(github_access_token)
    })
    resp.raise_for_status()
    return resp.json()


def github_auth_headers(github_access_token):
    """
    Create headers for authenticating requests against github

    Args:
        github_access_token (str): A github access token

    Returns:
        dict:
            Headers for authenticating a request
    """
    return {
        "Authorization": "Bearer {}".format(github_access_token),
        "Accept": "application/vnd.github.v3+json",
    }


async def create_pr(*, github_access_token, repo_url, title, body, head, base):  # pylint: disable=too-many-arguments
    """
    Create a pull request

    Args:
        github_access_token (str): A github access token
        repo_url (str): The URL of the repository to create the PR in
        title (str): The title of the PR
        body (str): The body of the PR
        head (str): The head branch for the PR
        base (str): The base branch for the PR
    """

    org, repo = get_org_and_repo(repo_url)
    endpoint = "https://api.github.com/repos/{org}/{repo}/pulls".format(
        org=org,
        repo=repo,
    )

    client = ClientWrapper()
    resp = await client.post(
        endpoint,
        headers=github_auth_headers(github_access_token),
        data=json.dumps({
            'title': title,
            'body': body,
            'head': head,
            'base': base,
        })
    )
    resp.raise_for_status()


async def fetch_pull_requests_since_date(*, github_access_token, org, repo, since):
    """
    Look up PRs between now and a given datetime

    Args:
        github_access_token (str): The github access token
        org (str): A github organization
        repo (str): A github repo
        since (date): The earliest date to request PRs

    Yields:
        PullRequest: Information about each pull request fetched
    """
    cursor = None
    while True:
        # This should hopefully not be an infinite loop because the cursor will be updated and the loop should
        # terminate once a pull request is out of the date range given.
        result = await run_query(
            github_access_token=github_access_token,
            query=make_pull_requests_query(
                org=org,
                repo=repo,
                cursor=cursor,
            )
        )

        edges = result['data']['organization']['repository']['pullRequests']['edges']
        if not edges:
            return
        cursor = edges[-1]['cursor']
        for edge in edges:
            node = edge['node']
            pr_number = node['number']
            url = node['url']
            pr_date = parse(node['updatedAt']).date()
            if pr_date < since:
                return
            title = node['title']
            if title.startswith("Release "):
                continue
            yield PullRequest(
                number=pr_number,
                title=title,
                updatedAt=pr_date,
                body=node['body'],
                org=org,
                repo=repo,
                url=url,
            )


async def fetch_issues_for_pull_requests(*, github_access_token, pull_requests):
    """
    Look up issues linked with the given pull requests

    Args:
        github_access_token (str): A github access token
        pull_requests (async_iterable of PullRequest):
            A iterable of PullRequest which contains issue numbers to be parsed in the body

    Yields:
        (PullRequest, list of (Issue, ParsedIssue))
    """
    issue_lookup = {}
    async for pull_request in pull_requests:
        parsed_issues = parse_linked_issues(pull_request)
        for parsed_issue in parsed_issues:
            if parsed_issue.issue_number not in issue_lookup:
                try:
                    issue = await get_issue(
                        github_access_token=github_access_token,
                        org=parsed_issue.org,
                        repo=parsed_issue.repo,
                        issue_number=parsed_issue.issue_number,
                    )
                    if issue is None:
                        continue
                    issue_lookup[parsed_issue.issue_number] = issue
                except HTTPError:
                    log.warning(
                        "Unable to find issue %d for %s/%s",
                        parsed_issue.issue_number,
                        parsed_issue.org,
                        parsed_issue.repo,
                    )
        yield pull_request, [
            (issue_lookup.get(parsed_issue.issue_number), parsed_issue) for parsed_issue in parsed_issues
        ]


def make_issue_release_notes(prs_and_issues):
    """
    Create release notes for PRs and linked issues

    Args:
        prs_and_issues (iterable of PullRequest, list of (Issue, ParsedIssue)):
            The PRs and issues to use to make release notes

    Returns:
        str:
            Release notes for the issues closed during the time
    """
    issue_to_prs = {}
    for pr, issue_list in prs_and_issues:
        for issue, parsed_issue in issue_list:
            if not issue or issue.status != "closed":
                continue
            if issue.number not in issue_to_prs:
                issue_to_prs[issue.number] = (issue, [])
            issue_to_prs[issue.number][1].append(
                (pr, parsed_issue)
            )

    if not issue_to_prs:
        return "No new issues closed by PR"

    return "\n".join(
        f"- {issue.title} (<{issue.url}|#{issue_number}>)" for issue_number, (issue, _) in
        sorted(issue_to_prs.items(), key=lambda tup: tup[0])
    )


async def get_issue(*, github_access_token, org, repo, issue_number):
    """
    Look up information about an issue

    Args:
        github_access_token (str): The github access token
        org (str): An organization
        repo (str): A repository
        issue_number (int): The github issue number

    Returns:
        Issue: Information about the issue
    """
    endpoint = f"https://api.github.com/repos/{org}/{repo}/issues/{issue_number}"
    client = ClientWrapper()
    response = await client.get(endpoint, headers=github_auth_headers(github_access_token))
    response.raise_for_status()
    response_json = response.json()
    if 'pull_request' in response_json:
        return

    return Issue(
        title=response_json['title'],
        number=response_json['number'],
        org=org,
        repo=repo,
        status=response_json['state'],
        updatedAt=parse(response_json['updated_at']),
        url=response_json['html_url'],
    )


async def get_pull_request(*, github_access_token, org, repo, branch):
    """
    Look up the pull request for a branch

    Args:
        github_access_token (str): The github access token
        org (str): The github organization (eg mitodl)
        repo (str): The github repository (eg micromasters)
        branch (str): The name of the associated branch

    Returns:
        dict: The information about the pull request
    """
    endpoint = "https://api.github.com/repos/{org}/{repo}/pulls".format(
        org=org,
        repo=repo,
    )

    client = ClientWrapper()
    response = await client.get(
        endpoint,
        headers=github_auth_headers(github_access_token),
    )
    response.raise_for_status()
    pulls = response.json()
    pulls = [pull for pull in pulls if pull['head']['ref'] == branch]
    if not pulls:
        return None
    elif len(pulls) > 1:
        # Shouldn't happen since we look up by branch
        raise Exception("More than one pull request for the branch {}".format(branch))

    return pulls[0]


async def calculate_karma(*, github_access_token, begin_date, end_date):
    """
    Calculate number of merged pull requests by assigned reviewer

    Args:
        github_access_token (str): A Github access token
        begin_date (datetime.date): Start date for the range to look in
        end_date (datetime.date): The end date for the range to look in

    Returns:
        list of tuple: (assignee, karma count) sorted from most karma to least
    """
    data = await run_query(github_access_token=github_access_token, query=KARMA_QUERY)

    karma = defaultdict(lambda: 0)
    for repository in data['data']['organization']['repositories']['nodes']:
        # Keep track if any dates fall outside the range. If none do and we're at the max limit for number of PRs,
        # we need to paginate (but instead we'll just raise an exception for now).
        some_dates_out_of_range = False
        for pull_request in repository['pullRequests']['nodes']:
            updated_at = parse(pull_request['updatedAt']).date()
            merged_at = parse(pull_request['mergedAt']).date()

            if begin_date <= updated_at <= end_date:
                if begin_date <= merged_at <= end_date:
                    # A pull request could get updated after it was merged. We don't have a good way
                    # to filter this out via API so just ignore them here
                    for assignee in pull_request['assignees']['nodes']:
                        karma[assignee['name']] += 1
            elif updated_at < begin_date:
                some_dates_out_of_range = True
        if len(repository['pullRequests']['nodes']) == 100 and not some_dates_out_of_range:
            # This means there are at least 100 pull requests within that time range for that value.
            # We will probably not get more than 100 merged pull requests in a single sprint, but raise
            # an exception if we do.
            raise Exception(
                "Response contains more PRs than can be handled at once"
                " for {repo}, {begin_date} to {end_date}.".format(
                    repo=repository['name'],
                    begin_date=begin_date,
                    end_date=end_date,
                )
            )

    karma_list = sorted(karma.items(), key=lambda tup: tup[1], reverse=True)
    return karma_list


async def needs_review(github_access_token):
    """
    Calculate which PRs need review

    Args:
        github_access_token (str): A Github access token

    Returns:
        list of tuple: A list of (repo name, pr title, pr url) for PRs that need review and are unassigned
    """
    data = await run_query(
        github_access_token=github_access_token,
        query=NEEDS_REVIEW_QUERY,
    )
    prs_needing_review = []
    # Query will show all open PRs, we need to filter on assignee and label
    for repository in data['data']['organization']['repositories']['nodes']:
        for pull_request in repository['pullRequests']['nodes']:
            has_needs_review = False

            # Check for needs review label
            for label in pull_request['labels']['nodes']:
                if label['name'].lower() == 'needs review':
                    has_needs_review = True
                    break

            if not has_needs_review:
                continue

            # Check for no assignee
            if not pull_request['assignees']['nodes']:
                prs_needing_review.append(
                    (repository['name'], pull_request['title'], pull_request['url'])
                )

    return prs_needing_review


def get_org_and_repo(repo_url):
    """
    Get the org and repo from a git repository cloned from github.

    Args:
        repo_url (str): The repository URL

    Returns:
        tuple: (org, repo)
    """
    org, repo = re.match(r'^.*github\.com[:|/](.+)/(.+)\.git', repo_url).groups()
    return org, repo


async def get_status_of_pr(*, github_access_token, org, repo, branch):
    """
    Get the status of the PR for a given branch

    Args:
        github_access_token (str): The github access token
        org (str): The github organization (eg mitodl)
        repo (str): The github repository (eg micromasters)
        branch (str): The name of the associated branch

    Returns:
        str: The status of the PR. If any status is failed this is failed,
            if any is pending this is pending. Else it's good.
    """
    endpoint = "https://api.github.com/repos/{org}/{repo}/commits/{ref}/statuses".format(
        org=org,
        repo=repo,
        ref=branch,
    )
    client = ClientWrapper()
    resp = await client.get(
        endpoint,
        headers=github_auth_headers(github_access_token),
    )
    if resp.status_code == 404:
        statuses = []
    else:
        resp.raise_for_status()
        statuses = resp.json()

    # Only look at PR builds
    statuses = [status for status in statuses if status['context'] == 'continuous-integration/travis-ci/pr']

    if len(statuses) == 0:
        # This may be due to the PR not being available yet
        return NO_PR_BUILD

    return statuses[0]['state']
