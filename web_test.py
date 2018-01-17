"""Tests for the web server"""
import json
from unittest.mock import Mock, patch
import urllib.parse
import uuid

import pytest
from tornado.testing import AsyncHTTPTestCase

from bot import FINISH_RELEASE_ID
from bot_test import DoofSpoof
from repo_info import RepoInfo
from web import make_app


pytestmark = pytest.mark.asyncio


class FinishReleaseTests(AsyncHTTPTestCase):
    """Tests for the finish release button"""

    def setUp(self):
        self.token = uuid.uuid4().hex
        self.repos_info = [
            RepoInfo(
                name='doof_repo',
                repo_url='http://github.com/mitodl/doof.git',
                prod_hash_url='http://doof.example.com/hash.txt',
                rc_hash_url='http://doof-rc.example.com/hash.txt',
                channel_id='doof',
            )
        ]
        self.doof = DoofSpoof()
        self.app = make_app(self.token, self.doof, self.repos_info)

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

    def test_different_callback_id(self):
        """
        If the callback id doesn't match don't do anything
        """
        with patch(
            'bot.finish_release', autospec=True
        ) as finish_release_mock:
            response = self.fetch('/api/v0/buttons/', method='POST', body=urllib.parse.urlencode({
                "payload": json.dumps({
                    "token": self.token,
                    "callback_id": "xyz",
                    "channel": {
                        "id": "doof"
                    },
                    "user": {
                        "id": "doofenshmirtz"
                    }
                }),
            }))
        assert finish_release_mock.called is False

        assert response.code == 200

    def test_finish(self):
        """
        Finish the release
        """
        wait_for_deploy_sync_mock = Mock()

        async def wait_for_deploy_fake(*args, **kwargs):
            """await cannot be used with mock objects"""
            wait_for_deploy_sync_mock(*args, **kwargs)

        with patch(
            'bot.get_release_pr', autospec=True
        ) as get_release_pr_mock, patch(
            'bot.finish_release', autospec=True
        ) as finish_release_mock, patch(
            'bot.wait_for_deploy', wait_for_deploy_fake,
        ):
            response = self.fetch('/api/v0/buttons/', method='POST', body=urllib.parse.urlencode({
                "payload": json.dumps({
                    "token": self.token,
                    "callback_id": FINISH_RELEASE_ID,
                    "channel": {
                        "id": "doof"
                    },
                    "user": {
                        "id": "doofenshmirtz"
                    }
                }),
            }))

        assert response.code == 200
        assert wait_for_deploy_sync_mock.called is True
        assert get_release_pr_mock.called is True
        assert finish_release_mock.called is True

        assert self.doof.said('deploying to production...')
        assert self.doof.said('has been released to production')
