"""Exceptions for release script"""


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
