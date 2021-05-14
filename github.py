"""Functions interacting with github"""

import json
import re
import logging

from client_wrapper import ClientWrapper

log = logging.getLogger(__name__)


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
