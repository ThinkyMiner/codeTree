import argparse
import os
from .server import run

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".", help="Path to repo root (default: current directory)")
    parser.add_argument("--exclude", action="append", default=[], metavar="PATH",
                        help="Path to leave out of the index, relative to the repo root (repeatable)")
    args = parser.parse_args()
    run(os.path.abspath(args.root), exclude=args.exclude)

if __name__ == "__main__":
    main()
