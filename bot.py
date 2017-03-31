#!/usr/bin/env python3
import argparse
import asyncio
from datetime import (
    datetime,
    timedelta,
)
from difflib import SequenceMatcher
import os
from subprocess import (
    check_call,
    check_output,
)
import re
import sys

import requests

from wait_for_checked import (
    get_release_pr,
    get_unchecked_authors,
    wait_for_checkboxes,
)


def get_org_and_repo(repo_dir):
    """
    Get the org and repo from a git repository cloned from github.

    Args:
        repo_dir (str): The repository directory

    Returns:
        tuple: (org, repo)
    """
    url = check_output(["git", "remote", "get-url", "origin"], cwd=repo_dir).decode().strip()
    org, repo = re.match("git@github\\.com:(.+)/(.+)\\.git", url).groups()
    return org, repo


def in_script_dir(file_path):
    """
    Get absolute path for a file from within the script directory

    Args:
        file_path (str): The path of a file relative to the script directory

    Returns:
        str: The absolute path to that file
    """
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), file_path)


def next_workday_at_10(now):
    """
    Return time which is 10am the next day, or the following Monday if it lands on the weekend

    Args:
        now (datetime): The current time
    Returns:
        datetime:
            10am the next day or on the following Monday of a weekend
    """
    tomorrow = now + timedelta(days=1)
    next_weekday = tomorrow
    while next_weekday.isoweekday() > 5:
        # If Saturday or Sunday, go to next day
        next_weekday += timedelta(days=1)
    return datetime(next_weekday.year, next_weekday.month, next_weekday.day, 10)


def reformatted_full_name(full_name):
    """
    Make the full name lowercase and split it so we use
    """
    pieces = full_name.lower().split()
    if len(pieces) >= 2:
        return "{} {}".format(pieces[0], pieces[-1])
    elif len(pieces) == 1:
        return pieces[0]
    else:
        return ''


def match_user(slack_users, author_name, threshold=0.6):
    """
    Do a fuzzy match of author name to full name. If it matches, return a formatted Slack handle. Else return original
    full name.
    
    Args:
        slack_users (list of dict): A list of slack users from their API
        author_name (str): The commit author's full name
        threshold (float): All matches must be at least this high to pass.
    """

    lower_author_name = reformatted_full_name(author_name)

    def match_for_user(slack_user):
        lower_name = reformatted_full_name(slack_user['profile']['real_name'])
        ratio = SequenceMatcher(a=lower_author_name, b=lower_name).ratio()
        if ratio >= threshold:
            return ratio
        else:
            return 0

    slack_matches = [(slack_user, match_for_user(slack_user)) for slack_user in slack_users]
    slack_matches = [(slack_user, match) for (slack_user, match) in slack_matches if match >= threshold]

    if len(slack_matches) > 0:
        matched_user = max(slack_matches, key=lambda pair: pair[1])[0]
        return "<@{user}|{user}>".format(user=matched_user['name'])
    else:
        return author_name


