"""Functions interacting with github"""

from collections import defaultdict
import json

from dateutil.parser import parse
import requests


KARMA_QUERY = """
query {

  organization(login:"mitodl") {
    repositories(first: 10, orderBy: {
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


def calculate_karma(github_access_token, begin_date, end_date):
    """
    Calculate number of merged pull requests by assigned reviewer

    Args:
        github_access_token (str): A Github access token
        begin_date (datetime.date): Start date for the range to look in
        end_date (datetime.date): The end date for the range to look in
    """
    data = run_query(github_access_token, KARMA_QUERY)

    karma = defaultdict(lambda: 0)
    for repository in data['data']['organization']['repositories']['nodes']:
        # Keep track if any dates fall outside the range. If none do and we're at the max limit for number of PRs,
        # we need to paginate (but instead we'll just raise an exception for now).
        outside_range = None
        for pull_request in repository['pullRequests']['nodes']:
            merged_at = parse(pull_request['updatedAt']).date()
            updated_at = parse(pull_request['mergedAt']).date()

            if begin_date <= updated_at <= end_date:
                if begin_date <= merged_at <= end_date:
                    # A pull request could get updated after it was merged. We don't have a good way
                    # to filter this out via API so just ignore them here
                    for assignee in pull_request['assignees']['nodes']:
                        karma[assignee['name']] += 1
            elif updated_at < begin_date:
                outside_range = updated_at
        if len(repository['pullRequests']['nodes']) == 100 and outside_range is None:
            # This means there are more than 100 pull requests within that time range for that value.
            # We will probably not get more than 100 merged pull requests in a single sprint, but raise
            # an exception if we do.
            raise Exception("Need to paginate for {}, earliest date is {} but closest date is {}".format(
                repository['name'], begin_date, repository['pullRequests']['nodes'][-1]['updatedAt'],
            ))

    karma_list = [(k, v) for k, v in karma.items()]
    karma_list = sorted(karma_list, key=lambda tup: tup[1], reverse=True)
    return karma_list
