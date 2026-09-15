"""Command-line entrypoints used by packaged launchers and development checks."""

import argparse
import asyncio
import json
from pathlib import Path

from .core import Core
from .server import serve
from .storage import default_root, read_json


def configured_core(root=None, allow_root=(), output_root=()):
    root = Path(root) if root else default_root()
    config = read_json(root / "settings.json") if (root / "settings.json").is_file() else {}
    return Core(
        root,
        allow_root or config.get("allowed_roots", []),
        output_root or config.get("output_roots", []),
    )


def main():
    parser = argparse.ArgumentParser(description="MATLAB Companion")
    parser.add_argument(
        "command", choices=["serve", "status", "setup", "self-test"], nargs="?", default="serve"
    )
    parser.add_argument("--root")
    parser.add_argument("--allow-root", action="append", default=[])
    parser.add_argument("--output-root", action="append", default=[])
    args = parser.parse_args()
    if args.command == "setup":
        from .setup_ui import main as setup_main

        setup_main()
        return
    core = configured_core(args.root, args.allow_root, args.output_root)
    if args.command == "serve":
        asyncio.run(serve(core))
    else:
        try:
            print(json.dumps(core.call("matlab_status", {}), indent=2))
            if args.command == "self-test":
                from .contracts import operation_schemas

                assert len(operation_schemas()) == 5
                print("PASS: portable contracts loaded; native acceptance is separate.")
        finally:
            core.close()


if __name__ == "__main__":
    main()