class Bot:
    """Slack bot used to manage the release"""

    def __init__(self, slack_webhook_url, access_token, repo_dir, version, rc_hash_url, prod_hash_url):
        """
        Create the slack bot

        Args:
            slack_webhook_url (str): A Slack webhook URL used to post in a Slack channel
            access_token (str): The OAuth access token used to interact with Slack
            repo_dir (str): The directory of a git repository which will be cloned and used for the release
            version (str): The version of the release
            rc_hash_url (str): The URL used to poll the RC server to confirm deployment of the release candidate
            prod_hash_url (str): The URL used to poll the production server to confirm deployment of production
        """
        self.slack_webhook_url = slack_webhook_url
        self.access_token = access_token
        self.repo_dir = repo_dir
        self.org, self.repo = get_org_and_repo(repo_dir)
        self.version = version
        self.rc_hash_url = rc_hash_url
        self.prod_hash_url = prod_hash_url

    def lookup_users(self):
        """
        Get users list from slack
        """
        resp = requests.post("https://slack.com/api/users.list", data={
            "token": self.access_token
        })
        resp.raise_for_status()
        return resp.json()['members']

    def translate_slack_usernames(self, unchecked_authors):
        """
        Try to match each full name with a slack username.

        Args:
            unchecked_authors (iterable of str): An iterable of full names

        Returns:
            iterable of str:
                A iterable of either the slack name or a full name if a slack name was not found
        """
        try:
            slack_users = self.lookup_users()
            return [match_user(slack_users, author) for author in unchecked_authors]

        except Exception as exception:
            sys.stderr.write("Error: {}".format(exception))
            return unchecked_authors

    def say(self, text):
        """
        Post a message in the Slack channel

        Args:
            text (str): A message
        """
        resp = requests.post(self.slack_webhook_url, json={
            "text": text,
        })
        resp.raise_for_status()

    async def do_release(self):
        """
        Start a new release and wait for deployment
        """
        check_call([in_script_dir("release.sh"), self.repo_dir, self.version])
        self.say("Started release {}! Now deploying to RC...".format(self.version))

        check_call([in_script_dir("wait_for_deploy.sh"), self.repo_dir, self.rc_hash_url, "release-candidate"])
        unchecked_authors = get_unchecked_authors(self.org, self.repo, self.version)
        slack_usernames = self.translate_slack_usernames(unchecked_authors)
        self.say(
            "Release {version} was deployed! PR is up at <{pr_url}|Release {version}>."
            " These people have commits in this release: {authors}".format(
                version=self.version,
                authors=", ".join(slack_usernames),
                pr_url=self.pr_url,
            )
        )

    @property
    def pr_url(self):
        """Get URL for Release PR"""
        return get_release_pr(self.org, self.repo, self.version)['html_url']

    async def wait_for_checkboxes(self):
        """
        Poll the Release PR and wait until all checkboxes are checked off
        """
        self.say("Waiting for checkboxes to be marked off...")
        await wait_for_checkboxes(self.org, self.repo, self.version)
        self.say("All checkboxes checked off. Release {} can be merged.".format(self.version))

    async def finish_release(self):
        """
        Merge the release candidate into the release branch, tag it, merge to master, and wait for deployment
        """
        check_call([in_script_dir("finish_release.sh"), self.repo_dir, self.version])
        self.say("Merged release {}! Now deploying to production...".format(self.version))
        check_call([in_script_dir("wait_for_deploy.sh"), self.repo_dir, self.prod_hash_url, "release"])
        self.say("Release {} is now in production.".format(self.version))

    def message_if_unchecked(self):
        """
        Send a message next morning if any boxes are not yet checked off
        """
        unchecked_authors = get_unchecked_authors(self.org, self.repo, self.version)
        if unchecked_authors:
            slack_usernames = self.translate_slack_usernames(unchecked_authors)
            self.say("Good morning! The following authors have not yet checked off their boxes: {}".format(
                ", ".join(slack_usernames)
            ))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=['release', 'wait_for_checkboxes', 'finish_release'])
    parser.add_argument("repo_dir")
    parser.add_argument("version")
    parser.add_argument("--org", default="mitodl")
    parser.add_argument("--rc-hash-url", default="https://micromasters-rc.herokuapp.com/static/hash.txt")
    parser.add_argument("--prod-hash-url", default="https://micromasters.mit.edu/static/hash.txt")
    args = parser.parse_args()

    slack_webhook_url = os.environ.get('SLACK_WEBHOOK_URL')
    if not slack_webhook_url:
        raise Exception("Missing SLACK_WEBHOOK_URL")

    slack_access_token = os.environ.get('SLACK_ACCESS_TOKEN')
    if not slack_access_token:
        raise Exception("Missing SLACK_ACCESS_TOKEN")

    bot = Bot(slack_webhook_url, slack_access_token, args.repo_dir, args.version, args.rc_hash_url, args.prod_hash_url)

    now = datetime.now()
    tomorrow_at_10 = next_workday_at_10(now)

    loop = asyncio.get_event_loop()
    if args.command == "release":
        loop.call_later((tomorrow_at_10 - now).total_seconds(), bot.message_if_unchecked)
        loop.run_until_complete(bot.do_release())
        loop.run_until_complete(bot.wait_for_checkboxes())
    elif args.command == 'wait_for_checkboxes':
        loop.call_later((tomorrow_at_10 - now).total_seconds(), bot.message_if_unchecked)
        loop.run_until_complete(bot.wait_for_checkboxes())
    elif args.command == "finish_release":
        loop.run_until_complete(bot.finish_release())
    loop.close()


if __name__ == "__main__":
    main()
