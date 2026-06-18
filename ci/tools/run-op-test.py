#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


RESULT_RE = re.compile(r"^\s*(?P<op>[A-Z0-9_]+)\((?P<params>.*)\):\s+(?P<status>OK|FAIL|not supported.*)$")

PARAM_RE = re.compile(
    r"type=(?P<type>[^,]+),ne=\[(?P<ne>[^\]]+)\]"
)

SRC_RE = re.compile(
    r"src(?P<index>\d+)=\{type=(?P<type>[^,]+),ne=\[(?P<ne>[^\]]+)\]\}"
)


def strip_ansi(text: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def parse_ne(raw: str | None) -> list[int] | None:
    if raw is None:
        return None
    return [int(part.strip()) for part in raw.split(",")]


def shape_label(ne: list[int] | None) -> str:
    if ne is None:
        return "none"
    return "x".join(str(v) for v in ne)


def parse_result_line(line: str) -> dict[str, object] | None:
    line = strip_ansi(line)
    match = RESULT_RE.match(line)
    if not match:
        return None

    params = match.group("params")
    param_match = PARAM_RE.search(params)
    if not param_match:
        raise RuntimeError(f"Could not parse op params: {params}")

    op = match.group("op")
    dtype = param_match.group("type")
    ne = parse_ne(param_match.group("ne"))
    sources = {
        int(src.group("index")): {
            "type": src.group("type"),
            "ne": parse_ne(src.group("ne")),
        }
        for src in SRC_RE.finditer(params)
    }
    src0 = sources.get(0, {})
    src1 = sources.get(1, {})
    src0_type = src0.get("type")
    src0_ne = src0.get("ne")
    src1_type = src1.get("type")
    src1_ne = src1.get("ne")
    status = match.group("status")
    supported = not status.startswith("not supported")
    passed = status == "OK"

    return {
        "case": f"{op}_{dtype}_{shape_label(ne)}_{src0_type or 'nosrc0'}_{shape_label(src0_ne)}_{src1_type or 'nosrc1'}_{shape_label(src1_ne)}",
        "op": op,
        "type": dtype,
        "ne": ne,
        "src0_type": src0_type,
        "src0_ne": src0_ne,
        "src1_type": src1_type,
        "src1_ne": src1_ne,
        "supported": supported,
        "passed": passed,
        "status": status,
    }


def run_test(args: argparse.Namespace) -> list[dict[str, object]]:
    cmd = [
        str(args.test_backend_ops),
        "test",
        "-o",
        args.op,
        "-b",
        args.backend,
        "--test-file",
        str(args.test_file),
    ]
    if args.extra_arg:
        cmd.extend(args.extra_arg)

    proc = subprocess.run(
        cmd,
        cwd=REPO_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if args.raw_output:
        args.raw_output.parent.mkdir(parents=True, exist_ok=True)
        args.raw_output.write_text(proc.stdout)

    results = []
    for line in proc.stdout.splitlines():
        parsed = parse_result_line(line)
        if parsed is not None:
            parsed["backend"] = args.backend
            parsed["test_file"] = str(args.test_file)
            results.append(parsed)

    if proc.returncode != 0 and not results:
        sys.stderr.write(proc.stdout)
        raise SystemExit(proc.returncode)
    if not results:
        sys.stderr.write(proc.stdout)
        raise SystemExit(f"No {args.op} test results were parsed")
    return results


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run test-backend-ops correctness tests for exported graph-op cases."
    )
    parser.add_argument("--op", default="MUL_MAT", help="Operation passed to test-backend-ops -o")
    parser.add_argument("--backend", default="CPU", help="Backend passed to test-backend-ops -b")
    parser.add_argument("--test-backend-ops", type=Path, required=True)
    parser.add_argument("--test-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--raw-output", type=Path, default=None)
    parser.add_argument("extra_arg", nargs=argparse.REMAINDER)
    args = parser.parse_args()

    results = run_test(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(json.dumps(row, sort_keys=True) for row in results) + "\n")

    failed = [row for row in results if not row["passed"]]
    print(f"wrote {len(results)} results to {args.output}")
    if failed:
        print(f"{len(failed)} cases failed or were unsupported")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
