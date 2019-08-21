"""Tests for slack functions"""
import pytest


from slack import get_channels_info


pytestmark = pytest.mark.asyncio


async def test_get_channels_info(mocker):
    """get_channels_info should obtain information for all public and private channels that doof knows about"""
    post_patch = mocker.async_patch('slack.httpx.AsyncClient.post')
    post_patch.return_value.json.side_effect = [
        {'channels': [{
            'name': 'a',
            'id': 'public channel',
        }]},
        {'groups': [{
            'name': 'and a',
            'id': 'private one',
        }]},
    ]
    token = 'token'
    assert await get_channels_info(token) == {
        'a': 'public channel',
        'and a': 'private one',
    }
    post_patch.assert_any_call(mocker.ANY, "https://slack.com/api/channels.list", data={'token': token})
    post_patch.assert_any_call(mocker.ANY, "https://slack.com/api/groups.list", data={'token': token})
    assert post_patch.return_value.raise_for_status.call_count == 2
