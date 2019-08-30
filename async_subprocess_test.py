"""Tests for async_subprocess_test"""
import subprocess

import pytest

from async_subprocess import check_call, check_output, call
from lib import async_wrapper


pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize("is_success", [True, False])
async def test_check_call_shell(mocker, is_success):
    """check_call should pass through a shell command string if shell is true"""
    patched = mocker.async_patch("asyncio.create_subprocess_shell")
    patched.return_value.wait = async_wrapper(lambda: 0 if is_success else 1)

    cmd = "git checkout shell"
    if is_success:
        await check_call(cmd, shell=True)
    else:
        with pytest.raises(subprocess.CalledProcessError):
            await check_call(cmd, shell=True)


@pytest.mark.parametrize("is_success", [True, False])
async def test_check_call_exec(mocker, is_success):
    """check_call should use exec if shell is false"""
    patched = mocker.async_patch("asyncio.create_subprocess_exec")
    patched.return_value.wait = async_wrapper(lambda: 0 if is_success else 1)

    args = ["git", "checkout", "shell"]
    if is_success:
        await check_call(args, shell=False)
    else:
        with pytest.raises(subprocess.CalledProcessError):
            await check_call(args, shell=False)


@pytest.mark.parametrize("is_success", [True, False])
async def test_call_shell(mocker, is_success):
    """call should pass through a shell command string if shell is true"""
    patched = mocker.async_patch("asyncio.create_subprocess_shell")
    expected_return = 0 if is_success else 1
    patched.return_value.wait = async_wrapper(lambda: expected_return)

    cmd = "git checkout shell"
    assert await call(cmd, shell=True) == expected_return


@pytest.mark.parametrize("is_success", [True, False])
async def test_call_exec(mocker, is_success):
    """call should use exec if shell is false"""
    patched = mocker.async_patch("asyncio.create_subprocess_exec")
    expected_return = 0 if is_success else 1
    patched.return_value.wait = async_wrapper(lambda: expected_return)

    args = ["git", "checkout", "shell"]
    assert await call(args, shell=False) == expected_return


@pytest.mark.parametrize("is_success", [True, False])
async def test_check_output_shell(mocker, is_success):
    """check_output should pass through a shell command string if shell is true"""
    patched = mocker.async_patch("asyncio.create_subprocess_shell")
    patched.return_value.wait = async_wrapper(lambda: 0 if is_success else 1)
    expected_return = "some response text"
    patched.return_value.communicate = async_wrapper(lambda input: (expected_return, None))

    cmd = "git checkout shell"
    if is_success:
        assert await check_output(cmd, shell=True) == expected_return
    else:
        with pytest.raises(subprocess.CalledProcessError):
            await check_output(cmd, shell=True)


@pytest.mark.parametrize("is_success", [True, False])
async def test_check_output_exec(mocker, is_success):
    """check_output should use exec if shell is false"""
    patched = mocker.async_patch("asyncio.create_subprocess_exec")
    patched.return_value.wait = async_wrapper(lambda: 0 if is_success else 1)
    expected_return = "some response text"
    patched.return_value.communicate = async_wrapper(lambda input: (expected_return, None))

    args = ["git", "checkout", "shell"]
    if is_success:
        assert await check_output(args, shell=False) == expected_return
    else:
        with pytest.raises(subprocess.CalledProcessError):
            await check_output(args, shell=False)
