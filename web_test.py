"""Tests for the web server"""
import asyncio
import json
from unittest.mock import patch
import urllib.parse
import uuid

import pytest
from tornado.testing import AsyncHTTPTestCase

from bot_test import DoofSpoof
from web import make_app


pytestmark = pytest.mark.asyncio


class FinishReleaseTests(AsyncHTTPTestCase):
    """Tests for the finish release button"""

    def setUp(self):
        self.token = uuid.uuid4().hex
        self.doof = DoofSpoof()
        self.loop = asyncio.get_event_loop()
        self.app = make_app(self.token, self.doof, self.loop)

        super().setUp()

    def get_app(self):
        """Override for this app"""
        return self.app

    def test_bad_auth(self):
        """
        Bad auth tokens should be rejected
        """
        response = self.fetch('/api/v0/buttons/', method='POST', body=urllib.parse.urlencode({
            "payload": json.dumps({
                "token": "xyz"
            }),
        }))

        assert response.code == 401

    def test_good_auth(self):
        """
        If the token validates, we should call handle_webhook on Bot
        """
        payload = {
            "token": self.token
        }

        with patch('bot.Bot.handle_webhook') as handle_webhook:
            async def fake_webhook(*args, **kwargs):  # pylint: disable=unused-argument
                pass
            handle_webhook.return_value = fake_webhook()  # pylint: disable=assignment-from-no-return

            response = self.fetch('/api/v0/buttons/', method='POST', body=urllib.parse.urlencode({
                "payload": json.dumps(payload),
            }))

        assert response.code == 200
        handle_webhook.assert_called_once_with(
            loop=self.loop,
            webhook_dict=payload,
        )
