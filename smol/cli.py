"""CLI entry point for smol: smol shrink, smol donut, smol daemon, etc."""

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="smol",
        description="Shrink any file to at most a chosen size",
    )
    parser.add_argument(
        "--version",
        action="version",
        version="smol 0.1.0",
    )

    # Default: show help if no subcommand given
    if argv is None:
        argv = sys.argv[1:]
    if not argv or argv[0] in ("--help", "-h"):
        parser.print_help()
        return 0

    # Handle known global flags
    if not argv or argv[0] in ("--help", "-h"):
        parser.print_help()
        return 0
    if argv[0] == "--version":
        print("smol 0.1.0")
        return 0

    # Handle unknown commands gracefully
    if argv and argv[0] not in ("shrink", "donut", "daemon", "integrate", "doctor"):
        print(f"Unknown command: {argv[0]}", file=sys.stderr)
        parser.print_help()
        return 2

    print("No command specified. Use `smol --help` to see available commands.")
    return 0


if __name__ == "__main__":
    sys.exit(main())