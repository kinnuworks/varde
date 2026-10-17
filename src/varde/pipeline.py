"""Batch driver: one terminal envelope per input, always."""
from __future__ import annotations

import asyncio
import gzip
import json
import os
import time
from datetime import datetime, timedelta, timezone
from importlib import resources
from pathlib import Path
from typing import Any

import httpx

from . import AGENT_NAME, __version__, writer
from .net import Budget, Fetcher, SnapshotStore
from .profile import SECTIONS, Profile
from .refresh import diff
from .sources import brreg, registers
from .synthesis import template
from .util import core_name, read_jsonl, utc_now, valid_orgnr, write_jsonl
from .web import site

PER_COMPANY_TIMEOUT = 150.0


def _load_seeds() -> dict[str, list[str]]:
    try:
        raw = resources.files("varde.data").joinpath("website_seeds.json.gz").read_bytes()
        return json.loads(gzip.decompress(raw)).get("seeds", {})
    except (FileNotFoundError, ModuleNotFoundError, OSError, ValueError):
        return {}


def _commit() -> str | None:
    head = Path(__file__).resolve().parents[2] / ".git" / "HEAD"
    try:
        ref = head.read_text().strip()
        if ref.startswith("ref: "):
            return (head.parent / ref[5:]).read_text().strip()
        return ref
    except OSError:
        return None


def envelope(p: Profile, completed_at: str, ops: dict, status: str = "completed") -> dict:
    for key in SECTIONS:
        if key not in p.sections:
            if key == "evidence":
                p.sections[key] = {"state": "available" if p.evidence else "not_available"}
            elif key == "refresh":
                p.sections[key] = {"state": "not_applicable", "reason": "First run for this company."}
            else:
                p.sections[key] = {"state": "not_available", "reason": "Nothing found in the checked sources."}
    for key, section in p.sections.items():
        section["claim_ids"] = [c["id"] for c in p.claims if c["section"] == key]
        section["title"] = SECTIONS.get(key, key)
    return {
        "organisation_number": p.organisation_number,
        "agent": {"name": AGENT_NAME, "version": __version__, "commit": _commit()},
        "run": {"run_id": p.run_id, "started_at": p.started_at, "completed_at": completed_at,
                "terminal_status": status},
        "state": "complete" if status == "completed" else "failed",
        "legal_name": p.legal_name,
        "sections": p.sections,
        "claims": p.claims,
        "evidence": p.evidence,
        "summary": p.context.get("summary") or {"text": "", "sentences": [], "unknowns": []},
        "changes": p.changes,
        "refresh": p.context.get("refresh") or {},
        "errors": p.errors,
        "operations": ops,
    }


async def research(p: Profile, f: Fetcher, shared: dict, previous: dict | None) -> None:
    org = p.organisation_number
    rec = await brreg.entity(p, f)
    if rec is None:
        return
    await asyncio.gather(brreg.roles(p, f), brreg.subunits(p, f), brreg.accounts(p, f),
                         brreg.held_roles(p, f), registers.doffin(p, f))
    await brreg.group_structure(p, f)
    p.context["group_orgs"] = {c["value"]["organisation_number"] for c in p.published("group_relation")}
    registers.gleif_claims(p, shared["gleif"].get(org))
    registers.wikidata_claims(p, shared["wikidata"].get(org))
    registers.ted_claims(p, shared["ted"].get(org))
    brreg.feed_events(p, shared["updates"].get(org, []))
    sub_orgs = {u.get("organisasjonsnummer") for u in p.context.get("subunits", []) if u.get("organisasjonsnummer")}
    await registers.nav_jobs(p, f, shared["nav"], sub_orgs)
    nav_homes = [ad.get("homepage") for o in [org, *sub_orgs] for ad in shared["nav"].index.get(o, []) if ad.get("homepage")]
    if f.budget.remaining_s() > 90:
        await site.website(p, f, shared["seeds"], nav_homes)
    else:
        p.mark_field("official_website", "web_presence", "failed", "Batch time budget reached before the website step.")


