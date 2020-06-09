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
    resp = await client.post("https://slack.com/api/conversations.list", data={
        "token": slack_access_token,
        "types": "public_channel,private_channel"
    })
    resp.raise_for_status()
    channels = resp.json()['channels']
    channels_map = {channel['name']: channel['id'] for channel in channels}

    return channels_map
