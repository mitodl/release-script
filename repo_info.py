"""Information about repositories"""
from collections import namedtuple

RepoInfo = namedtuple('RepoInfo', [
    'name',
    'repo_url',
    'rc_hash_url',
    'prod_hash_url',
    'channel_id',
    'project_type',
    'web_application_type',
    'packaging_tool',
    'announcements',
])
