"""functions for interacting with slack"""
import http3


async def get_channels_info(slack_access_token):
    """
    Get channel information from slack

    Args:
        slack_access_token (str): Used to authenticate with slack

    Returns:
        dict: A map of channel names to channel ids
    """
    client = http3.AsyncClient()
    # public channels
    resp = await client.post("https://slack.com/api/channels.list", data={
        "token": slack_access_token
    })
    resp.raise_for_status()
    channels = resp.json()['channels']
    channels_map = {channel['name']: channel['id'] for channel in channels}

    # private channels
    resp = await client.post("https://slack.com/api/groups.list", data={
        "token": slack_access_token
    })
    resp.raise_for_status()
    groups = resp.json()['groups']
    groups_map = {group['name']: group['id'] for group in groups}

    return {**channels_map, **groups_map}