async def run_batch(orgs: list[str], out_dir: Path, run_id: str, *, previous: dict[str, dict],
                    max_requests: int, time_budget: float, per_company: int, concurrency: int) -> tuple[list[dict], dict]:
    started = utc_now()
    t0 = time.monotonic()
    budget = Budget(max_requests, time_budget, per_company)
    store = SnapshotStore(out_dir / "snapshots")
    fetcher = Fetcher(store, budget)
    valid = [o for o in orgs if valid_orgnr(o)]
    since = (datetime.now(timezone.utc) - timedelta(days=365)).strftime("%Y-%m-%dT00:00:00.000Z")
    nav = registers.NavIndex()
    gleif, wikidata, ted, (_, updates), bulk_names = await asyncio.gather(
        registers.gleif_batch(fetcher, valid), registers.wikidata_batch(fetcher, valid),
        registers.ted_batch(fetcher, valid), brreg.update_feed(fetcher, valid, since),
        brreg.batch_names(fetcher, valid))
    names: dict[str, list[str]] = {}
    for o in valid:
        row = bulk_names.get(o)
        if row:
            names.setdefault(core_name(row), []).append(o)
    await nav.refresh(fetcher, names)
    shared = {"gleif": gleif, "wikidata": wikidata, "ted": ted, "updates": updates, "nav": nav, "seeds": _load_seeds()}
    sem = asyncio.Semaphore(concurrency)
    profiles: dict[str, Profile] = {}
    timing: dict[str, int] = {}

    async def one(org: str) -> None:
        p = Profile(org, run_id)
        profiles[org] = p
        if not valid_orgnr(org):
            p.error("input", f"Invalid organisation number: {org!r}")
            p.mark("identity", "failed", "Input is not a valid Norwegian organisation number.")
            return
        async with sem:
            start = time.monotonic()
            try:
                await asyncio.wait_for(research(p, fetcher, shared, previous.get(org)),
                                       timeout=min(PER_COMPANY_TIMEOUT, max(5.0, budget.remaining_s() - 20)))
            except asyncio.TimeoutError:
                p.error("pipeline", "Per-company time limit reached; remaining steps marked failed.")
                for section in ("web_presence", "activity"):
                    p.mark(section, "failed", "Time limit reached before this step finished.")
            except Exception as exc:  # one company's failure never stops the batch
                p.error("pipeline", f"{type(exc).__name__}: {exc}")
                p.mark("identity", "failed", "Unexpected error while researching this company.")
            timing[org] = int((time.monotonic() - start) * 1000)

    await asyncio.gather(*(one(o) for o in orgs))
    retry = [profiles[o] for o in orgs if profiles[o].context.pop("web_retry", False)]
    if retry and budget.remaining_s() > 120:
        async def again(p: Profile) -> None:
            p.claims = [c for c in p.claims if not (c["field"] == "official_website" and c["availability"] != "available")]
            p.sections.pop("web_presence", None)
            async with sem:
                try:
                    await asyncio.wait_for(site.website(p, fetcher, shared["seeds"], []), timeout=60)
                except asyncio.TimeoutError:
                    p.mark_field("official_website", "web_presence", "failed", "Website step timed out twice.")
        await asyncio.gather(*(again(p) for p in retry))
    await fetcher.close()
    for org in orgs:
        diff(profiles[org], previous.get(org))
    llm_calls = 0
    if writer.enabled() and budget.remaining_s() > 120:
        wsem = asyncio.Semaphore(8)
        async with httpx.AsyncClient(timeout=60) as client:
            async def summarise(p: Profile) -> None:
                nonlocal llm_calls
                async with wsem:
                    if budget.remaining_s() < 60:
                        p.context["summary"] = template(p)
                        return
                    llm_calls += 1
                    p.context["summary"] = await writer.write(p, client)
            await asyncio.gather(*(summarise(profiles[o]) for o in orgs))
    completed = utc_now()
    envelopes = []
    for org in orgs:
        p = profiles[org]
        if "summary" not in p.context:
            p.context["summary"] = template(p)
        ops = {"requests": budget.by_company.get(org, 0), "runtime_ms": timing.get(org),
               "third_party_cost_usd": 0, "llm_calls": 1 if str(p.context["summary"].get("writer", "")).startswith("model") else 0}
        status = "completed" if p.legal_name else "failed"
        envelopes.append(envelope(p, completed, ops, status))
    lat = sorted(timing.values())
    report = {
        "agent": AGENT_NAME, "version": __version__, "commit": _commit(), "run_id": run_id,
        "started_at": started, "completed_at": completed, "runtime_s": round(time.monotonic() - t0, 1),
        "expected_count": len(orgs), "emitted_envelopes": len(envelopes),
        "requests": budget.used, "requests_by_host": dict(sorted(budget.by_host.items(), key=lambda x: -x[1])[:25]),
        "third_party_cost_usd": 0, "llm_calls": llm_calls,
        "p50_ms": lat[len(lat) // 2] if lat else None, "p95_ms": lat[min(len(lat) - 1, int(len(lat) * 0.95))] if lat else None,
        "budgets": {"max_requests": max_requests, "time_budget_s": time_budget, "per_company_requests": per_company},
        "nav_index_built_at": nav.built_at, "seed_companies": len(shared["seeds"]),
    }
    return envelopes, report


def coverage(envelopes: list[dict]) -> dict:
    fams = ["official_website", "social_profile", "hiring_signal", "dated_news", "job_ad", "public_record",
            "role", "workplace", "revenue", "registry_update", "group_relation", "lei"]
    out = {}
    for fam in fams:
        companies = sum(1 for e in envelopes if any(c["field"] == fam and c["availability"] == "available" for c in e["claims"]))
        facts = sum(1 for e in envelopes for c in e["claims"] if c["field"] == fam and c["availability"] == "available")
        out[fam] = {"companies": companies, "facts": facts}
    return out


def validate(envelopes: list[dict], orgs: list[str]) -> dict:
    got = [e["organisation_number"] for e in envelopes]
    unsupported = sum(1 for e in envelopes for c in e["claims"]
                      if c["availability"] == "available" and not c.get("evidence_ids"))
    bad_spans = 0
    for e in envelopes:
        ev = {x["id"]: x for x in e["evidence"]}
        for c in e["claims"]:
            if c["availability"] != "available":
                continue
            if not any(ev.get(i, {}).get("span_exact") for i in c.get("evidence_ids", [])):
                bad_spans += 1
    checks = {
        "one_envelope_per_input": got == orgs,
        "unique_organisation_numbers": len(set(got)) == len(got),
        "every_published_claim_has_evidence": unsupported == 0,
        "every_published_claim_has_exact_span": bad_spans == 0,
        "states_valid": all(c["availability"] in ("available", "not_available", "blocked", "not_applicable", "ambiguous", "failed")
                            for e in envelopes for c in e["claims"]),
    }
    return {"passed": all(checks.values()), "checks": checks, "claims_without_exact_span": bad_spans}


def load_previous(path: str | None, state_dir: str | None) -> dict[str, dict]:
    rows: list[dict] = []
    if path and Path(path).exists():
        rows = read_jsonl(Path(path))
    elif state_dir and (Path(state_dir) / "latest.jsonl").exists():
        rows = read_jsonl(Path(state_dir) / "latest.jsonl")
    return {r["organisation_number"]: r for r in rows if r.get("organisation_number")}


def save_state(state_dir: str, envelopes: list[dict], run_id: str) -> None:
    root = Path(state_dir)
    (root / "history").mkdir(parents=True, exist_ok=True)
    write_jsonl(root / "history" / f"{run_id}.jsonl", envelopes)
    merged = {r["organisation_number"]: r for r in read_jsonl(root / "latest.jsonl")}
    merged.update({e["organisation_number"]: e for e in envelopes if e["run"]["terminal_status"] == "completed"})
    write_jsonl(root / "latest.jsonl", list(merged.values()))
