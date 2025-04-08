"""Tests for wait_for_deploy"""

import json
from unittest.mock import Mock, AsyncMock

import pytest
from requests import Response
from requests.exceptions import RequestException

from test_util import async_context_manager_yielder
from wait_for_deploy import wait_for_deploy, fetch_release_hash


pytestmark = pytest.mark.asyncio


# Removed parametrization as expected_version is now mandatory
async def test_wait_for_deploy(mocker, test_repo_directory):
    """wait_for_deploy should poll deployed web applications until the expected version is found."""
    mock_latest_hash = "mock_commit_hash_1234567"
    expected_version = "1.2.3"  # Version is now mandatory

    # The signal wait_for_deploy will look for is always the expected_version
    release_signal = expected_version

    # Mock fetch_release_hash to return dummy values twice, then the correct signal
    fetch_release_patch = mocker.patch(
        "wait_for_deploy.fetch_release_hash"
    )  # Use patch, not async_patch
    fetch_release_patch.side_effect = [
        "intermediate_signal_1",
        "intermediate_signal_2",
        release_signal,
    ]

    # Mock check_output to return the latest commit hash
    check_output_patch = mocker.async_patch("wait_for_deploy.check_output")
    check_output_patch.return_value = f" {mock_latest_hash} ".encode()

    # Mock init_working_dir
    init_working_dir_mock = mocker.patch(
        "wait_for_deploy.init_working_dir",
        side_effect=async_context_manager_yielder(test_repo_directory),
    )
    mocker.async_patch("asyncio.sleep")

    repo_url = "repo_url"
    token = "token"
    hash_url = "http://example.com/hash"
    watch_branch = "main"

    # Call the function under test
    result = await wait_for_deploy(
        github_access_token=token,
        repo_url=repo_url,
        hash_url=hash_url,
        watch_branch=watch_branch,
        expected_version=expected_version,  # Pass the mandatory version
    )
    assert result is True

    # Assertions
    init_working_dir_mock.assert_called_once_with(token, repo_url)
    check_output_patch.assert_called_once_with(
        ["git", "rev-parse", f"origin/{watch_branch}"], cwd=test_repo_directory
    )
    # Check that fetch_release_hash was called correctly with the expected version
    fetch_release_patch.assert_any_call(hash_url, expected_version=expected_version)
    assert (
        fetch_release_patch.call_count == 3
    ), "fetch_release_hash should be called 3 times"


@pytest.mark.asyncio
async def test_fetch_release_hash_plain_text(mocker):
    """fetch_release_hash should return the hash when the response is plain text"""
    mock_response = Mock(spec=Response)
    mock_response.content = b"a" * 40
    mock_response.raise_for_status = Mock()

    mock_client_wrapper_patch = mocker.patch("wait_for_deploy.ClientWrapper")
    mock_get = AsyncMock(return_value=mock_response)
    mock_client_wrapper_patch.return_value.get = mock_get

    hash_url = "http://example.com/hash"
    expected_version = "0.0.1"  # Must provide expected version
    # Since content is plain text hash, it should return the hash
    result = await fetch_release_hash(hash_url, expected_version=expected_version)
    assert result == "a" * 40
    mock_get.assert_called_once_with(hash_url)


@pytest.mark.asyncio
async def test_fetch_release_hash_json(mocker):
    """fetch_release_hash should return the hash from a JSON response"""
    expected_hash = "b" * 40
    mock_response = Mock(spec=Response)
    mock_response.content = json.dumps({"hash": expected_hash}).encode()
    mock_response.raise_for_status = Mock()

    mock_client_wrapper_patch = mocker.patch("wait_for_deploy.ClientWrapper")
    mock_get = AsyncMock(return_value=mock_response)
    mock_client_wrapper_patch.return_value.get = mock_get

    hash_url = "http://example.com/hash.json"
    expected_version = "0.0.2"  # Must provide expected version
    # Since JSON lacks 'version' key, it should return the hash
    result = await fetch_release_hash(hash_url, expected_version=expected_version)
    assert result == expected_hash
    mock_get.assert_called_once_with(hash_url)


@pytest.mark.asyncio
async def test_fetch_release_hash_json_with_version_match(mocker):
    """fetch_release_hash should return the hash when version matches"""
    expected_hash = "c" * 40
    expected_version = "1.2.3"
    mock_response = Mock(spec=Response)
    mock_response.content = json.dumps(
        {"hash": expected_hash, "version": expected_version}
    ).encode()
    mock_response.raise_for_status = Mock()

    mock_client_wrapper_patch = mocker.patch("wait_for_deploy.ClientWrapper")
    mock_get = AsyncMock(return_value=mock_response)
    mock_client_wrapper_patch.return_value.get = mock_get

    hash_url = "http://example.com/hash_version.json"
    result = await fetch_release_hash(hash_url, expected_version=expected_version)
    # With the new logic, if version matches, it returns the version, not the hash
    assert result == expected_version
    mock_get.assert_called_once_with(hash_url)


