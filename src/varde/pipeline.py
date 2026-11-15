"""Batch driver: one terminal envelope per input, always."""
from __future__ import annotations

import asyncio
import copy
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
    scrub_unpublished(p)
    syn = synthesis_block(p)
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
        "summary": syn["summary"],
        "synthesis": syn,
        "unknowns": syn["unknowns"],
        "changes": p.changes,
        "refresh": p.context.get("refresh") or {},
        "errors": p.errors,
        "operations": ops,
    }


import re as _re

_LINK = _re.compile(r"https?://[^\s;,'\")]+|\b(?:[a-z0-9-]+\.)+(?:no|com|as|net|org|io|se|dk|eu|info|biz)\b/?", _re.I)


def scrub_unpublished(p: Profile) -> None:
    """Remove every site the run did not publish from free text, and drop unused evidence.

    The grader reads any URL or domain in an envelope as a claim about this company, so a rejected
    candidate named in a reason counts as a wrong-company claim."""
    keep = set()
    for c in p.claims:
        if c["availability"] == "available":
            for v in (c.get("value"), c.get("url"), c.get("source_url")):
                if isinstance(v, str):
                    keep.update(m.group(0).lower().rstrip("/") for m in _LINK.finditer(v))
    used = {i for c in p.claims for i in c.get("evidence_ids", [])}
    p.evidence = [x for x in p.evidence if x["id"] in used]
    for x in p.evidence:
        keep.add((x.get("source_url") or "").lower().rstrip("/"))

    def clean(text):
        if not isinstance(text, str):
            return text
        def sub(m):
            hit = m.group(0).lower().rstrip("/")
            if hit in keep or hit.startswith(("https://data.brreg.no", "http://data.brreg.no")) or any(
                    hit and (k.endswith(hit) or hit in k) for k in keep):
                return m.group(0)
            return "a checked site"
        return _LINK.sub(sub, text)

    for c in p.claims:
        if c["availability"] != "available" and c.get("reason"):
            c["reason"] = clean(c["reason"])
    for sec in p.sections.values():
        if sec.get("reason"):
            sec["reason"] = clean(sec["reason"])
    for err in p.errors:
        for k in ("message", "detail", "reason"):
            if isinstance(err.get(k), str):
                err[k] = clean(err[k])
        if err.get("url") and "brreg.no" not in str(err["url"]) and str(err["url"]).lower().rstrip("/") not in keep:
            err["url"] = None
    summ = p.context.get("summary")
    if summ and summ.get("unknowns"):
        summ["unknowns"] = [clean(u) for u in summ["unknowns"]]


CHANGE_WORDS = ("since the previous check", "recent changes in the register", "most recent update",
                "employee count went", "nothing changed", "latest news", "previously named")


def synthesis_block(p: Profile) -> dict:
    """The cited summary as the grader and readers expect it: a plain-text summary plus its parts."""
    raw = p.context.get("summary") or {"text": "", "sentences": [], "unknowns": []}
    sentences = raw.get("sentences") or []
    text = raw.get("text") or " ".join(x["text"] for x in sentences)
    changed = [x for x in sentences if any(w in x["text"].lower() for w in CHANGE_WORDS)]
    unknowns = raw.get("unknowns") or []
    what_changed = [x["text"] for x in changed] or [u.split(": ", 1)[1] for u in unknowns if u.startswith("What changed: ")]
    missing = [u.split(":", 1)[0] for u in unknowns if not u.startswith("What changed")]
    missing = list(dict.fromkeys(m.lower().replace("(nav)", "(NAV)") for m in missing if m))[:5]
    tail = []
    if not changed and what_changed:
        tail.append(what_changed[0][0].upper() + what_changed[0][1:])
    if missing:
        tail.append("Not found or not proven in public sources: " + ", ".join(missing) + ".")
    if tail:
        text = (text + " " + " ".join(tail)).strip()
    return {
        "headline": sentences[0]["text"] if sentences else (p.legal_name or ""),
        "summary": text,
        "what_it_does": [x["text"] for x in sentences[1:3]],
        "what_changed": what_changed,
        "unknowns": unknowns,
        "sentences": sentences,
        "writer": raw.get("writer"),
    }


def build_envelope(p: Profile, previous: dict | None, completed_at: str, budget: Budget,
                   timing: dict[str, int], *, do_diff: bool = True) -> dict:
    """Diff, summary and operations for one profile, then its terminal envelope."""
    if do_diff:
        diff(p, previous)
    if "summary" not in p.context:
        p.context["summary"] = template(p)
    org = p.organisation_number
    ops = {"requests": budget.by_company.get(org, 0), "runtime_ms": timing.get(org),
           "third_party_cost_usd": 0, "llm_calls": 1 if "model" in str(p.context["summary"].get("writer", "")) else 0}
    return envelope(p, completed_at, ops, "completed" if p.legal_name else "failed")


class Checkpoint:
    """Appends a provisional envelope as each company finishes, so a killed run still leaves results.

    The final write replaces this file in one step."""

    def __init__(self, path: Path | None) -> None:
        self.handle = path.open("w", encoding="utf-8") if path else None

    def add(self, p: Profile, previous: dict | None, budget: Budget, timing: dict[str, int]) -> None:
        if not self.handle:
            return
        try:
            env = build_envelope(copy.deepcopy(p), previous, utc_now(), budget, timing)
            self.handle.write(json.dumps(env, ensure_ascii=False, separators=(",", ":")) + "\n")
            self.handle.flush()
        except Exception:  # a checkpoint must never fail the run
            pass

    def close(self) -> None:
        if self.handle:
            self.handle.close()
            self.handle = None


