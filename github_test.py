"""Tests for github functions"""
import json
import os
from unittest.mock import patch

from dateutil.parser import parse

from bot import SCRIPT_DIR
from github import (
    calculate_karma,
    KARMA_QUERY,
)


def test_karma():
    """Assert behavior of karma calculation"""
    with open(os.path.join(SCRIPT_DIR, "test_karma_response.json")) as f:
        payload = json.load(f)
    github_access_token = 'token'

    with patch('github.run_query', autospec=True, return_value=payload) as patched:
        assert calculate_karma(github_access_token, parse("2017-11-09").date(), parse("2017-11-09").date()) == [
            ('Tobias Macey', 1),
        ]
    patched.assert_called_once_with(github_access_token, KARMA_QUERY)
