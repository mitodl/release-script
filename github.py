"""Functions interacting with github"""

from collections import defaultdict
import json
import re

from dateutil.parser import parse
import requests


KARMA_QUERY = """
query {

  organization(login:"mitodl") {
    repositories(first: 100, orderBy: {
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
    repositories(first: 100, orderBy: {
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


def run_query(github_access_token, query):
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
    resp = requests.post(endpoint, data=query, headers={
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


def create_pr(github_access_token, repo_url, title, body, head, base):  # pylint: disable=too-many-arguments
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

    resp = requests.post(
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


def get_pull_request(github_access_token, org, repo, branch):
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

    response = requests.get(
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


def calculate_karma(github_access_token, begin_date, end_date):
    """
    Calculate number of merged pull requests by assigned reviewer

    Args:
        github_access_token (str): A Github access token
        begin_date (datetime.date): Start date for the range to look in
        end_date (datetime.date): The end date for the range to look in

    Returns:
        list of tuple: (assignee, karma count) sorted from most karma to least
    """
    data = run_query(github_access_token, KARMA_QUERY)

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

    karma_list = [(k, v) for k, v in karma.items()]
    karma_list = sorted(karma_list, key=lambda tup: tup[1], reverse=True)
    return karma_list


def needs_review(github_access_token):
    """
    Calculate which PRs need review

    Args:
        github_access_token (str): A Github access token

    Returns:
        list of tuple: A list of (repo name, pr title, pr url) for PRs that need review and are unassigned
    """
    data = run_query(github_access_token, NEEDS_REVIEW_QUERY)
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
