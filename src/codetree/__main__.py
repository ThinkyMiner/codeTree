import argparse
import os
from .indexer import exclude_prefixes
from .server import run

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".", help="Path to repo root (default: current directory)")
    parser.add_argument("--exclude", action="append", default=[], metavar="PATH",
                        help="Path to leave out of the index, relative to the repo root (repeatable)")
    args = parser.parse_args()
    root = os.path.abspath(args.root)
    try:
        exclude_prefixes(root, args.exclude)
    except ValueError as error:
        parser.error(str(error))
    run(root, exclude=args.exclude)

if __name__ == "__main__":
    main()
