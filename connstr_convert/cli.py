import argparse
import sys

from .core import parse_dsn, parse_uri, to_dsn, to_uri


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="connstr-convert",
        description="Convert a database connection string between DSN and URI form.",
    )
    parser.add_argument(
        "connection_string",
        help="input connection string, either 'key=value ...' or 'scheme://...'",
    )
    parser.add_argument(
        "--to",
        choices=("uri", "dsn"),
        required=True,
        help="output format",
    )
    parser.add_argument(
        "--scheme",
        default=None,
        help="scheme to use for URI output (defaults to the input scheme, or postgresql)",
    )
    args = parser.parse_args(argv)

    try:
        if "://" in args.connection_string:
            parsed = parse_uri(args.connection_string)
        else:
            parsed = parse_dsn(args.connection_string)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.to == "uri":
        print(to_uri(parsed, scheme=args.scheme))
    else:
        print(to_dsn(parsed))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
