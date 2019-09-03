"""asyncio subprocess create_subprocess_exec"""
import asyncio
import subprocess


async def check_call(args, *, env=None, shell=False):
    """
    Similar to subprocess.check_call but adapted for asyncio. Please add new arguments as needed.
    """
    returncode = await call(args, env=env, shell=shell)
    if returncode != 0:
        raise subprocess.CalledProcessError(returncode, args[0])


async def check_output(args, *, env=None, shell=False):
    """
    Similar to subprocess.check_output but adapted for asyncio. Please add new arguments as needed.
    """
    create_func = asyncio.create_subprocess_shell if shell else asyncio.create_subprocess_exec
    popenargs = [args] if shell else args
    proc = await create_func(
        *popenargs,
        stdin=None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    stdout_data, _ = await proc.communicate(input=None)
    returncode = await proc.wait()
    if returncode != 0:
        raise subprocess.CalledProcessError(returncode, args[0])
    return stdout_data


async def call(args, *, env=None, shell=False):
    """
    Similar to subprocess.call but adapted for asyncio. Please add new arguments as needed.
    """
    create_func = asyncio.create_subprocess_shell if shell else asyncio.create_subprocess_exec
    popenargs = [args] if shell else args
    proc = await create_func(
        *popenargs,
        stdin=None,
        stdout=None,
        stderr=None,
        env=env,
    )
    return await proc.wait()
