from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_WEIGHTS = (3, 2, 7, 6, 5, 4, 3, 2)

LEGAL_SUFFIXES = (
    "asa", "as", "ans", "da", "ba", "sa", "ks", "nuf", "enk", "iks", "kf", "bbl", "brl", "stiftelsen",
    "sf", "hf", "sti", "fli", "esek", "ab", "gmbh", "ltd", "limited", "inc", "aps", "oy",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def stable_id(*parts: Any, length: int = 12) -> str:
    raw = "\x1f".join(str(p) for p in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:length]


def valid_orgnr(value: str) -> bool:
    """Norwegian organisation numbers carry a MOD11 check digit."""
    if not re.fullmatch(r"[89]\d{8}", value or ""):
        return False
    total = sum(int(d) * w for d, w in zip(value[:8], _WEIGHTS))
    check = 11 - total % 11
    if check == 11:
        check = 0
    return check != 10 and check == int(value[8])


def digits(value: Any) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def fold(text: str) -> str:
    """Lower-case, strip accents except Norwegian letters, collapse whitespace."""
    text = unicodedata.normalize("NFKC", text or "").casefold()
    text = text.replace("&", " og ")
    text = re.sub(r"[^\wæøå]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def core_name(legal_name: str) -> str:
    """Legal name without legal-form words: 'DIPS AS' -> 'dips'."""
    words = [w for w in fold(legal_name).split() if w not in LEGAL_SUFFIXES]
    return " ".join(words)


def ascii_slug(text: str) -> str:
    table = str.maketrans({"æ": "ae", "ø": "o", "å": "a", "é": "e", "ü": "u", "ö": "o", "ä": "a"})
    return re.sub(r"[^a-z0-9]", "", fold(text).translate(table))


def read_inputs(path: str | Path) -> list[str]:
    """Accept JSONL rows, a JSON list or object, or plain text with one number per line.

    Invalid or duplicate entries never stop the batch; duplicates are kept once.
    Malformed values are returned as-is so the caller can emit a failed envelope.
    """
    source = Path(path)
    text = source.read_text(encoding="utf-8").strip()
    values: list[Any] = []
    if text.startswith("["):
        values = json.loads(text)
    elif text.startswith("{") and "\n" not in text:
        body = json.loads(text)
        values = body.get("organisation_numbers") or body.get("organisations") or [body]
    else:
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            if line.startswith("{"):
                values.append(json.loads(line))
            else:
                values.append(line)
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        raw = value.get("organisation_number") or value.get("orgnr") if isinstance(value, dict) else value
        org = digits(raw) if len(digits(raw)) == 9 else str(raw).strip()
        if org in seen:
            continue
        seen.add(org)
        out.append(org)
    return out


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":"), sort_keys=False) + "\n")
    tmp.replace(path)


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
