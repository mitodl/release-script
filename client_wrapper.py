"""Wrapper for HTTP client. Replaces httpx until it matures."""
import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry


class ClientWrapper:
    """Wrapper for requests or httpx to make an HTTP request"""

    def __init__(self):
        self.session = requests.Session()
        adapter = HTTPAdapter(max_retries=Retry(status_forcelist=[502, 503]))
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

    async def get(self, *args, **kwargs):
        """GET request"""
        return self.session.get(*args, **kwargs)

    async def post(self, *args, **kwargs):
        """POST request"""
        return self.session.post(*args, **kwargs)

    async def delete(self, *args, **kwargs):
        """DELETE request"""
        return self.session.delete(*args, **kwargs)
