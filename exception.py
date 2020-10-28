"""Exceptions for release script"""
from subprocess import CalledProcessError


class InputException(Exception):
    """Exception raised for invalid input."""


class ReleaseException(Exception):
    """Exception raised for a command error due to some release status"""


class ResetException(Exception):
    """Exception meant to reset the process"""


class DependencyException(Exception):
    """Error if dependency is missing"""


class UpdateVersionException(Exception):
    """Error if the old version is invalid or cannot be found, or if there's a duplicate version"""


class VersionMismatchException(Exception):
    """Error if the version is unexpected"""


class AsyncCalledProcessError(CalledProcessError):
    """Extend CalledProcessError to print the stdout as well"""

    def __str__(self):
        super_str = super().__str__()
        return f"{super_str}. stdout={self.stdout}, stderr={self.stderr}"