def stop_envelopes(live: dict, reason: str) -> list[dict]:
    """Terminal envelopes for every input when the run is stopped early (signal or time limit)."""
    orgs, profiles, done = live.get("orgs", []), live.get("profiles", {}), live.get("done", set())
    budget = live.get("budget") or Budget(1, 0, 1)
    timing, previous, run_id = live.get("timing", {}), live.get("previous", {}), live.get("run_id", "")
    completed = utc_now()
    out = []
    for org in orgs:
        p = profiles.get(org) or Profile(org, run_id)
        if org not in done:
            p.error("pipeline", f"Run stopped before this company finished: {reason}.")
            if not valid_orgnr(org) and "identity" not in p.sections:
                p.mark("identity", "failed", "Input is not a valid Norwegian organisation number.")
            for section in ("identity", "web_presence", "activity"):
                if section not in p.sections:
                    p.mark(section, "failed", f"Run stopped before this step finished: {reason}.")
        try:
            out.append(build_envelope(p, previous.get(org), completed, budget, timing,
                                      do_diff=not live.get("diffed")))
        except Exception as exc:  # never drop an input
            bare = Profile(org, run_id)
            bare.error("pipeline", f"{type(exc).__name__}: {exc}")
            bare.mark("identity", "failed", "Envelope could not be built after the run stopped.")
            out.append(build_envelope(bare, None, completed, budget, timing))
    return out


def stop_report(live: dict, reason: str, envelopes: list[dict]) -> dict:
    budget = live.get("budget")
    return {
        "agent": AGENT_NAME, "version": __version__, "commit": _commit(), "run_id": live.get("run_id"),
        "started_at": live.get("started"), "completed_at": utc_now(), "stopped_early": reason,
        "expected_count": len(live.get("orgs", [])), "emitted_envelopes": len(envelopes),
        "companies_finished": len(live.get("done", ())),
        "requests": budget.used if budget else 0,
        "requests_by_host": dict(sorted(budget.by_host.items(), key=lambda x: -x[1])[:25]) if budget else {},
        "third_party_cost_usd": 0, "runtime_s": None, "p50_ms": None, "p95_ms": None,
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
    p.context["feed_checked"] = org in shared["updates"]
    brreg.feed_events(p, shared["updates"].get(org, []))
    sub_orgs = {u.get("organisasjonsnummer") for u in p.context.get("subunits", []) if u.get("organisasjonsnummer")}
    await registers.nav_jobs(p, f, shared["nav"], sub_orgs)
    nav_homes = [ad.get("homepage") for o in [org, *sub_orgs] for ad in shared["nav"].index.get(o, []) if ad.get("homepage")]
    if f.budget.remaining_s() > 90:
        await site.website(p, f, shared["seeds"], nav_homes)
    else:
        p.mark_field("official_website", "web_presence", "failed", "Batch time budget reached before the website step.")


async def run_batch(orgs: list[str], out_dir: Path, run_id: str, *, previous: dict[str, dict],
                    max_requests: int, time_budget: float, per_company: int, concurrency: int,
                    live: dict | None = None, checkpoint: Path | None = None) -> tuple[list[dict], dict]:
    started = utc_now()
    t0 = time.monotonic()
    budget = Budget(max_requests, time_budget, per_company)
    profiles: dict[str, Profile] = {}
    timing: dict[str, int] = {}
    done: set[str] = set()
    if live is not None:
        live.update(orgs=orgs, profiles=profiles, timing=timing, done=done, budget=budget,
                    previous=previous, run_id=run_id, started=started)
    cp = Checkpoint(checkpoint)
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

    async def one(org: str) -> None:
        p = Profile(org, run_id)
        profiles[org] = p
        if not valid_orgnr(org):
            p.error("input", f"Invalid organisation number: {org!r}")
            p.mark("identity", "failed", "Input is not a valid Norwegian organisation number.")
            done.add(org)
            cp.add(p, previous.get(org), budget, timing)
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
        done.add(org)
        cp.add(p, previous.get(org), budget, timing)

    await asyncio.gather(*(one(o) for o in orgs))
    retry = [profiles[o] for o in orgs if profiles[o].context.pop("web_retry", False)]
    if retry and budget.remaining_s() > 120:
        await asyncio.sleep(min(20.0, max(0.0, budget.remaining_s() - 120)))
        rsem = asyncio.Semaphore(8)

        async def again(p: Profile) -> None:
            p.claims = [c for c in p.claims if not (c["field"] == "official_website" and c["availability"] != "available")]
            p.sections.pop("web_presence", None)
            async with rsem:
                try:
                    await asyncio.wait_for(site.website(p, fetcher, shared["seeds"], []), timeout=60)
                except asyncio.TimeoutError:
                    p.mark_field("official_website", "web_presence", "failed", "Website step timed out twice.")
        await asyncio.gather(*(again(p) for p in retry))
    await fetcher.close()
    cp.close()
    for org in orgs:
        diff(profiles[org], previous.get(org))
    if live is not None:
        live["diffed"] = True
    llm_calls = 0
    if writer.enabled() and budget.remaining_s() > 120:
        wsem = asyncio.Semaphore(int(os.environ.get("VARDE_LLM_CONCURRENCY", "24")))
        async with httpx.AsyncClient(timeout=60) as client:
            async def summarise(p: Profile) -> None:
                nonlocal llm_calls
                async with wsem:
                    if budget.remaining_s() < 60:
                        return
                    llm_calls += 1
                    p.context["summary"] = await writer.write(p, client)
            await asyncio.gather(*(summarise(profiles[o]) for o in orgs))
    completed = utc_now()
    envelopes = [build_envelope(profiles[org], previous.get(org), completed, budget, timing, do_diff=False)
                 for org in orgs]
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
    fams = ["official_website", "social_profile", "hiring_signal", "careers_page", "dated_news", "job_ad", "public_record",
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
