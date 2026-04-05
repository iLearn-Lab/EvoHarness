from __future__ import annotations

import argparse
import base64
import subprocess
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="evoh-task-runner")
    parser.add_argument("--command")
    parser.add_argument("--command-file")
    parser.add_argument("--command-b64")
    parser.add_argument("--cwd", required=True)
    parser.add_argument("--log-file", required=True)
    parser.add_argument("--exit-file", required=True)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    cwd = Path(args.cwd).resolve()
    log_file = Path(args.log_file).resolve()
    exit_file = Path(args.exit_file).resolve()
    modes = [bool(args.command), bool(args.command_file), bool(args.command_b64)]
    if sum(1 for item in modes if item) != 1:
        raise SystemExit("Pass exactly one of --command, --command-file, or --command-b64")
    command = args.command
    if args.command_file:
        command = Path(args.command_file).resolve().read_text(encoding="utf-8")
    if args.command_b64:
        command = base64.b64decode(args.command_b64.encode("ascii")).decode("utf-8")
    assert command is not None
    log_file.parent.mkdir(parents=True, exist_ok=True)
    exit_file.parent.mkdir(parents=True, exist_ok=True)

    with log_file.open("ab") as handle:
        process = subprocess.run(
            command,
            cwd=str(cwd),
            shell=True,
            stdout=handle,
            stderr=subprocess.STDOUT,
            check=False,
        )
    exit_file.write_text(str(process.returncode), encoding="utf-8")


if __name__ == "__main__":
    main()
