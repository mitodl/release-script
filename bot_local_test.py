"""Make sure bot_local works"""

import pytest

from bot_local import async_main


pytestmark = pytest.mark.asyncio


async def test_bot_local(mocker, test_repo):
    """
    bot_local should execute a command
    """
    channel_name = "doof_channel"
    channel_id = "D1234567"
    timezone = "America/New_York"
    slack_token = "slack token"
    github_token = "github_token"
    npm_token = "npm_token"
    repos_info = [test_repo]
    channels_info = {channel_name: channel_id}

    get_envs_mock = mocker.patch(
        "bot_local.get_envs",
        return_value={
            "SLACK_ACCESS_TOKEN": slack_token,
            "GITHUB_ACCESS_TOKEN": github_token,
            "NPM_TOKEN": npm_token,
            "TIMEZONE": timezone,
        },
    )
    get_channels_info = mocker.async_patch(
        "bot_local.get_channels_info", return_value=channels_info
    )
    mocker.patch("bot_local.sys", argv=["bot_local.py", channel_name, "hi"])
    load_repos = mocker.patch("bot_local.load_repos_info", return_value=repos_info)
    handle_message_mock = mocker.async_patch("bot_local.ConsoleBot.handle_message")
    startup_mock = mocker.async_patch("bot_local.ConsoleBot.startup")

    await async_main()

    get_envs_mock.assert_called_once_with()
    load_repos.assert_called_once_with(channels_info)
    get_channels_info.assert_called_once_with(slack_token)
    startup_mock.assert_called_once_with(mocker.ANY)
    handle_message_mock.assert_called_once_with(
        mocker.ANY,
        manager="mitodl_user",
        channel_id=channel_id,
        words=["hi"],
    )
