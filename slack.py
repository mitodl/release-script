"""functions for interacting with slack"""
from client_wrapper import ClientWrapper


async def iterate_cursor(fetch, key, url, *, data):
    """
    Iterate over a slack response and yield items as they come in

    Args:
        fetch (function): A function to fetch with, like ClientWrapper().post for example
        key (str): The key which contains the list within the request
        url (str): The URL to interact with
        data (dict): parameters for the request
    """
    next_cursor = None
    while True:
        resp = await fetch(
            url,
            data={
                **({"cursor": next_cursor} if next_cursor is not None else {}),
                **data,
            },
        )
        resp.raise_for_status()
        resp_json = resp.json()
        for item in resp_json[key]:
            yield item

        next_cursor = resp_json.get("response_metadata", {}).get("next_cursor")
        if not next_cursor:
            return


async def get_channels_info(slack_access_token):
    """
    Get channel information from slack

    Args:
        slack_access_token (str): Used to authenticate with slack

    Returns:
        dict: A map of channel names to channel ids
    """
    client = ClientWrapper()
    # public channels
    channels = {}

    async for channel in iterate_cursor(
        client.post,
        "channels",
        # see https://api.slack.com/methods/conversations.list
        "https://slack.com/api/conversations.list",
        data={
            "token": slack_access_token,
            "types": "public_channel,private_channel",
            "limit": 200,  # increase from default of 100
            "exclude_archived": "true",
        },
    ):
        channels[channel["name"]] = channel["id"]

    return channels


async def get_doofs_id(slack_access_token):
    """
    Ask Slack for Doof's id

    Args:
        slack_access_token (str): The slack access token
    """
    client = ClientWrapper()

    async for member in iterate_cursor(
        client.post,
        "members",
        "https://slack.com/api/users.list",
        data={"token": slack_access_token},
    ):
        if member["name"] == "doof":
            return member["id"]

    raise Exception("Unable to find Doof's user id")
