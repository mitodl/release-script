#!/usr/bin/env python3
"""Wait for all checkboxes to get checked off"""
import argparse
import asyncio

from lib import wait_for_checkboxes


def main():
    """Wait for all checkboxes to get checked off"""
    parser = argparse.ArgumentParser()
    parser.add_argument("repo")
    parser.add_argument("--org", default="mitodl")
    args = parser.parse_args()

    if "." in args.repo or "/" in args.repo:
        raise Exception("repo is just the repo name, not a URL or directory (ie 'micromasters')")

    loop = asyncio.get_event_loop()
    loop.run_until_complete(wait_for_checkboxes(args.org, args.repo))
    loop.close()


if __name__ == "__main__":
    main()
