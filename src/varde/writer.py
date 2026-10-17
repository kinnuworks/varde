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

NUMBER_WORDS = re.compile(r"\b(two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|"
                          r"fifteen|twenty|thirty|forty|fifty|hundred|thousand|million|billion|dozen)\b", re.I)

SYSTEM = (
    "You translate a Norwegian company's own registered description of its business into one or two plain "
    "English sentences for a company profile. Use only the texts provided. Translate faithfully: do not add "
    "activities, markets, customers, sizes, places, dates or numbers that are not in the texts, and do not "
    "praise the company, and do not correct apparent typos or add explanations in brackets. Start with the company name. If the texts say nothing useful about what the company "
    "does, return an empty string. Return JSON only: {\"text\": \"...\"}"
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


RELATION_LABEL = {
    "subsidiary": "A subsidiary owned by {name}",
    "parent": "The direct parent company that owns {name}",
    "ultimate parent": "The ultimate parent company at the top of {name}'s group",
    "group company": "Another company in the same group as {name} (no ownership link to it stated)",
}


def _claims_payload(p: Profile) -> list[dict]:
    keep = []
    groups = 0
    caps = {"registry_update": 4, "workplace": 6, "role": 10, "public_record": 5, "job_ad": 5, "dated_news": 4,
            "social_profile": 6, "role_in_other_entity": 3, "hiring_signal": 2}
    seen: dict[str, int] = {}
    for c in p.published():
        seen[c["field"]] = seen.get(c["field"], 0) + 1
        if seen[c["field"]] > caps.get(c["field"], 99):
            continue
        if c["field"] in ("organisation_number",) or c["field"].startswith("register_"):
            continue
        label = c.get("label") or c["field"]
        if c["field"] == "group_relation":
            rel = c["value"].get("relation")
            if rel == "group company" or groups >= 8:
                continue
            groups += 1
            label = RELATION_LABEL.get(rel, label).format(name=p.legal_name)
        if c["field"] == "role_in_other_entity":
            label = f"A role that {p.legal_name} itself holds in another entity"
        item: dict[str, Any] = {"id": c["id"], "label": label, "value": c["value"]}
        for k in ("as_of", "reporting_period"):
            if c.get(k):
                item[k] = c[k]
        keep.append(item)
    return keep[:90]


async def _call(client: httpx.AsyncClient, prompt: str) -> str | None:
    provider = os.environ["VARDE_LLM_PROVIDER"].lower()
    model = os.environ["VARDE_MODEL"]
    if provider == "anthropic":
        base = os.environ.get("VARDE_LLM_BASE_URL", "https://api.anthropic.com")
        r = await client.post(f"{base}/v1/messages", headers={
            "x-api-key": os.environ["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={"model": model, "max_tokens": 400, "thinking": {"type": "disabled"}, "system": SYSTEM,
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


DESCRIBE = ("registered_activity", "statutory_purpose", "website_description")


async def write(p: Profile, client: httpx.AsyncClient) -> dict:
    """Template summary, with the 'what it does' sentence translated by the model when possible."""
    base = template(p)
    sources = [c for f in DESCRIBE for c in p.published(f)]
    if not p.legal_name or not sources:
        return base
    payload = {"company": p.legal_name,
               "texts": {c["field"]: c["value"] for c in sources}}
    try:
        text = await _call(client, json.dumps(payload, ensure_ascii=False, default=str))
    except (httpx.HTTPError, KeyError, ValueError):
        return base
    m = re.search(r"\{.*\}", text or "", re.S)
    try:
        out = (json.loads(m.group(0)).get("text") or "").strip() if m else ""
    except ValueError:
        return base
    if not out or re.search(r"\d", out) or NUMBER_WORDS.search(out) or "—" in out or len(out) > 420:
        return base
    sent = {"text": out, "claim_ids": [c["id"] for c in sources]}
    if not validate(p, sent):
        return base
    describe_ids = {c["id"] for c in sources}
    kept = [x for x in base["sentences"] if not (set(x["claim_ids"]) & describe_ids)]
    sentences = kept[:1] + [sent] + kept[1:]
    return {"text": " ".join(x["text"] for x in sentences), "sentences": sentences,
            "unknowns": base["unknowns"], "writer": "template_v2+model_description"}
