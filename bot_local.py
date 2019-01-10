#!/usr/bin/env python3
"""Run the bot locally to test it out"""
import asyncio
import sys

from bot import (
    Bot,
    get_channels_info,
    get_envs,
    load_repos_info,
)


class ConsoleBot(Bot):
    """Fake console bot"""
    async def say(
            self, *, channel_id, text='', attachments=None, message_type='', is_announcement=False
    ):  # pylint: disable=unused-argument
        """Print messages to stdout"""
        attachment_text = ''
        if attachments is not None:
            attachment_text = attachments[0].get('text', '')
        line = " ".join(word for word in [text, attachment_text, message_type, is_announcement] if word)
        print("\033[92m{}\033[0m".format(line))

    async def typing(self, channel_id):
        """Ignore typing messages"""


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

    bot = ConsoleBot(
        websocket=None,
        slack_access_token=envs['SLACK_ACCESS_TOKEN'],
        github_access_token=envs['GITHUB_ACCESS_TOKEN'],
        timezone=envs['TIMEZONE'],
        repos_info=repos_info
    )

    loop = asyncio.get_event_loop()
    loop.run_until_complete(
        loop.create_task(
            bot.handle_message(
                manager='mitodl_user',
                channel_id=channel_id,
                words=words,
                loop=loop,
            )
        )
    )


if __name__ == "__main__":
    main()
