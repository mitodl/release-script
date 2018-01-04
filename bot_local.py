#!/usr/bin/env python3
"""Run the bot locally to test it out"""
import asyncio
import json
import sys

from bot import (
    Bot,
    get_channels_info,
    get_envs,
    load_repos_info,
)


class FakeConsoleSocket:
    """Fake socket which dumps to stdout"""
    def __init__(self, channel_id):
        self.channel_id = channel_id

    async def send(self, payload_json):
        """Print out data which would get sent"""
        payload = json.loads(payload_json)
        if payload.get('channel') != self.channel_id:
            raise Exception("Unexpected channel for payload: {}".format(payload))
        if payload.get('type') != 'message':
            # ignore typing and other unimportant messages
            return
        text = payload.get('text')
        print(
            "\033[92m{}\033[0m".format(text)
        )


def main():
    """Handle command line arguments and run a command"""
    envs = get_envs()

    if len(sys.argv) < 3:
        raise Exception("Expected arguments: channel_name command arg1 arg2...")

    _, channel_name, *words = sys.argv

    channels_info = get_channels_info(envs['SLACK_ACCESS_TOKEN'])
    try:
        channel_id = channels_info[channel_name]
    except KeyError:
        raise Exception("Unable to find channel by name {}".format(channel_name))

    repos_info = load_repos_info(channels_info)
    try:
        repo_info = [repo_info for repo_info in repos_info if repo_info.channel_id == channel_id][0]
    except IndexError:
        repo_info = None

    bot = Bot(
        websocket=FakeConsoleSocket(channel_id),
        slack_access_token=envs['SLACK_ACCESS_TOKEN'],
        github_access_token=envs['GITHUB_ACCESS_TOKEN'],
        timezone=envs['TIMEZONE'],
    )

    loop = asyncio.get_event_loop()
    loop.run_until_complete(
        loop.create_task(
            bot.handle_message('mitodl_user', channel_id, repo_info, words, loop)
        )
    )


if __name__ == "__main__":
    main()
