"""Command-line entrypoints used by packaged launchers and development checks."""

import argparse
import asyncio
import json

from .diagnostics import passive_status, resolve_root
from .storage import read_json


def configured_core(root=None, allow_root=(), output_root=()):
    from .core import Core

    root = resolve_root(root)
    config = read_json(root / "settings.json") if (root / "settings.json").is_file() else {}
    return Core(
        root,
        allow_root or config.get("allowed_roots", []),
        output_root or config.get("output_roots", []),
    )


def main():
    parser = argparse.ArgumentParser(description="MATLAB Companion")
    parser.add_argument(
        "command",
        choices=["serve", "status", "setup", "self-test", "coordinator"],
        nargs="?",
        default="serve",
    )
    parser.add_argument("--root")
    parser.add_argument("--allow-root", action="append", default=[])
    parser.add_argument("--output-root", action="append", default=[])
    parser.add_argument("--idle-seconds", type=float, default=30, help=argparse.SUPPRESS)
    args = parser.parse_args()
    root = resolve_root(args.root)
    if args.command == "setup":
        from .setup_ui import main as setup_main

        setup_main(root)
        return
    if args.command == "serve":
        from .client import CoordinatorClient
        from .server import serve

        core = CoordinatorClient(
            root, args.allow_root, args.output_root, idle_seconds=args.idle_seconds
        )
        asyncio.run(serve(core))
    elif args.command == "coordinator":
        from .coordinator import Coordinator

        Coordinator(root, args.allow_root, args.output_root, idle_seconds=args.idle_seconds).run()
    else:
        print(json.dumps(passive_status(root), indent=2))
        if args.command == "self-test":
            from .contracts import operation_schemas

            assert len(operation_schemas()) == 5
            print("PASS: portable contracts loaded; native acceptance is separate.")


if __name__ == "__main__":
    main()
