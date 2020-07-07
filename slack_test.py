"""Tests for slack functions"""
import pytest


from slack import get_channels_info, get_doofs_id


pytestmark = pytest.mark.asyncio


async def test_get_channels_info(mocker):
    """get_channels_info should obtain information for all public and private channels that doof knows about"""
    post_patch = mocker.async_patch('client_wrapper.ClientWrapper.post')
    next_cursor = 'some cursor'
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
            ],
            'response_metadata': {
                'next_cursor': next_cursor,
            }
        },
        {
            'channels': [
                {
                    'name': 'two',
                    'id': 'a channel in the next page'
                }
            ]
        },
    ]
    token = 'token'
    assert await get_channels_info(token) == {
        'a': 'public channel',
        'and a': 'private one',
        'two': 'a channel in the next page',
    }
    post_patch.assert_any_call(
        mocker.ANY,
        "https://slack.com/api/conversations.list",
        data={
            'token': token,
            "types": "public_channel,private_channel",
        },
    )
    post_patch.assert_any_call(
        mocker.ANY,
        "https://slack.com/api/conversations.list",
        data={
            'token': token,
            "types": "public_channel,private_channel",
            "cursor": next_cursor,
        },
    )


async def test_get_doofs_id(mocker):
    """get_doofs_id should contact the user API which gets slack info"""
    post_patch = mocker.async_patch('client_wrapper.ClientWrapper.post')
    doof_id = "It's doof"
    token = "It's a token"
    post_patch.return_value.json.return_value = {
        "user": {
            "id": doof_id
        }
    }
    assert await get_doofs_id(token) == doof_id
    post_patch.assert_called_once_with(
        mocker.ANY,
        "https://slack.com/api/users.identity", data={'token': token}
    )
