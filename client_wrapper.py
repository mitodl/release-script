"""Wrapper for HTTP client. Replaces httpx until it matures."""
import requests


class ClientWrapper:
    """Wrapper for requests or httpx to make an HTTP request"""

    async def get(self, *args, **kwargs):
        """GET request"""
        return requests.get(*args, **kwargs)

    async def post(self, *args, **kwargs):
        """POST request"""
        return requests.post(*args, **kwargs)

    async def delete(self, *args, **kwargs):
        """DELETE request"""
        return requests.delete(*args, **kwargs)
