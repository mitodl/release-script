"""Tests for async_subprocess_test"""

import subprocess

import pytest

from async_subprocess import check_call, check_output, call
from exception import AsyncCalledProcessError
from test_util import async_wrapper


pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize("is_success", [True, False])
async def test_check_call_shell(mocker, is_success):
    """check_call should pass through a shell command string if shell is true"""
    patched = mocker.async_patch("asyncio.create_subprocess_shell")
    patched.return_value.wait = async_wrapper(lambda: 0 if is_success else 1)

    cmd = "git checkout shell"
    if is_success:
        await check_call(cmd, shell=True, cwd=".")
    else:
        with pytest.raises(subprocess.CalledProcessError):
            await check_call(cmd, shell=True, cwd=".")


@pytest.mark.parametrize("is_success", [True, False])
async def test_check_call_exec(mocker, is_success):
    """check_call should use exec if shell is false"""
    patched = mocker.async_patch("asyncio.create_subprocess_exec")
    patched.return_value.wait = async_wrapper(lambda: 0 if is_success else 1)

    args = ["git", "checkout", "shell"]
    if is_success:
        await check_call(args, shell=False, cwd=".")
    else:
        with pytest.raises(subprocess.CalledProcessError):
            await check_call(args, shell=False, cwd=".")


@pytest.mark.parametrize("is_success", [True, False])
async def test_call_shell(mocker, is_success):
    """call should pass through a shell command string if shell is true"""
    patched = mocker.async_patch("asyncio.create_subprocess_shell")
    expected_return = 0 if is_success else 1
    patched.return_value.wait = async_wrapper(lambda: expected_return)

    cmd = "git checkout shell"
    assert await call(cmd, shell=True, cwd=".") == expected_return


@pytest.mark.parametrize("is_success", [True, False])
async def test_call_exec(mocker, is_success):
    """call should use exec if shell is false"""
    patched = mocker.async_patch("asyncio.create_subprocess_exec")
    expected_return = 0 if is_success else 1
    patched.return_value.wait = async_wrapper(lambda: expected_return)

    args = ["git", "checkout", "shell"]
    assert await call(args, shell=False, cwd=".") == expected_return


@pytest.mark.parametrize("is_success", [True, False])
async def test_check_output_shell(mocker, is_success):
    """check_output should pass through a shell command string if shell is true"""
    patched = mocker.async_patch("asyncio.create_subprocess_shell")
    patched.return_value.wait = async_wrapper(lambda: 0 if is_success else 1)
    expected_return = "some response text"
    patched.return_value.communicate = async_wrapper(
        lambda input: (expected_return, None)
    )

    cmd = "git checkout shell"
    if is_success:
        assert await check_output(cmd, shell=True, cwd=".") == expected_return
    else:
        with pytest.raises(subprocess.CalledProcessError):
            await check_output(cmd, shell=True, cwd=".")


@pytest.mark.parametrize("is_success", [True, False])
async def test_check_output_exec(mocker, is_success):
    """check_output should use exec if shell is false"""
    patched = mocker.async_patch("asyncio.create_subprocess_exec")
    patched.return_value.wait = async_wrapper(lambda: 0 if is_success else 1)
    expected_return = "some response text"
    patched.return_value.communicate = async_wrapper(
        lambda input: (expected_return, None)
    )

    args = ["git", "checkout", "shell"]
    if is_success:
        assert await check_output(args, shell=False, cwd=".") == expected_return
    else:
        with pytest.raises(subprocess.CalledProcessError):
            await check_output(args, shell=False, cwd=".")


async def test_check_output_exception_stdout():
    """Exceptions from check_output should include any text received from stdout"""
    with pytest.raises(AsyncCalledProcessError) as ex:
        await check_output("echo some text here && false", shell=True, cwd=".")

    assert ex.value.returncode == 1
    assert str(ex.value) == (
        "Command 'echo some text here && false' returned non-zero exit status 1.."
        " stdout=b'some text here\\n', stderr=b''"
    )


async def test_check_output_exception_stderr():
    """Exceptions from check_output should include any text received from stderr"""
    with pytest.raises(AsyncCalledProcessError) as ex:
        await check_output("1>&2 echo some text here && false", shell=True, cwd=".")

    assert ex.value.returncode == 1
    assert str(ex.value) == (
        "Command '1>&2 echo some text here && false' returned non-zero exit status 1.."
        " stdout=b'', stderr=b'some text here\\n'"
    )
