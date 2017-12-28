"""Exceptions for release script"""


class InputException(Exception):
    """Exception raised for invalid input."""


class ReleaseException(Exception):
    """Exception raised for a command error due to some release status"""


class TokenException(Exception):
    """The token failed to validate"""
