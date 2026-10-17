"""Company profile: claims, evidence and section states for one organisation number.

A claim is published (`available`) only with at least one evidence record whose
quoted span appears verbatim in the saved snapshot. Absence is recorded as an
explicit state, never as zero.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from .net import FetchError, Snapshot
from .util import stable_id, utc_now

STATES = ("available", "not_available", "blocked", "not_applicable", "ambiguous", "failed")

SECTIONS = {
    "identity": "Legal identity and public brand",
    "financials": "Latest annual accounts and history",
    "leadership": "Leadership and registered workplaces",
    "web_presence": "Verified official website and company-owned profiles",
    "activity": "Hiring and dated public activity",
    "evidence": "Claim-level evidence and availability state",
    "refresh": "Refresh metadata and material changes",
}

# Precedence when several sources report a section state: the most informative wins.
_STATE_RANK = {"available": 5, "ambiguous": 4, "not_available": 3, "not_applicable": 3, "blocked": 2, "failed": 1}


_DECODER = json.JSONDecoder()


def json_span(text: str, key: str, value: Any = None, *, start: int = 0, end: int | None = None) -> str | None:
    """Exact `"key":value` text as it appears in a JSON response.

    Searches `text[start:end]`; when `value` is given, only an occurrence whose
    decoded value equals it is returned. The result is always a literal slice of
    `text`, so it can be found again with a plain text search.
    """
    stop = len(text) if end is None else end
    needle = f'"{key}"'
    pos = text.find(needle, start, stop)
    while pos >= 0:
        colon = pos + len(needle)
        while colon < stop and text[colon] in " \t\r\n":
            colon += 1
        if colon < stop and text[colon] == ":":
            vstart = colon + 1
            while vstart < stop and text[vstart] in " \t\r\n":
                vstart += 1
            try:
                decoded, vend = _DECODER.raw_decode(text, vstart)
            except ValueError:
                decoded, vend = None, -1
            if vend > 0 and (value is None or decoded == value or str(decoded) == str(value)):
                return text[pos:vend]
        pos = text.find(needle, pos + 1, stop)
    return None


def json_object_bounds(text: str, anchor: str) -> tuple[int, int] | None:
    """Bounds of the smallest JSON object in `text` that contains `anchor`."""
    idx = text.find(anchor)
    if idx < 0:
        return None
    depth = 0
    i = idx
    while i >= 0:
        ch = text[i]
        if ch == "}":
            depth += 1
        elif ch == "{":
            if depth == 0:
                try:
                    _, vend = _DECODER.raw_decode(text, i)
                    return i, vend
                except ValueError:
                    return None
            depth -= 1
        i -= 1
    return None


def text_span(text: str, needle: str, *, context: int = 60) -> str | None:
    """Exact substring of the page around `needle` (case-insensitive search)."""
    if not needle:
        return None
    idx = text.casefold().find(needle.casefold())
    if idx < 0:
        return None
    start = max(0, idx - context)
    end = min(len(text), idx + len(needle) + context)
    span = text[start:end]
    # Trim to whole words where possible without losing the needle.
    left = span.find(" ")
    if 0 <= left < idx - start:
        span = span[left + 1:]
    right = span.rfind(" ")
    if right > span.casefold().find(needle.casefold()) + len(needle):
        span = span[:right]
    return span.strip()


@dataclass
class Profile:
    organisation_number: str
    run_id: str
    legal_name: str | None = None
    claims: list[dict] = field(default_factory=list)
    evidence: list[dict] = field(default_factory=list)
    sections: dict[str, dict] = field(default_factory=dict)
    errors: list[dict] = field(default_factory=list)
    changes: list[dict] = field(default_factory=list)
    context: dict[str, Any] = field(default_factory=dict)  # working data shared between sources
    started_at: str = field(default_factory=utc_now)
    _evidence_index: dict[str, str] = field(default_factory=dict)

    # ---------- evidence ----------
    def add_evidence(self, snap: Snapshot, *, source_class: str, span: str | None, method: str,
                     licence: str, note: str | None = None, span_context: str | None = None) -> str | None:
        """Record evidence; returns its id, or None when the span is not in the snapshot."""
        exact = bool(span) and span in snap.text
        if span and not exact:
            return None
        key = f"{snap.sha256}|{span}|{method}"
        if key in self._evidence_index:
            return self._evidence_index[key]
        ev_id = f"e{len(self.evidence) + 1}"
        record = {
            "id": ev_id,
            "source_url": snap.final_url,
            "requested_url": snap.url,
            "source_class": source_class,
            "retrieved_at": snap.retrieved_at,
            "http_status": snap.status,
            "content_sha256": snap.sha256,
            "snapshot_path": snap.path,
            "claim_span": span,
            "span_exact": exact,
            "extraction_method": method,
            "licence": licence,
        }
        if snap.redirects:
            record["redirect_chain"] = snap.redirects
        if note:
            record["note"] = note
        if span_context and span_context in snap.text:
            record["span_context"] = span_context
        self.evidence.append(record)
        self._evidence_index[key] = ev_id
        return ev_id

    def add_absence_evidence(self, url: str, *, source_class: str, method: str, note: str,
                             retrieved_at: str | None = None, snap: Snapshot | None = None) -> str:
        ev_id = f"e{len(self.evidence) + 1}"
        record = {
            "id": ev_id,
            "source_url": snap.final_url if snap else url,
            "source_class": source_class,
            "retrieved_at": snap.retrieved_at if snap else (retrieved_at or utc_now()),
            "content_sha256": snap.sha256 if snap else None,
            "snapshot_path": snap.path if snap else None,
            "claim_span": None,
            "span_exact": False,
            "extraction_method": method,
            "note": note,
        }
        self.evidence.append(record)
        return ev_id

    # ---------- claims ----------
    def add_claim(self, field_name: str, section: str, value: Any, evidence_ids: list[str | None], *,
                  as_of: str | None = None, period: str | None = None, match: dict | None = None,
                  confidence: float = 0.99, label: str | None = None, extra: dict | None = None,
                  availability: str = "available") -> dict | None:
        ids = [e for e in evidence_ids if e]
        if availability == "available" and not ids:
            return None
        claim_key = stable_id(field_name, json.dumps(value, ensure_ascii=False, sort_keys=True, default=str))
        for existing in self.claims:
            if existing["claim_key"] == claim_key:
                for e in ids:
                    if e not in existing["evidence_ids"]:
                        existing["evidence_ids"].append(e)
                return existing
        claim = {
            "id": f"c{len(self.claims) + 1}",
            "claim_key": claim_key,
            "field": field_name,
            "section": section,
            "value": value,
            "availability": availability,
            "confidence": confidence,
            "evidence_ids": ids,
        }
        if label:
            claim["label"] = label
        if as_of:
            claim["as_of"] = as_of
        if period:
            claim["reporting_period"] = period
        if match:
            claim["match"] = match
        if extra:
            claim.update(extra)
        self.claims.append(claim)
        self.mark(section, availability if availability in STATES else "available")
        return claim

    def mark_field(self, field_name: str, section: str, state: str, reason: str,
                   evidence_ids: list[str | None] | None = None) -> None:
        """Record that a field family was checked and what was found (no value)."""
        claim_key = stable_id(field_name, "__state__")
        if any(c["claim_key"] == claim_key for c in self.claims):
            return
        if any(c["field"] == field_name and c["availability"] == "available" for c in self.claims):
            return
        self.claims.append({
            "id": f"c{len(self.claims) + 1}",
            "claim_key": claim_key,
            "field": field_name,
            "section": section,
            "value": None,
            "availability": state,
            "reason": reason,
            "evidence_ids": [e for e in (evidence_ids or []) if e],
        })
        self.mark(section, state, reason)

    def mark(self, section: str, state: str, reason: str | None = None) -> None:
        current = self.sections.get(section)
        if current is None or _STATE_RANK.get(state, 0) > _STATE_RANK.get(current["state"], 0):
            self.sections[section] = {"state": state, **({"reason": reason} if reason else {})}

    def error(self, source: str, err: FetchError | str, *, field_name: str | None = None) -> None:
        if isinstance(err, FetchError):
            self.errors.append({"source": source, "url": err.url, "reason": err.reason,
                                "at": err.retrieved_at, **({"field": field_name} if field_name else {})})
        else:
            self.errors.append({"source": source, "reason": err, "at": utc_now()})

    def published(self, field_name: str | None = None, section: str | None = None) -> list[dict]:
        return [c for c in self.claims if c["availability"] == "available"
                and (field_name is None or c["field"] == field_name)
                and (section is None or c["section"] == section)]

    def drop_claims(self, predicate) -> int:
        before = len(self.claims)
        self.claims = [c for c in self.claims if not predicate(c)]
        return before - len(self.claims)
