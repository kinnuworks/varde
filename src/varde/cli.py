"""Command line: `varde run --organisations batch.jsonl --output out/envelopes.jsonl`."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from .pipeline import coverage, load_previous, run_batch, save_state, validate
from .util import read_inputs, utc_now, write_jsonl


def _load_env() -> None:
    for candidate in (Path.cwd() / ".env", Path(__file__).resolve().parents[3] / ".env"):
        if candidate.exists():
            for line in candidate.read_text().splitlines():
                if "=" in line and not line.lstrip().startswith("#"):
                    key, value = line.split("=", 1)
                    os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def flatten(env: dict) -> dict:
    row: dict = {"organisation_number": env["organisation_number"], "legal_name": env.get("legal_name"),
                 "summary": env["summary"].get("text"), "unknowns": env["summary"].get("unknowns")}
    for c in env["claims"]:
        if c["availability"] != "available":
            row.setdefault("states", {})[c["field"]] = {"state": c["availability"], "reason": c.get("reason")}
            continue
        row.setdefault("facts", {}).setdefault(c["field"], []).append(c["value"])
    return row


def main(argv: list[str] | None = None) -> None:
    _load_env()
    parser = argparse.ArgumentParser(prog="varde", description="Research Norwegian companies by organisation number.")
    sub = parser.add_subparsers(dest="command")
    run = sub.add_parser("run", help="Research a batch and write one envelope per input")
    for p in (parser, run):
        p.add_argument("--organisations", "--input", dest="organisations", help="JSONL, JSON or text list of organisation numbers")
        p.add_argument("--output", default="out/envelopes.jsonl")
        p.add_argument("--profiles-output")
        p.add_argument("--report")
        p.add_argument("--run-id")
        p.add_argument("--expected-count", type=int)
        p.add_argument("--previous", help="Envelopes from an earlier run to diff against")
        p.add_argument("--state-dir", help="Keep run history here and diff against the latest run")
        p.add_argument("--max-requests", type=int, default=int(os.environ.get("VARDE_MAX_REQUESTS", "0")) or None)
        p.add_argument("--time-budget", type=float, default=float(os.environ.get("VARDE_TIME_BUDGET", "2400")))
        p.add_argument("--per-company-requests", type=int, default=int(os.environ.get("VARDE_PER_COMPANY", "40")))
        p.add_argument("--concurrency", type=int, default=int(os.environ.get("VARDE_CONCURRENCY", "48")))
        p.add_argument("--no-html", action="store_true")
        # Accepted for compatibility with the Signalpost starter harness; not needed here.
        for flag in ("--bulk", "--workers", "--checkpoint-every", "--modules"):
            p.add_argument(flag)
        p.add_argument("--resume", action="store_true")
    args = parser.parse_args(argv)
    if not args.organisations:
        parser.error("--organisations is required")

    orgs = read_inputs(args.organisations)
    if args.expected_count is not None and len(orgs) != args.expected_count:
        print(f"warning: expected {args.expected_count} organisations, received {len(orgs)}", file=sys.stderr)
    out = Path(args.output)
    out_dir = out.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    run_id = args.run_id or "varde-" + utc_now().replace(":", "").replace("-", "")
    previous = load_previous(args.previous, args.state_dir)
    max_requests = args.max_requests or max(2000, 40 * len(orgs))

    envelopes, report = asyncio.run(run_batch(
        orgs, out_dir, run_id, previous=previous, max_requests=max_requests, time_budget=args.time_budget,
        per_company=args.per_company_requests, concurrency=args.concurrency))

    write_jsonl(out, envelopes)
    write_jsonl(Path(args.profiles_output) if args.profiles_output else out_dir / "profiles.jsonl",
                [flatten(e) for e in envelopes])
    report["coverage"] = coverage(envelopes)
    report["validation"] = validate(envelopes, orgs)
    report["changes"] = sum(len(e["changes"]) for e in envelopes)
    Path(args.report or out_dir / "run-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    if args.state_dir:
        save_state(args.state_dir, envelopes, run_id)
    if not args.no_html:
        try:
            from .report import write_report
            slim = []
            for e in envelopes:
                e2 = dict(e)
                e2["evidence"] = [{k: v for k, v in x.items() if k not in ("requested_url", "http_status", "redirect_chain")}
                                  for x in e["evidence"]]
                slim.append(e2)
            write_report(slim, out_dir / "report.html", {
                "agent": report["agent"], "version": report["version"], "run_id": run_id,
                "started_at": report["started_at"], "completed_at": report["completed_at"],
                "companies": len(envelopes), "requests": report["requests"], "cost_usd": 0})
        except Exception as exc:  # the report is a view; it must never fail the run
            print(f"warning: report.html not written: {exc}", file=sys.stderr)
    summary = {k: report[k] for k in ("run_id", "emitted_envelopes", "requests", "runtime_s", "p50_ms", "p95_ms")}
    summary["coverage"] = report["coverage"]
    summary["validation"] = report["validation"]["checks"]
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    # Exit non-zero only when the batch contract itself is broken.
    sys.exit(0 if report["validation"]["checks"]["one_envelope_per_input"] else 1)


if __name__ == "__main__":
    main()
