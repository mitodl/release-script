"""asyncio subprocess create_subprocess_exec"""

import asyncio
import subprocess

from exception import AsyncCalledProcessError


async def check_call(args, *, cwd, env=None, shell=False):
    """
    Similar to subprocess.check_call but adapted for asyncio. Please add new arguments as needed.
    cwd is added as an explicit argument because asyncio will not work well with os.chdir, which is not bound to the
    context of the running coroutine.
    """
    returncode = await call(args, cwd=cwd, env=env, shell=shell)
    if returncode != 0:
        raise AsyncCalledProcessError(returncode, args if shell else args[0])


async def check_output(args, *, cwd, env=None, shell=False):
    """
    Similar to subprocess.check_output but adapted for asyncio. Please add new arguments as needed.
    cwd is added as an explicit argument because asyncio will not work well with os.chdir, which is not bound to the
    context of the running coroutine.
    """
    create_func = (
        asyncio.create_subprocess_shell if shell else asyncio.create_subprocess_exec
    )
    popenargs = [args] if shell else args
    proc = await create_func(
        *popenargs,
        stdin=None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        cwd=cwd,
    )
    stdout_data, stderr_data = await proc.communicate(input=None)
    returncode = await proc.wait()
    if returncode != 0:
        raise AsyncCalledProcessError(
            returncode, popenargs[0], output=stdout_data, stderr=stderr_data
        )
    return stdout_data


async def call(args, *, cwd, env=None, shell=False):
    """
    Similar to subprocess.call but adapted for asyncio. Please add new arguments as needed.
    cwd is added as an explicit argument because asyncio will not work well with os.chdir, which is not bound to the
    context of the running coroutine.
    """
    create_func = (
        asyncio.create_subprocess_shell if shell else asyncio.create_subprocess_exec
    )
    popenargs = [args] if shell else args
    proc = await create_func(
        *popenargs,
        stdin=None,
        stdout=None,
        stderr=None,
        cwd=cwd,
        env=env,
    )
    return await proc.wait()
