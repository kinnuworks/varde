"""Build the declared website-candidate cache (src/varde/data/website_seeds.json.gz).

Inputs
- crawl.jsonl from crawl_candidates.py (identifiers found on public front/contact pages)
- Brønnøysund bulk files of entities and sub-units (NLOD 2.0)
- the Signalpost company universe

A domain becomes a candidate for a company when
- its pages print the company's organisation number (strongest),
- its pages show a phone or email that the register lists for exactly one entity,
- it is the register's website or email domain for one of the company's sub-units, or
- it is the email domain the register lists for the company itself.
Domains that print many organisation numbers (directories, accountants, web agencies)
are dropped. Only organisation number, domain and source tag are stored. Seeds are
candidates: the run fetches every one live and publishes it only with on-site proof.
"""
from __future__ import annotations

import argparse
import gzip
import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import ijson
import tldextract

TLD = tldextract.TLDExtract(suffix_list_urls=(), cache_dir=None)
WEBMAIL = {"gmail.com", "hotmail.com", "outlook.com", "live.com", "live.no", "online.no", "yahoo.com", "icloud.com",
           "me.com", "msn.com", "frisurf.no", "broadpark.no", "getmail.no", "start.no", "c2i.net", "altibox.no",
           "lyse.net", "hotmail.no", "outlook.no", "epost.no", "mail.com", "protonmail.com", "proton.me", "aol.com",
           "telenor.no", "googlemail.com", "gmx.com", "yahoo.no", "tele2.no", "bluezone.no", "ebnett.no"}
RANK = {"crawl_orgnr": 0, "registry_email_domain": 1, "subunit_website": 2, "crawl_phone": 3, "crawl_email": 4}


def dom(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip().lower()
    if "@" in value:
        value = value.split("@", 1)[1]
    host = re.sub(r"^https?://", "", value).split("/")[0]
    ext = TLD(host)
    return f"{ext.domain}.{ext.suffix}" if ext.domain and ext.suffix else None


def phone8(value: str | None) -> str | None:
    d = re.sub(r"\D", "", value or "")
    if d.startswith("47") and len(d) == 10:
        d = d[2:]
    return d if len(d) == 8 else None


def stream(path: str):
    with gzip.open(path, "rb") as fh:
        yield from ijson.items(fh, "item")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--crawl", nargs="+", required=True)
    ap.add_argument("--enheter", required=True)
    ap.add_argument("--underenheter")
    ap.add_argument("--universe", required=True)
    ap.add_argument("--out", default="src/varde/data/website_seeds.json.gz")
    args = ap.parse_args()

    universe = {json.loads(l)["organisation_number"] for l in gzip.open(args.universe, "rt")}
    phone_owner: dict[str, set[str]] = defaultdict(set)
    email_owner: dict[str, set[str]] = defaultdict(set)
    email_dom_owner: dict[str, set[str]] = defaultdict(set)
    seeds: dict[str, dict[str, str]] = defaultdict(dict)

    def add(org: str, domain: str | None, source: str) -> None:
        if not domain or org not in universe or domain in WEBMAIL:
            return
        current = seeds[org].get(domain)
        if current is None or RANK[source] < RANK[current]:
            seeds[org][domain] = source

    for rec in stream(args.enheter):
        org = rec.get("organisasjonsnummer")
        for key in ("telefon", "mobil"):
            p = phone8(rec.get(key))
            if p:
                phone_owner[p].add(org)
        email = (rec.get("epostadresse") or "").lower().strip()
        if email:
            email_owner[email].add(org)
            d = dom(email)
            if d and d not in WEBMAIL:
                email_dom_owner[d].add(org)
    for d, owners in email_dom_owner.items():
        if len(owners) <= 3:
            for org in owners:
                add(org, d, "registry_email_domain")
    for rec in (stream(args.underenheter) if args.underenheter else []):
        parent = rec.get("overordnetEnhet")
        if parent in universe:
            add(parent, dom(rec.get("hjemmeside")), "subunit_website")

    crowded = 0
    for path in args.crawl:
        for line in open(path, encoding="utf-8"):
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if row.get("error") or not row.get("final_url"):
                continue
            d = dom(row["final_url"]) or row["domain"]
            orgs = [o for o in row.get("orgnrs") or []]
            if len(orgs) > 4:
                crowded += 1
                continue
            for o in orgs:
                add(o, d, "crawl_orgnr")
            if orgs:
                continue
            phones = row.get("phones") or []
            if len(phones) <= 4:
                for p in phones:
                    owners = phone_owner.get(p, set())
                    if len(owners) == 1:
                        add(next(iter(owners)), d, "crawl_phone")
            for e in (row.get("emails") or [])[:6]:
                owners = email_owner.get(e, set())
                if len(owners) == 1:
                    add(next(iter(owners)), d, "crawl_email")

    out = {org: [d for d, _ in sorted(ds.items(), key=lambda kv: RANK[kv[1]])][:4] for org, ds in seeds.items()}
    tags = {org: {d: seeds[org][d] for d in ds} for org, ds in out.items()}
    by_source: dict[str, int] = defaultdict(int)
    for ds in tags.values():
        for s in set(ds.values()):
            by_source[s] += 1
    payload = {"built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "companies": len(out), "by_source": dict(by_source), "dropped_crowded_domains": crowded,
               "seeds": out, "tags": tags}
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(args.out, "wt", encoding="utf-8") as fh:
        json.dump(payload, fh, separators=(",", ":"))
    print(json.dumps({k: v for k, v in payload.items() if k not in ("seeds", "tags")}, indent=1))


if __name__ == "__main__":
    main()
