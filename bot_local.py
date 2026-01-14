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

    async def say(self, *, channel_id, text="", attachments=None, message_type=""):
        """Print messages to stdout"""
        attachment_text = ""
        if attachments is not None:
            attachment_text = attachments[0].get("text", "")
        line = f"{' '.join(word for word in [text, attachment_text, message_type] if word)} "
        print(f"\033[92m{line}\033[0m")


async def async_main():
    """Handle command line arguments and run a command"""
    envs = get_envs()

    if len(sys.argv) < 3:
        raise Exception("Expected arguments: channel_name command arg1 arg2...")

    _, channel_name, *words = sys.argv

    channels_info = await get_channels_info(envs["SLACK_ACCESS_TOKEN"])
    try:
        channel_id = channels_info[channel_name]
    except KeyError as ex:
        raise Exception(f"Unable to find channel by name {channel_name}") from ex

    repos_info = load_repos_info(channels_info)

    bot = ConsoleBot(
        doof_id="console",
        slack_access_token=envs["SLACK_ACCESS_TOKEN"],
        github_access_token=envs["GITHUB_ACCESS_TOKEN"],
        timezone=envs["TIMEZONE"],
        npm_token=envs["NPM_TOKEN"],
        repos_info=repos_info,
    )

    await bot.startup()

    await bot.handle_message(
        manager="mitodl_user",
        channel_id=channel_id,
        words=words,
    )


def main():
    """Main function"""
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
