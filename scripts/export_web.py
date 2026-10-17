"""Export a run's envelopes as static JSON for the hosted web app.

web/data/index.json        one row per company for the directory, search and compare
web/data/run.json          run metadata and change counts
web/data/companies/<orgnr>.json   the full envelope (snapshot fields stored once)
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

AREAS = {
    "identity": "Company record", "financials": "Financials", "leadership": "People & places",
    "web_presence": "Website & profiles", "activity": "Hiring & activity",
}


def pub(env: dict, field: str) -> list[dict]:
    return [c for c in env["claims"] if c["field"] == field and c["availability"] == "available"]


def first(env: dict, field: str):
    items = pub(env, field)
    return items[0]["value"] if items else None


def latest_fig(env: dict, field: str) -> dict | None:
    items = sorted([c for c in pub(env, field) if c["value"].get("account_type") == "SELSKAP"],
                   key=lambda c: c.get("reporting_period") or "")
    return items[-1]["value"] if items else None


def row(env: dict) -> dict:
    addr = first(env, "registered_address") or ""
    town = addr.split(",")[-1].strip()[5:].strip() if "," in addr else ""
    industry = next((c["value"] for c in pub(env, "industry") if c["value"].get("rank") == 1), None)
    form = first(env, "legal_form") or {}
    areas = {k: env["sections"].get(k, {}).get("state") == "available" for k in AREAS}
    return {
        "organisation_number": env["organisation_number"], "name": env.get("legal_name"),
        "legal_form": form.get("code"), "municipality": town.title() if town else None,
        "industry": industry.get("description") if industry else None, "industry_code": industry.get("code") if industry else None,
        "employees": first(env, "registered_employees"), "founded": first(env, "founded"),
        "revenue": latest_fig(env, "revenue"), "annual_result": latest_fig(env, "annual_result"),
        "equity": latest_fig(env, "equity"), "website": first(env, "official_website"),
        "social_profiles": [c["value"] for c in pub(env, "social_profile")],
        "open_positions": len(pub(env, "job_ad")), "hiring_signals": len(pub(env, "hiring_signal")),
        "news": len(pub(env, "dated_news")), "public_records": len(pub(env, "public_record")),
        "roles": len(pub(env, "role")), "workplaces": len(pub(env, "workplace")),
        "changes": len(env.get("changes") or []),
        "bankrupt": first(env, "status_konkurs") is True, "winding_up": first(env, "status_underAvvikling") is True,
        "areas": areas, "areas_found": sum(areas.values()),
        "summary": (env.get("summary") or {}).get("text", "")[:400],
    }


def pack(env: dict) -> dict:
    keys = ("source_url", "retrieved_at", "content_sha256", "snapshot_path", "source_class", "licence")
    snaps, index, evidence = [], {}, []
    for ev in env["evidence"]:
        k = tuple(ev.get(x) for x in keys)
        if k not in index:
            index[k] = len(snaps)
            snaps.append(dict(zip(keys, k)))
        evidence.append({**{x: v for x, v in ev.items() if x not in keys and x not in ("requested_url", "redirect_chain")},
                         "snapshot": index[k]})
    return {**env, "evidence": evidence, "snapshots": snaps}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("envelopes")
    ap.add_argument("--out", default="web/data")
    ap.add_argument("--report", help="run-report.json of the same run")
    args = ap.parse_args()
    out = Path(args.out)
    (out / "companies").mkdir(parents=True, exist_ok=True)
    envs = [json.loads(line) for line in open(args.envelopes, encoding="utf-8") if line.strip()]
    rows = []
    for env in envs:
        if not env.get("legal_name"):
            continue
        rows.append(row(env))
        (out / "companies" / f"{env['organisation_number']}.json").write_text(
            json.dumps(pack(env), ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    rows.sort(key=lambda r: (-r["areas_found"], r["name"] or ""))
    (out / "index.json").write_text(json.dumps(rows, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    meta = json.loads(Path(args.report).read_text()) if args.report else {}
    changes = [{"organisation_number": e["organisation_number"], "name": e.get("legal_name"), **c}
               for e in envs for c in (e.get("changes") or [])]
    (out / "run.json").write_text(json.dumps({
        "run_id": meta.get("run_id"), "started_at": meta.get("started_at"), "completed_at": meta.get("completed_at"),
        "companies": len(rows), "requests": meta.get("requests"), "cost_usd": meta.get("third_party_cost_usd", 0),
        "coverage": meta.get("coverage"),
        "changes": [{k: v for k, v in c.items() if k in ("organisation_number", "name", "type", "field", "material", "explanation", "detected_at")}
                    for c in changes][:2000],
    }, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"exported {len(rows)} companies to {out}")


if __name__ == "__main__":
    main()
