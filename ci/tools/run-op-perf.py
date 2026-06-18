#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


PERF_RE = re.compile(
    r"^\s*(?P<op>[A-Z0-9_]+)\((?P<params>.*)\):\s+"
    r"(?P<runs>\d+)\s+runs\s+-\s+"
    r"(?P<time_us>[0-9.]+)\s+us/run\s+-\s+"
    r"(?:(?P<work>[0-9.]+)\s+(?P<work_unit>[A-Z]+)LOP/run\s+-\s+"
    r"(?P<rate>[0-9.]+)\s+(?P<rate_unit>[A-Z]+)LOPS|"
    r"(?P<memory_kb>\d+)\s+kB/run\s+-\s+"
    r"(?P<bandwidth_gb_s>[0-9.]+)\s+GB/s)"
)

PARAM_RE = re.compile(
    r"type=(?P<type>[^,]+),ne=\[(?P<ne>[^\]]+)\]"
)

SRC_RE = re.compile(
    r"src(?P<index>\d+)=\{type=(?P<type>[^,]+),ne=\[(?P<ne>[^\]]+)\]\}"
)

UNIT_SCALE = {
    "k": 1e3,
    "M": 1e6,
    "G": 1e9,
    "T": 1e12,
}


def parse_ne(raw: str | None) -> list[int] | None:
    if raw is None:
        return None
    return [int(part.strip()) for part in raw.split(",")]


def shape_label(ne: list[int] | None) -> str:
    if ne is None:
        return "none"
    return "x".join(str(v) for v in ne)


def parse_perf_line(line: str) -> dict[str, object] | None:
    line = re.sub(r"\x1b\[[0-9;]*m", "", line)
    match = PERF_RE.match(line)
    if not match:
        return None

    params = match.group("params")
    param_match = PARAM_RE.search(params)
    if not param_match:
        raise RuntimeError(f"Could not parse op params: {params}")

    ne = parse_ne(param_match.group("ne"))
    op = match.group("op")
    dtype = param_match.group("type")
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

    row: dict[str, object] = {
        "case": f"{op}_{dtype}_{shape_label(ne)}_{src0_type or 'nosrc0'}_{shape_label(src0_ne)}_{src1_type or 'nosrc1'}_{shape_label(src1_ne)}",
        "op": op,
        "type": dtype,
        "ne": ne,
        "src0_type": src0_type,
        "src0_ne": src0_ne,
        "src1_type": src1_type,
        "src1_ne": src1_ne,
        "runs": int(match.group("runs")),
        "time_us": float(match.group("time_us")),
    }

    if match.group("rate"):
        rate_unit = match.group("rate_unit")
        work_unit = match.group("work_unit")
        row["flops_per_run"] = float(match.group("work")) * UNIT_SCALE[work_unit]
        row["flops"] = float(match.group("rate")) * UNIT_SCALE[rate_unit]
    else:
        row["memory_kb"] = int(match.group("memory_kb"))
        row["bandwidth_gb_s"] = float(match.group("bandwidth_gb_s"))

    return row


def run_perf(args: argparse.Namespace) -> list[dict[str, object]]:
    cmd = [
        str(args.test_backend_ops),
        "perf",
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
        parsed = parse_perf_line(line)
        if parsed is not None:
            parsed["backend"] = args.backend
            parsed["test_file"] = str(args.test_file)
            results.append(parsed)

    if proc.returncode != 0:
        sys.stderr.write(proc.stdout)
        raise SystemExit(proc.returncode)
    if not results:
        sys.stderr.write(proc.stdout)
        raise SystemExit(f"No {args.op} perf results were parsed")
    return results


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run test-backend-ops perf for exported graph-op cases."
    )
    parser.add_argument("--op", default="MUL_MAT", help="Operation passed to test-backend-ops -o")
    parser.add_argument("--backend", default="HRX0", help="Backend passed to test-backend-ops -b")
    parser.add_argument("--test-backend-ops", type=Path, required=True)
    parser.add_argument("--test-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--raw-output", type=Path, default=None)
    parser.add_argument("extra_arg", nargs=argparse.REMAINDER)
    args = parser.parse_args()

    results = run_perf(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(json.dumps(row, sort_keys=True) for row in results) + "\n")
    print(f"wrote {len(results)} results to {args.output}")


if __name__ == "__main__":
    main()
