#!/usr/bin/env python3
import argparse
import asyncio
import sys

from lib import (
    get_unchecked_authors,
    wait_for_checkboxes,
)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("repo")
    parser.add_argument("version")
    parser.add_argument("--org", default="mitodl")
    parser.add_argument("--wait", default=False, action='store_true')
    args = parser.parse_args()

    if args.wait:
        loop = asyncio.get_event_loop()
        loop.run_until_complete(wait_for_checkboxes(args.org, args.repo, args.version))
        loop.close()
    else:
        unchecked_authors = get_unchecked_authors(args.org, args.repo, args.version)
        if unchecked_authors:
            print("Unchecked authors: {}".format(", ".join(unchecked_authors)))
            sys.exit(1)

if __name__ == "__main__":
    main()
