#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


TABLE_HEADERS = [
    "case",
    "base us",
    "cand us",
    "delta",
    "metric",
    "base",
    "cand",
    "status",
]


def load_results(path: Path) -> dict[str, dict[str, object]]:
    rows: dict[str, dict[str, object]] = {}
    for line_no, line in enumerate(path.read_text().splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        case = row.get("case")
        if not isinstance(case, str):
            raise RuntimeError(f"{path}:{line_no}: missing string case")
        rows[case] = row
    return rows


def pct(delta: float, base: float) -> float:
    return 100.0 * delta / base if base else 0.0


def rate(row: dict[str, object]) -> tuple[str, float]:
    if "flops" in row:
        return ("tflops", float(row["flops"]) / 1e12)
    if "bandwidth_gb_s" in row:
        return ("gb_s", float(row["bandwidth_gb_s"]))
    return ("rate", 0.0)


def shape(values: list[object]) -> str:
    return "[" + "x".join(str(v) for v in values) + "]"


def case_name(row: dict[str, object], fallback: str) -> str:
    op = row.get("op")
    dtype = row.get("type")
    ne = row.get("ne")
    src0_type = row.get("src0_type")
    src0_ne = row.get("src0_ne")
    src1_type = row.get("src1_type")
    src1_ne = row.get("src1_ne")
    if isinstance(op, str) and isinstance(dtype, str) and isinstance(ne, list):
        parts = [op, f"dst={dtype}{shape(ne)}"]
        if isinstance(src0_type, str) and isinstance(src0_ne, list):
            parts.append(f"a={src0_type}{shape(src0_ne)}")
        if isinstance(src1_type, str) and isinstance(src1_ne, list):
            parts.append(f"b={src1_type}{shape(src1_ne)}")
        return " ".join(parts)
    return fallback


def print_table(rows: list[dict[str, object]]) -> None:
    widths = [44, 10, 10, 9, 8, 10, 10, 10]
    fmt = "  ".join(f"{{:<{width}}}" for width in widths)
    print(fmt.format(*TABLE_HEADERS))
    print(fmt.format(*["-" * width for width in widths]))
    for row in rows:
        print(
            fmt.format(
                str(row["case"])[: widths[0]],
                row["base_us"],
                row["cand_us"],
                row["delta"],
                row["metric"],
                row["base_rate"],
                row["cand_rate"],
                row["status"],
            )
        )


def markdown_cell(value: object) -> str:
    text = str(value)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text.replace("|", r"\|").replace("\n", "<br>")


def append_markdown_list(lines: list[str], title: str, items: list[str]) -> None:
    if not items:
        return
    lines.extend(["", f"#### {title}"])
    lines.extend(f"- {markdown_cell(item)}" for item in items)


def render_step_summary(
    baseline_path: Path,
    candidate_path: Path,
    max_regression_pct: float,
    table_rows: list[dict[str, object]],
    missing: list[str],
    extra: list[str],
    failures: list[str],
) -> str:
    keys = [
        "case",
        "base_us",
        "cand_us",
        "delta",
        "metric",
        "base_rate",
        "cand_rate",
        "status",
    ]
    lines = [
        "### Op perf comparison",
        "",
        f"- Baseline: `{baseline_path}`",
        f"- Candidate: `{candidate_path}`",
        f"- Max regression threshold: `{max_regression_pct:.2f}%`",
        "",
        "| " + " | ".join(TABLE_HEADERS) + " |",
        "| " + " | ".join("---" for _ in TABLE_HEADERS) + " |",
    ]
    for row in table_rows:
        lines.append("| " + " | ".join(markdown_cell(row[key]) for key in keys) + " |")

    append_markdown_list(lines, "Missing candidate cases", missing)
    append_markdown_list(lines, "Extra candidate cases", extra)
    append_markdown_list(lines, "Regression failures", failures)

    if failures:
        lines.extend(["", "**Result:** failed. Comparison checks did not pass."])
    else:
        lines.extend(["", "**Result:** passed. No timing regressions exceeded the threshold."])

    return "\n".join(lines) + "\n"


def render_skipped_step_summary(
    baseline_path: Path,
    candidate_path: Path,
    max_regression_pct: float,
) -> str:
    return "\n".join(
        [
            "### Op perf comparison",
            "",
            "Comparison skipped because the baseline perf JSONL was missing.",
            "",
            f"- Baseline: `{baseline_path}`",
            f"- Candidate: `{candidate_path}`",
            f"- Max regression threshold: `{max_regression_pct:.2f}%`",
            "",
            "**Result:** skipped.",
        ]
    ) + "\n"


def append_step_summary(markdown: str) -> None:
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return
    with Path(summary_path).open("a", encoding="utf-8") as summary_file:
        summary_file.write(markdown)


def require_file(path: Path, label: str) -> None:
    if not path.is_file():
        print(f"{label} perf JSONL does not exist: {path}", file=sys.stderr)
        raise SystemExit(1)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare op perf JSONL files and fail on timing regressions."
    )
    parser.add_argument("baseline", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument(
        "--max-regression-pct",
        type=float,
        default=5.0,
        help="Allowed candidate time_us increase per case before failing",
    )
    parser.add_argument(
        "--require-all-cases",
        action="store_true",
        help="Fail if any baseline case is missing from the candidate",
    )
    parser.add_argument(
        "--skip-missing-baseline",
        action="store_true",
        help="Exit successfully when the baseline JSONL file is absent",
    )
    args = parser.parse_args()

    require_file(args.candidate, "Candidate")
    if not args.baseline.is_file():
        if args.skip_missing_baseline:
            print(
                f"Baseline perf JSONL is missing; skipping comparison: {args.baseline}"
            )
            append_step_summary(
                render_skipped_step_summary(
                    args.baseline,
                    args.candidate,
                    args.max_regression_pct,
                )
            )
            raise SystemExit(0)
        require_file(args.baseline, "Baseline")

    baseline = load_results(args.baseline)
    candidate = load_results(args.candidate)

    failures: list[str] = []
    table_rows: list[dict[str, object]] = []
    missing: list[str] = []
    for case in sorted(baseline):
        if case not in candidate:
            message = case_name(baseline[case], case)
            if args.require_all_cases:
                failures.append(f"{message}: missing from candidate")
            missing.append(message)
            continue

        base = baseline[case]
        cand = candidate[case]
        base_us = float(base["time_us"])
        cand_us = float(cand["time_us"])
        delta_pct = pct(cand_us - base_us, base_us)
        base_metric, base_rate = rate(base)
        cand_metric, cand_rate = rate(cand)
        metric = base_metric if base_metric == cand_metric else f"{base_metric}/{cand_metric}"
        status = "ok"

        if delta_pct > args.max_regression_pct:
            status = "regress"
            failures.append(
                f"{case_name(base, case)}: {cand_us:.3f} us vs {base_us:.3f} us "
                f"({delta_pct:+.2f}%, limit +{args.max_regression_pct:.2f}%)"
            )

        table_rows.append(
            {
                "case": case_name(base, case),
                "base_us": f"{base_us:.3f}",
                "cand_us": f"{cand_us:.3f}",
                "delta": f"{delta_pct:+.2f}%",
                "metric": metric,
                "base_rate": f"{base_rate:.3f}",
                "cand_rate": f"{cand_rate:.3f}",
                "status": status,
            }
        )

    print_table(table_rows)

    if missing:
        print("\nMissing candidate cases:")
        for case in missing:
            print(f"  {case}")

    extra = [case_name(candidate[case], case) for case in sorted(set(candidate) - set(baseline))]
    if extra:
        print("\nExtra candidate cases:")
        for case in extra:
            print(f"  {case}")

    append_step_summary(
        render_step_summary(
            args.baseline,
            args.candidate,
            args.max_regression_pct,
            table_rows,
            missing,
            extra,
            failures,
        )
    )

    if failures:
        print("\nRegressions:")
        for failure in failures:
            print(f"  {failure}")
        raise SystemExit(1)

    print("\nNo timing regressions exceeded the threshold.")


if __name__ == "__main__":
    main()