@pytest.mark.asyncio
async def test_fetch_release_hash_json_with_version_mismatch(mocker):
    """fetch_release_hash should raise an exception when version mismatches"""
    expected_hash = "d" * 40
    expected_version = "1.2.3"
    deployed_version = "1.2.4"
    mock_response = Mock(spec=Response)
    mock_response.content = json.dumps(
        {"hash": expected_hash, "version": deployed_version}
    ).encode()
    mock_response.raise_for_status = Mock()

    mock_client_wrapper_patch = mocker.patch("wait_for_deploy.ClientWrapper")
    mock_get = AsyncMock(return_value=mock_response)
    mock_client_wrapper_patch.return_value.get = mock_get

    hash_url = "http://example.com/hash_version_mismatch.json"
    with pytest.raises(Exception) as excinfo:
        await fetch_release_hash(hash_url, expected_version=expected_version)
    assert (
        f"Version mismatch at {hash_url}: Expected '{expected_version}', but found '{deployed_version}'"
        in str(excinfo.value)
    )
    mock_get.assert_called_once_with(hash_url)


@pytest.mark.asyncio
async def test_fetch_release_hash_json_no_hash_key(mocker):
    """fetch_release_hash should treat content as hash if 'hash' key is missing in JSON"""
    # This tests the fallback behavior where the entire content is treated as hash
    # if JSON parsing succeeds but 'hash' key is missing.
    # If the content itself is not a valid hash, it will fail the length check later.
    mock_response = Mock(spec=Response)
    # Simulate JSON with only a version key
    mock_response.content = json.dumps({"version": "1.0.0"}).encode()
    mock_response.raise_for_status = Mock()

    mock_client_wrapper_patch = mocker.patch("wait_for_deploy.ClientWrapper")
    mock_get = AsyncMock(return_value=mock_response)
    mock_client_wrapper_patch.return_value.get = mock_get

    hash_url = "http://example.com/no_hash_key.json"
    expected_version = "1.0.0"  # Must provide expected version
    # We expect it to return the version since it's present and matches expected
    result = await fetch_release_hash(hash_url, expected_version=expected_version)
    assert result == expected_version
    mock_get.assert_called_once_with(hash_url)


@pytest.mark.asyncio
async def test_fetch_release_hash_json_no_version_key_expected(mocker):
    """fetch_release_hash should proceed if version is expected but not in JSON"""
    expected_hash = "f" * 40
    expected_version = "2.0.0"
    mock_response = Mock(spec=Response)
    # JSON has hash but no version key
    mock_response.content = json.dumps({"hash": expected_hash}).encode()
    mock_response.raise_for_status = Mock()

    mock_client_wrapper_patch = mocker.patch("wait_for_deploy.ClientWrapper")
    mock_get = AsyncMock(return_value=mock_response)
    mock_client_wrapper_patch.return_value.get = mock_get

    hash_url = "http://example.com/no_version_key.json"
    # Since 'version' key is missing, it should fall back and return the hash
    result = await fetch_release_hash(hash_url, expected_version=expected_version)
    assert result == expected_hash
    mock_get.assert_called_once_with(hash_url)


@pytest.mark.asyncio
async def test_fetch_release_hash_invalid_length(mocker):
    """fetch_release_hash should raise an exception for invalid hash length"""
    invalid_hash = "g" * 39  # Not 40 characters
    mock_response = Mock(spec=Response)
    mock_response.content = invalid_hash.encode()
    mock_response.raise_for_status = Mock()

    mock_client_wrapper_patch = mocker.patch("wait_for_deploy.ClientWrapper")
    mock_get = AsyncMock(return_value=mock_response)
    mock_client_wrapper_patch.return_value.get = mock_get

    hash_url = "http://example.com/invalid_hash"
    expected_version = "0.0.3"  # Must provide expected version
    with pytest.raises(Exception) as excinfo:
        await fetch_release_hash(hash_url, expected_version=expected_version)
    # Update assertion to match the error message when expected_version is provided
    assert (
        f"Expected version '{expected_version}' but found invalid signal at {hash_url}. Content: '{invalid_hash}'"
        in str(excinfo.value)
    )
    mock_get.assert_called_once_with(hash_url)


@pytest.mark.asyncio
async def test_fetch_release_hash_http_error(mocker):
    """fetch_release_hash should raise exception on HTTP error"""
    mock_client_wrapper_patch = mocker.patch("wait_for_deploy.ClientWrapper")
    # Simulate an HTTP error during the get call
    mock_get = AsyncMock(side_effect=RequestException("Connection failed"))
    mock_client_wrapper_patch.return_value.get = mock_get

    hash_url = "http://example.com/http_error"
    expected_version = (
        "0.0.4"  # Must provide expected version, even if error occurs before use
    )
    with pytest.raises(RequestException):
        await fetch_release_hash(hash_url, expected_version=expected_version)
    mock_get.assert_called_once_with(hash_url)
