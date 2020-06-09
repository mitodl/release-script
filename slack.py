"""functions for interacting with slack"""
from client_wrapper import ClientWrapper


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
    next_cursor = None
    channels = []

    while True:
        resp = await client.post("https://slack.com/api/conversations.list", data={
            "token": slack_access_token,
            "types": "public_channel,private_channel",
            **({"cursor": next_cursor} if next_cursor is not None else {})
        })
        resp.raise_for_status()
        resp_json = resp.json()
        channels.extend(resp_json['channels'])

        next_cursor = resp_json.get("response_metadata", {}).get("next_cursor")
        if not next_cursor:
            break

    return {channel['name']: channel['id'] for channel in channels}
