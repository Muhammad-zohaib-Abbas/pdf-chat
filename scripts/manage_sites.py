"""Create and manage websites (tenants) and their API keys.

    python -m scripts.manage_sites create --name "My Site"
    python -m scripts.manage_sites list
    python -m scripts.manage_sites rotate <site_id>
    python -m scripts.manage_sites disable <site_id>
    python -m scripts.manage_sites enable <site_id>
    python -m scripts.manage_sites adopt-legacy <site_id>

An API key is shown only once, when it is created or rotated.
"""

import argparse
import sys
from uuid import UUID

from app import sites


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)

    create = commands.add_parser("create")
    create.add_argument("--name", required=True)
    create.add_argument(
        "--adopt-legacy",
        action="store_true",
        help="also assign existing documents and conversations to this site",
    )

    commands.add_parser("list")

    for name in ("rotate", "disable", "enable", "adopt-legacy"):
        commands.add_parser(name).add_argument("site_id", type=UUID)

    args = parser.parse_args()

    if args.command == "create":
        site_id, api_key = sites.create_site(args.name.strip())
        print(f"Site ID: {site_id}")
        print(f"API key: {api_key}")
        print("Save this key now. It cannot be shown again.")
        if args.adopt_legacy:
            documents, conversations = sites.adopt_legacy_data(site_id)
            print(f"Adopted {documents} document rows, {conversations} conversations.")

    elif args.command == "list":
        for site_id, name, active, created in sites.list_sites():
            print(f"{site_id}  {'active ' if active else 'DISABLED'}  {name}  {created:%Y-%m-%d}")

    elif args.command == "rotate":
        api_key = sites.rotate_key(args.site_id)
        if api_key is None:
            print("Site not found.")
            return 1
        print(f"New API key: {api_key}")
        print("The old key no longer works. Save this one now.")

    elif args.command in ("disable", "enable"):
        if not sites.set_active(args.site_id, args.command == "enable"):
            print("Site not found.")
            return 1
        print(f"Site {args.command}d.")

    elif args.command == "adopt-legacy":
        try:
            documents, conversations = sites.adopt_legacy_data(args.site_id)
        except ValueError as error:
            print(error)
            return 1
        print(f"Adopted {documents} document rows, {conversations} conversations.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
