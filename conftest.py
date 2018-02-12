"""Fixtures"""

import pytest


@pytest.fixture
def client(mocker):
    new_client = mocker.Mock()

    async def get(*args, **kwargs):
        """Allow mocking of get"""
        return new_client.get_sync(*args, **kwargs)

    async def post(*args, **kwargs):
        """
        Allow mocking of post
        """
        return new_client.post_sync(*args, **kwargs)

    yield new_client
