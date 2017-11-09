#!/usr/bin/env python3
"""Run the bot locally to test it out"""
import asyncio
import json
import sys

from bot import (
    Bot,
    get_envs,
    load_repos_info,
)


class FakeConsoleSocket:
    """Fake socket which dumps to stdout"""

    async def send(self, payload):
        """Print out data which would get sent"""
        text = json.loads(payload)['text']
        print(
            "\033[92m{}\033[0m".format(text)
        )


def main():
    """Handle command line arguments and run a command"""
    envs = get_envs()

    if len(sys.argv) < 3:
        raise Exception("Expected arguments: project_name command arg1 arg2...")

    _, project_name, *words = sys.argv

    repos_info = load_repos_info()
    try:
        repo_info = [repo_info for repo_info in repos_info if repo_info.name == project_name][0]
    except IndexError:
        raise Exception("Unable to find channel with name {}".format(project_name))

    bot = Bot(FakeConsoleSocket(), envs['SLACK_ACCESS_TOKEN'], envs['GITHUB_ACCESS_TOKEN'])

    loop = asyncio.get_event_loop()
    loop.run_until_complete(
        loop.create_task(
            bot.handle_message(repo_info.channel_id, repo_info, words, loop)
        )
    )


if __name__ == "__main__":
    main()
