"""Recall against a pooled reference, the way Signalpost scores it.

Pool = union of verified finds from every run passed in (our own plus rival runs).
Per family: 0.7 x share of pool companies covered + 0.3 x share of pool facts found.
Recall points = 50 x mean over the four external families.
"""
from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from urllib.parse import urlsplit

FAMILIES = {
    "website": ("official_website",),
    "social": ("social_profile",),
    "hiring": ("hiring_signal", "job_ad"),
    "news": ("dated_news",),
}


def norm(fam: str, c: dict) -> str | None:
    v = c.get("value")
    if fam == "website":
        s = str(v or "").lower()
        s = re.sub(r"^https?://", "", s).split("/")[0].removeprefix("www.")
        return s or None
    if fam == "social":
        return re.sub(r"^https?://(www\.)?", "", str(v or "").lower()).rstrip("/") or None
    if fam == "hiring":
        url = c.get("url") or (v.get("url") if isinstance(v, dict) else v)
        if not url:
            return None
        u = urlsplit(str(url))
        return (u.netloc.lower().removeprefix("www.") + u.path.rstrip("/").lower()) or None
    if fam == "news":
        title = c.get("title") or (str(v).rsplit(" (", 1)[0] if v else "")
        return re.sub(r"\W+", " ", str(title).lower()).strip()[:80] or None
    return None


def load(path: str) -> dict[str, dict[str, set[str]]]:
    out: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for line in open(path, encoding="utf-8"):
        e = json.loads(line)
        org = e.get("organisation_number")
        for c in e.get("claims") or []:
            if c.get("availability") != "available":
                continue
            for fam, fields in FAMILIES.items():
                if c.get("field") in fields:
                    key = norm(fam, c)
                    if key:
                        out[org][fam].add(key)
    return out


def main() -> None:
    names = sys.argv[1::2]
    runs = {n: load(p) for n, p in zip(names, sys.argv[2::2])}
    pool: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for run in runs.values():
        for org, fams in run.items():
            for fam, keys in fams.items():
                pool[org][fam] |= keys
    print(f"{'family':8} pool(companies/facts)  " + "  ".join(f"{n:>22}" for n in runs))
    totals = {n: [] for n in runs}
    for fam in FAMILIES:
        pc = [o for o in pool if pool[o][fam]]
        pf = sum(len(pool[o][fam]) for o in pc)
        cells = []
        for n, run in runs.items():
            cc = sum(1 for o in pc if run.get(o, {}).get(fam))
            cf = sum(len(run.get(o, {}).get(fam, set()) & pool[o][fam]) for o in pc)
            score = (0.7 * cc / len(pc) + 0.3 * cf / pf) if pc else 0
            totals[n].append(score)
            cells.append(f"{cc:>3}c {cf:>3}f -> {score:5.2f}")
        print(f"{fam:8} {len(pc):>4} / {pf:<6}          " + "  ".join(f"{c:>22}" for c in cells))
    for n, xs in totals.items():
        print(f"recall points {n}: {50 * sum(xs) / len(xs):.1f} / 50")


if __name__ == "__main__":
    main()
