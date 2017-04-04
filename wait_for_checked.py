#!/usr/bin/env python3
"""Wait for all checkboxes to get checked off"""
import argparse
import asyncio

from lib import wait_for_checkboxes


def main():
    """Wait for all checkboxes to get checked off"""
    parser = argparse.ArgumentParser()
    parser.add_argument("repo")
    parser.add_argument("version")
    parser.add_argument("--org", default="mitodl")
    args = parser.parse_args()

    loop = asyncio.get_event_loop()
    loop.run_until_complete(wait_for_checkboxes(args.org, args.repo, args.version))
    loop.close()

if __name__ == "__main__":
    main()
