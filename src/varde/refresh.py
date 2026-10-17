"""Refresh as a diff against the previous envelope.

- Stable claim keys (field + value) make reruns idempotent: unchanged sources
  produce no changes.
- Single-valued fields report `changed_*`; multi-valued fields report additions
  and removals (`new_role`, `ended_role`, `new_job`, `closed_job`, ...).
- When a source fails on a rerun, the last supported value is carried forward
  with its original evidence and a note, never erased.
- Every change keeps the previous value and its evidence next to the current one.
"""
from __future__ import annotations

import copy
from typing import Any

from .profile import Profile
from .util import utc_now

SINGLE = {
    "legal_name": "changed_name", "legal_form": "changed_legal_form", "registered_address": "changed_address",
    "postal_address": "changed_postal_address", "registered_employees": "changed_employee_count",
    "registry_website": "changed_registry_website", "registry_phone": "changed_phone", "registry_email": "changed_email",
    "official_website": "changed_website", "share_capital": "changed_share_capital",
    "latest_filed_accounts_year": "new_filing", "statutory_purpose": "changed_purpose",
    "registered_activity": "changed_activity", "status_konkurs": "changed_bankruptcy_status",
    "status_underAvvikling": "changed_winding_up_status", "website_description": "changed_description",
    "lei": "changed_lei",
}
MULTI = {
    "role": ("new_role", "ended_role"), "workplace": ("new_location", "closed_location"),
    "job_ad": ("new_job", "closed_job"), "hiring_signal": ("new_hiring_signal", "removed_hiring_signal"),
    "social_profile": ("new_social_profile", "removed_social_profile"), "dated_news": ("new_news", None),
    "public_record": ("new_public_record", None), "group_relation": ("new_group_relation", "ended_group_relation"),
    "industry": ("new_industry_code", "removed_industry_code"), "registry_update": ("new_registry_update", None),
}
MATERIAL = {"changed_name", "changed_legal_form", "changed_address", "changed_website", "new_filing",
            "changed_bankruptcy_status", "changed_winding_up_status", "new_role", "ended_role",
            "changed_share_capital", "new_group_relation", "ended_group_relation", "new_public_record"}
FINANCIAL = {"revenue", "operating_result", "annual_result", "total_assets", "equity", "total_debt",
             "salary_costs", "profit_before_tax", "cash", "sales_revenue"}


def _describe(value: Any) -> str:
    if isinstance(value, dict):
        for key in ("name", "title", "type", "amount"):
            if value.get(key):
                extra = value.get("role") or value.get("date") or value.get("period") or ""
                return f"{value[key]}{' (' + str(extra) + ')' if extra else ''}"
        return ", ".join(f"{k}: {v}" for k, v in value.items() if v not in (None, "", [])) [:160]
    return str(value)


def _evidence_for(env_or_profile: Any, claim: dict) -> list[dict]:
    evidence = env_or_profile["evidence"] if isinstance(env_or_profile, dict) else env_or_profile.evidence
    ids = set(claim.get("evidence_ids") or [])
    return [e for e in evidence if e["id"] in ids]


def diff(p: Profile, previous: dict | None) -> None:
    now = utc_now()
    if not previous:
        p.mark("refresh", "not_applicable", "First run for this company: nothing to compare yet.")
        p.context["refresh"] = {"previous_run_id": None, "compared_at": now}
        return
    prev_claims = [c for c in previous.get("claims", []) if c.get("availability") == "available"]
    cur_claims = p.published()
    failed_fields = {c["field"] for c in p.claims if c["availability"] in ("failed", "blocked")}
    failed_sections = {s for s, v in p.sections.items() if v.get("state") in ("failed", "blocked")}
    changes: list[dict] = []

    def change(ctype: str, field: str, prev: dict | None, cur: dict | None, explanation: str) -> None:
        changes.append({
            "type": ctype, "field": field, "material": ctype in MATERIAL, "detected_at": now,
            "previous": {"value": prev["value"], "claim_key": prev["claim_key"], "as_of": prev.get("as_of"),
                         "evidence": _evidence_for(previous, prev)} if prev else None,
            "current": {"value": cur["value"], "claim_id": cur["id"], "as_of": cur.get("as_of")} if cur else None,
            "explanation": explanation,
        })

    by_field_prev: dict[str, list[dict]] = {}
    for c in prev_claims:
        by_field_prev.setdefault(c["field"], []).append(c)
    by_field_cur: dict[str, list[dict]] = {}
    for c in cur_claims:
        by_field_cur.setdefault(c["field"], []).append(c)

    carried = 0
    for field in sorted(set(by_field_prev) | set(by_field_cur)):
        prev_list = by_field_prev.get(field, [])
        cur_list = by_field_cur.get(field, [])
        prev_keys = {c["claim_key"]: c for c in prev_list}
        cur_keys = {c["claim_key"]: c for c in cur_list}
        source_failed = field in failed_fields or (prev_list and prev_list[0]["section"] in failed_sections and not cur_list)
        if source_failed and prev_list and not cur_list:
            for c in prev_list:
                kept = copy.deepcopy(c)
                kept["id"] = f"c{len(p.claims) + 1}"
                old_ev = _evidence_for(previous, c)
                new_ids = []
                for e in old_ev:
                    e2 = copy.deepcopy(e)
                    e2["id"] = f"e{len(p.evidence) + 1}"
                    e2["note"] = (e2.get("note") or "") + " Carried forward from the previous run because the source failed on this run."
                    p.evidence.append(e2)
                    new_ids.append(e2["id"])
                kept["evidence_ids"] = new_ids
                kept["carried_forward"] = True
                kept["carried_from_run"] = (previous.get("run") or {}).get("run_id")
                p.claims = [x for x in p.claims if not (x["field"] == field and x["availability"] != "available")]
                p.claims.append(kept)
                carried += 1
            continue
        if field in SINGLE:
            if prev_list and cur_list and set(prev_keys) != set(cur_keys):
                pv, cv = prev_list[0], cur_list[0]
                change(SINGLE[field], field, pv, cv,
                       f"{pv.get('label') or field} changed from {_describe(pv['value'])} to {_describe(cv['value'])}.")
            elif cur_list and not prev_list:
                change(SINGLE[field], field, None, cur_list[0],
                       f"{cur_list[0].get('label') or field} is now {_describe(cur_list[0]['value'])} (not found on the previous run).")
            continue
        if field in FINANCIAL:
            prev_periods = {c.get("reporting_period") for c in prev_list}
            for c in cur_list:
                if c.get("reporting_period") not in prev_periods and field == "revenue":
                    change("new_filing", field, None, c,
                           f"New annual accounts for {c.get('reporting_period')} are available.")
            continue
        if field in MULTI:
            added, removed = MULTI[field]
            for key, c in cur_keys.items():
                if key not in prev_keys:
                    change(added, field, None, c, f"New: {_describe(c['value'])}.")
            if removed:
                for key, c in prev_keys.items():
                    if key not in cur_keys:
                        change(removed, field, c, None, f"No longer listed: {_describe(c['value'])}.")
    p.changes = changes
    p.context["refresh"] = {"previous_run_id": (previous.get("run") or {}).get("run_id"),
                            "previous_completed_at": (previous.get("run") or {}).get("completed_at"),
                            "compared_at": now, "changes": len(changes),
                            "material_changes": sum(1 for c in changes if c["material"]), "carried_forward": carried}
    p.mark("refresh", "available" if changes or carried else "not_available",
           None if changes else "No changes since the previous run.")
