"""Tests for the web server"""
import asyncio
import json
from unittest.mock import patch
import urllib.parse
import uuid

import pytest
from tornado.testing import AsyncHTTPTestCase

from bot_test import DoofSpoof
from web import make_app, is_authenticated


pytestmark = pytest.mark.asyncio


class FinishReleaseTests(AsyncHTTPTestCase):
    """Tests for the finish release button"""

    def setUp(self):
        self.secret = uuid.uuid4().hex
        self.loop = asyncio.get_event_loop()
        self.doof = DoofSpoof(loop=self.loop)
        self.app = make_app(secret=self.secret, bot=self.doof)

        super().setUp()

    def get_app(self):
        """Override for this app"""
        return self.app

    def test_bad_auth_buttons(self):
        """
        Bad auth should be rejected for buttons
        """
        with patch("web.is_authenticated", return_value=False):
            response = self.fetch("/api/v0/buttons/", method='POST', body=urllib.parse.urlencode({
                "payload": json.dumps({}),
            }))

        assert response.code == 401

    def test_bad_auth_events(self):
        """
        Bad auth should be rejected for buttons
        """
        with patch("web.is_authenticated", return_value=False):
            response = self.fetch("/api/v0/events/", method='POST', body=json.dumps({}))

            assert response.code == 401

    def test_good_auth(self):
        """
        If the token validates, we should call handle_webhook on Bot
        """
        payload = {}

        with patch('bot.Bot.handle_webhook') as handle_webhook, patch("web.is_authenticated", return_value=True):
            async def fake_webhook(*args, **kwargs):  # pylint: disable=unused-argument
                pass
            handle_webhook.return_value = fake_webhook()  # pylint: disable=assignment-from-no-return

            response = self.fetch('/api/v0/buttons/', method='POST', body=urllib.parse.urlencode({
                "payload": json.dumps(payload),
            }))

        assert response.code == 200
        handle_webhook.assert_called_once_with(
            webhook_dict=payload,
        )

    def test_event_challenge(self):
        """Doof should respond to a challenge with the same challenge text"""
        challenge = "event challenge text"
        payload = {
            "type": "url_verification",
            "challenge": challenge
        }

        with patch('bot.Bot.handle_event') as handle_event, patch("web.is_authenticated", return_value=True):
            async def fake_event(*args, **kwargs):  # pylint: disable=unused-argument
                pass
            handle_event.return_value = fake_event()  # pylint: disable=assignment-from-no-return

            response = self.fetch('/api/v0/events/', method='POST', body=json.dumps(payload))

        assert response.code == 200
        assert response.body == challenge.encode()

    def test_event_handle(self):
        """Doof should call handle_event for valid events"""
        payload = {
            "type": "not_a_challenge",
        }

        with patch('bot.Bot.handle_event') as handle_event, patch("web.is_authenticated", return_value=True):
            async def fake_event(*args, **kwargs):  # pylint: disable=unused-argument
                pass
            handle_event.return_value = fake_event()  # pylint: disable=assignment-from-no-return

            response = self.fetch('/api/v0/events/', method='POST', body=json.dumps(payload))

        assert response.code == 200
        assert response.body == b""
        handle_event.assert_called_once_with(
            webhook_dict=payload,
        )


# pylint: disable=too-many-arguments
@pytest.mark.parametrize("secret, timestamp, signature, body, expected", [
    [  # values from Slack docs
        "8f742231b10e8888abcd99yyyzzz85a5",
        "1531420618",
        "v0=a2114d57b48eac39b9ad189dd8316235a7b4a8d21a10bd27519666489c69b503",
        b"token=xyzz0WbapA4vBCDEFasx0q6G&team_id=T1DC2JH3J&team_domain=testteamnow&channel_id=G8PSS9T3V&"
        b"channel_name=foobar&user_id=U2CERLKJA&user_name=roadrunner&command=%2Fwebhook-collect&"
        b"text=&response_url=https%3A%2F%2Fhooks.slack.com%2Fcommands%"
        b"2FT1DC2JH3J%2F397700885554%2F96rGlfmibIGlgcZRskXaIFfN"
        b"&trigger_id=398738663015.47445629121.803a0bc887a14d10d2c447fce8b6703c", True
    ], [
        "secret",
        "timestamp",
        "v0=notgonnawork",
        b"body",
        False
    ]
])
def test_is_authenticated(mocker, secret, timestamp, signature, body, expected):
    """Test our slack authentication logic"""
    request = mocker.Mock(body=body, headers={
        "X-Slack-Signature": signature,
        "X-Slack-Request-Timestamp": timestamp,
    })
    assert is_authenticated(request, secret) is expected
