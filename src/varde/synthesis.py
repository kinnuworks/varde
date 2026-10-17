"""Cited company summary.

Each sentence lists the claim ids it rests on. `validate` rejects a sentence
whose numbers or dates do not appear in its cited claims, so the summary can
only restate supported facts. The template below needs no model key; a model
writer, when configured, must pass the same validator or the template is used.
"""
from __future__ import annotations

import json
import re
from typing import Any

from .profile import Profile

FORMS_EN = {
    "AS": "private limited company", "ASA": "public limited company", "ENK": "sole proprietorship",
    "ANS": "general partnership", "DA": "partnership with shared liability", "SA": "cooperative",
    "STI": "foundation", "BRL": "housing cooperative", "ESEK": "owners' association (sameie)",
    "NUF": "Norwegian branch of a foreign company", "FLI": "association", "KS": "limited partnership",
    "IKS": "inter-municipal company", "SPA": "savings bank", "BA": "company with limited liability",
    "PK": "pension fund", "SAM": "co-ownership", "KF": "municipal enterprise", "SF": "state enterprise",
    "ANNA": "other legal entity", "GFS": "mutual insurance company", "PRE": "shipping partnership",
    "VPFO": "securities fund", "BBL": "housing association", "IKJP": "other legal person", "KIRK": "church body",
}

ROLE_ORDER = ["DAGL", "LEDE", "NEST", "MEDL", "STYR", "INNH", "DTPR", "DTSO", "KOMP", "REVI", "REGN"]


def _fmt_amount(raw: str) -> str:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return str(raw)
    sign = "-" if value < 0 else ""
    whole = f"{abs(round(value)):,}".replace(",", " ")
    return f"{sign}{whole}"


def _num_tokens(text: str) -> set[str]:
    return {re.sub(r"[\s  ]", "", m) for m in re.findall(r"\d[\d\s  ]*\d|\d", text)}


def validate(p: Profile, sentence: dict) -> bool:
    cited = [c for c in p.claims if c["id"] in sentence["claim_ids"]]
    if not cited or any(c["availability"] != "available" for c in cited):
        return False
    blob = json.dumps([c["value"] for c in cited] + [c.get("as_of") for c in cited] +
                      [c.get("reporting_period") for c in cited], ensure_ascii=False, default=str)
    blob_digits = re.sub(r"[^\d]", " ", blob)
    available = set(blob_digits.split())
    for token in _num_tokens(sentence["text"]):
        token = token.lstrip("0") or "0"
        if not any(a.lstrip("0") == token or token in a for a in available):
            return False
    return True


def _first(p: Profile, field: str) -> dict | None:
    items = p.published(field)
    return items[0] if items else None


