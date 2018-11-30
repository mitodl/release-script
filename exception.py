"""Exceptions for release script"""


class InputException(Exception):
    """Exception raised for invalid input."""


class RebaseException(Exception):
    """Exception during a rebase"""


class ReleaseException(Exception):
    """Exception raised for a command error due to some release status"""


class ResetException(Exception):
    """Exception meant to reset the process"""
