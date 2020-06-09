"""Tests for slack functions"""
import pytest


from slack import get_channels_info


pytestmark = pytest.mark.asyncio


async def test_get_channels_info(mocker):
    """get_channels_info should obtain information for all public and private channels that doof knows about"""
    post_patch = mocker.async_patch('client_wrapper.ClientWrapper.post')
    post_patch.return_value.json.side_effect = [
        {
            'channels': [
                {
                    'name': 'a',
                    'id': 'public channel',
                },
                {
                    'name': 'and a',
                    'id': 'private one',
                },
            ]
        },
    ]
    token = 'token'
    assert await get_channels_info(token) == {
        'a': 'public channel',
        'and a': 'private one',
    }
    post_patch.assert_called_once_with(
        mocker.ANY,
        "https://slack.com/api/conversations.list",
        data={
            'token': token,
            "types": "public_channel,private_channel",
        },
    )