def template(p: Profile) -> dict:
    s: list[dict] = []

    def add(text: str, claims: list[dict | None]) -> None:
        ids = [c["id"] for c in claims if c]
        if ids:
            s.append({"text": text, "claim_ids": ids})

    name = _first(p, "legal_name")
    form = _first(p, "legal_form")
    addr = _first(p, "registered_address")
    founded = _first(p, "founded")
    if name:
        town = (p.context.get("entity") or {}).get("forretningsadresse", {}).get("poststed") or ""
        kind = FORMS_EN.get(form["value"]["code"], form["value"]["description"].lower()) if form else "registered entity"
        text = f"{name['value']} is " + ("an " if kind[0] in "aeiou" else "a ") + kind
        if town:
            text += f" registered in {town.title()}"
        if founded:
            text += f", founded {founded['value']}"
        add(text + ".", [name, form, addr if town else None, founded])

    status = [c for c in p.published() if c["field"].startswith("status_") and c["value"] is True]
    for c in status:
        add(f"The register marks it as {c.get('label', '').lower()}.", [c])

    activity = _first(p, "registered_activity") or _first(p, "statutory_purpose")
    desc = _first(p, "website_description")
    industry = next((c for c in p.published("industry") if c["value"].get("rank") == 1), None)
    if desc:
        add(f"Its website describes the business as follows: \"{desc['value'][:220].rstrip()}\"", [desc])
    elif activity:
        add(f"Its registered activity: \"{activity['value'][:220].rstrip()}\"", [activity])
    if industry:
        add(f"Its main industry code is {industry['value']['code']} ({industry['value']['description'].lower()}).", [industry])

    emp = _first(p, "registered_employees")
    workplaces = p.published("workplace")
    if emp and workplaces:
        add(f"The register shows {emp['value']} employees and {len(workplaces)} registered workplace"
            f"{'s' if len(workplaces) != 1 else ''}.", [emp] + workplaces[:8])
    elif emp:
        add(f"The register shows {emp['value']} employees.", [emp])
    elif workplaces:
        add(f"It has {len(workplaces)} registered workplace{'s' if len(workplaces) != 1 else ''}.", workplaces[:8])

    revs = sorted([c for c in p.published("revenue") if c["value"].get("account_type") == "SELSKAP"],
                  key=lambda c: c.get("reporting_period") or "")
    res = {c.get("reporting_period"): c for c in p.published("annual_result") if c["value"].get("account_type") == "SELSKAP"}
    if revs:
        latest = revs[-1]
        period = latest["reporting_period"]
        year = period.split("/")[-1][:4]
        cur = latest["value"]["currency"]
        text = f"In its {year} accounts, total operating income was {_fmt_amount(latest['value']['amount'])} {cur}"
        cites = [latest]
        if period in res:
            text += f" and the annual result was {_fmt_amount(res[period]['value']['amount'])} {cur}"
            cites.append(res[period])
        if len(revs) > 1:
            prev = revs[-2]
            pyear = prev["reporting_period"].split("/")[-1][:4]
            text += f", against {_fmt_amount(prev['value']['amount'])} {cur} in operating income for {pyear}"
            cites.append(prev)
        add(text + ".", cites)
    else:
        fin_state = next((c for c in p.claims if c["field"] == "annual_accounts"), None)
        if fin_state and fin_state.get("reason"):
            pass

    roles = p.published("role")
    order = {code: i for i, code in enumerate(ROLE_ORDER)}
    lead = sorted(roles, key=lambda c: order.get(c["value"].get("role_code"), 99))
    names = [c for c in lead if c["value"].get("role_code") in ("DAGL", "LEDE", "INNH")][:2]
    if names:
        parts = [f"{c['value']['name']} ({c['value']['role'].lower()})" for c in names]
        board = [c for c in roles if c["value"].get("role_code") in ("MEDL", "NEST")]
        text = "Registered leadership: " + " and ".join(parts)
        if board:
            text += f", with {len(board)} other board member{'s' if len(board) != 1 else ''}"
        add(text + ".", names + board[:6])

    site = _first(p, "official_website")
    socials = p.published("social_profile")
    if site:
        text = f"Its verified website is {site['value']}"
        if socials:
            text += ", which links to " + ", ".join(sorted({c['value'].split('/')[0].split('.')[0].capitalize() for c in socials}))
        add(text + ".", [site] + socials[:6])

    jobs = p.published("job_ad")
    hiring = p.published("hiring_signal")
    if jobs:
        add(f"It has {len(jobs)} open position{'s' if len(jobs) != 1 else ''} listed, most recently "
            f"\"{jobs[0]['value'].get('title')}\".", jobs[:5])
    elif hiring:
        add("Its website links to a careers page or job board.", hiring[:2])
    news = sorted(p.published("dated_news"), key=lambda c: c.get("as_of") or "", reverse=True)
    if news:
        add(f"The latest news on its own website is \"{news[0].get('title') or news[0]['value']}\" from {news[0].get('as_of')}.", [news[0]])
    records = p.published("public_record")
    if records:
        kinds = sorted({c["value"].get("type") for c in records if c["value"].get("type")})
        add(f"Public records found: {', '.join(k.lower() for k in kinds[:3])}.", records[:6])

    changes = [c for c in p.changes if c.get("material")]
    if changes:
        add("Since the previous check: " + "; ".join(c["explanation"].rstrip(".") for c in changes[:3]) + ".",
            [x for x in (next((cl for cl in p.claims if cl["id"] == (c.get("current") or {}).get("claim_id")), None)
                         for c in changes[:3]) if x] or [name])
    updates = p.published("registry_update")
    if updates and not changes:
        latest = sorted(updates, key=lambda c: c["value"].get("date") or "")[-1]
        fields = ", ".join(latest["value"].get("changed_fields") or [])
        add(f"The register's most recent update was on {latest['as_of']}" + (f" ({fields})." if fields else "."), [latest])

    valid = [x for x in s if validate(p, x)]
    unknowns = unknown_list(p)
    return {"text": " ".join(x["text"] for x in valid), "sentences": valid, "unknowns": unknowns, "writer": "template_v1"}


UNKNOWN_LABELS = {
    "official_website": "Official website", "social_profile": "Social profiles", "job_ad": "Open positions (NAV)",
    "annual_accounts": "Structured annual accounts", "roles": "Registered roles", "workplace": "Registered workplaces",
    "registered_employees": "Employee count", "dated_news": "Dated news",
}


def unknown_list(p: Profile) -> list[str]:
    out = []
    for c in p.claims:
        if c["availability"] in ("not_available", "ambiguous", "failed", "blocked") and c.get("reason"):
            label = UNKNOWN_LABELS.get(c["field"], c["field"].replace("_", " ").capitalize())
            out.append(f"{label}: {c['reason']}")
    if not p.published("official_website") and not any(c["field"] == "official_website" for c in p.claims):
        out.append("Official website: not checked.")
    if p.published("official_website") and not p.published("dated_news"):
        out.append("Dated news: none found on the verified website.")
    return out[:12]
