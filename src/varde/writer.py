"""Optional model-written summary, held to the same rules as the template.

Enabled only when `VARDE_LLM_PROVIDER` (anthropic or openai), `VARDE_MODEL` and the
provider's key are set. The model sees only this company's published claims and
must return sentences that cite claim ids. Each sentence is validated (numbers
and dates must appear in its cited claims); if fewer than three sentences pass,
the deterministic template is used instead. The model never decides identity
and never sees raw pages.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any

import httpx

from .profile import Profile
from .synthesis import template, unknown_list, validate

SYSTEM = (
    "You write short, factual company briefs for people deciding whether to apply to, sell to, partner with or "
    "invest in a Norwegian company. Use only the claims provided. Every sentence must cite the ids of the claims "
    "it uses. Copy numbers, amounts and dates exactly as they appear in the claims; do not calculate, round, "
    "convert or estimate anything. Translate Norwegian descriptions into plain English. Do not guess at anything "
    "the claims do not state. Write 4 to 7 sentences covering, where the claims allow: what the company does, its "
    "size and latest filed figures, who leads it, where it operates, hiring and public activity, and what changed "
    "recently. Return JSON only: {\"sentences\": [{\"text\": \"...\", \"claim_ids\": [\"c1\"]}]}"
)


def enabled() -> bool:
    provider = os.environ.get("VARDE_LLM_PROVIDER", "").lower()
    if not os.environ.get("VARDE_MODEL"):
        return False
    if provider == "anthropic":
        return bool(os.environ.get("ANTHROPIC_API_KEY"))
    if provider == "openai":
        return bool(os.environ.get("OPENAI_API_KEY"))
    return False


def _claims_payload(p: Profile) -> list[dict]:
    keep = []
    for c in p.published():
        if c["field"] in ("organisation_number",) or c["field"].startswith("register_"):
            continue
        item: dict[str, Any] = {"id": c["id"], "label": c.get("label") or c["field"], "value": c["value"]}
        for k in ("as_of", "reporting_period"):
            if c.get(k):
                item[k] = c[k]
        keep.append(item)
    return keep[:140]


async def _call(client: httpx.AsyncClient, prompt: str) -> str | None:
    provider = os.environ["VARDE_LLM_PROVIDER"].lower()
    model = os.environ["VARDE_MODEL"]
    if provider == "anthropic":
        base = os.environ.get("VARDE_LLM_BASE_URL", "https://api.anthropic.com")
        r = await client.post(f"{base}/v1/messages", headers={
            "x-api-key": os.environ["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={"model": model, "max_tokens": 900, "temperature": 0, "system": SYSTEM,
                  "messages": [{"role": "user", "content": prompt}]})
        r.raise_for_status()
        body = r.json()
        return "".join(part.get("text", "") for part in body.get("content", []) if part.get("type") == "text")
    base = os.environ.get("VARDE_LLM_BASE_URL", "https://api.openai.com")
    r = await client.post(f"{base}/v1/chat/completions", headers={"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"},
                          json={"model": model, "temperature": 0, "max_tokens": 900,
                                "response_format": {"type": "json_object"},
                                "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}]})
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


async def write(p: Profile, client: httpx.AsyncClient) -> dict:
    base = template(p)
    if not p.legal_name:
        return base
    payload = {"company": p.legal_name, "organisation_number": p.organisation_number,
               "claims": _claims_payload(p),
               "changes_since_previous_run": [c["explanation"] for c in p.changes[:8]]}
    try:
        text = await _call(client, json.dumps(payload, ensure_ascii=False, default=str))
    except (httpx.HTTPError, KeyError, ValueError):
        return base
    if not text:
        return base
    m = re.search(r"\{.*\}", text, re.S)
    try:
        sentences = json.loads(m.group(0)).get("sentences", []) if m else []
    except ValueError:
        return base
    ids = {c["id"] for c in p.claims}
    valid = []
    for sent in sentences:
        if not isinstance(sent, dict) or not isinstance(sent.get("text"), str):
            continue
        sent = {"text": sent["text"].strip(), "claim_ids": [i for i in sent.get("claim_ids", []) if i in ids]}
        if sent["claim_ids"] and validate(p, sent) and "—" not in sent["text"]:
            valid.append(sent)
    if len(valid) < 3:
        return base
    return {"text": " ".join(s["text"] for s in valid), "sentences": valid, "unknowns": unknown_list(p),
            "writer": f"model:{os.environ.get('VARDE_MODEL')}"}
