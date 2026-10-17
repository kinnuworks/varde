"""Public records keyed by the organisation number: NAV jobs, GLEIF, Wikidata, TED, Doffin.

Batch sources make one request per chunk of companies and keep the response as
shared evidence; each claim quotes the record that carries this company's
number. Nothing here is matched by name.
"""
from __future__ import annotations

import gzip
import json
import os
import re
from importlib import resources
from typing import Any

from ..net import Fetcher, FetchError, Snapshot
from ..profile import Profile, json_object_bounds, json_span

NAV = "https://pam-stilling-feed.nav.no"
NAV_PUBLIC = "https://arbeidsplassen.nav.no/stillinger/stilling/"


# ---------------------------------------------------------------- NAV jobs
class NavIndex:
    def __init__(self) -> None:
        self.index: dict[str, list[dict]] = {}
        self.built_at: str | None = None
        self.token: str | None = None
        self.cursor: str | None = None
        self.closed: set[str] = set()
        self.tail_pages = 0
        try:
            raw = resources.files("varde.data").joinpath("nav_index.json.gz").read_bytes()
            body = json.loads(gzip.decompress(raw))
            self.index = body.get("index", {})
            self.built_at = body.get("built_at")
            self.cursor = body.get("cursor")
        except (FileNotFoundError, ModuleNotFoundError, OSError, ValueError):
            pass

    async def refresh(self, f: Fetcher, names: dict[str, list[str]], max_pages: int = 40) -> None:
        """Read the feed from the index cursor to its live end.

        Ads that turned inactive are dropped. New active ads whose employer name
        matches a batch company are fetched, and kept only when the ad's employer
        organisation number is that company's.
        """
        if not self.cursor:
            return
        token = await self.ensure_token(f)
        if not token:
            return
        from ..util import core_name
        cursor = self.cursor
        fresh: list[tuple[str, str]] = []
        while cursor and self.tail_pages < max_pages:
            snap = await f.get(f"{NAV}{cursor}", headers={"Authorization": f"Bearer {token}"}, accept_json=True)
            if isinstance(snap, FetchError):
                break
            self.tail_pages += 1
            body = snap.json()
            items = body.get("items") or []
            for item in items:
                entry = item.get("_feed_entry") or {}
                if entry.get("status") != "ACTIVE":
                    self.closed.add(item.get("id"))
                    continue
                key = core_name(entry.get("businessName") or "")
                if key in names:
                    fresh.append((item.get("id"), key))
            nxt = body.get("next_url")
            if len(items) < 1000 or not nxt or nxt == cursor:
                break
            cursor = nxt
        known = {ad["id"] for ads in self.index.values() for ad in ads}
        for ad_id, key in fresh[:60]:
            if ad_id in known:
                continue
            snap = await f.get(f"{NAV}/api/v1/feedentry/{ad_id}", headers={"Authorization": f"Bearer {token}"}, accept_json=True)
            if isinstance(snap, FetchError):
                continue
            content = snap.json().get("ad_content") or {}
            org = re.sub(r"\D", "", str((content.get("employer") or {}).get("orgnr") or ""))
            if len(org) == 9:
                self.index.setdefault(org, []).append({"id": ad_id, "title": content.get("title"),
                                                       "homepage": (content.get("employer") or {}).get("homepage")})
        for org, ads in list(self.index.items()):
            self.index[org] = [ad for ad in ads if ad["id"] not in self.closed]

    async def ensure_token(self, f: Fetcher) -> str | None:
        if self.token:
            return self.token
        snap = await f.get(f"{NAV}/api/publicToken")
        if isinstance(snap, FetchError):
            return None
        m = re.search(r"eyJ[\w.-]+", snap.text)
        self.token = m.group(0) if m else None
        return self.token


async def nav_jobs(p: Profile, f: Fetcher, nav: NavIndex, subunit_orgs: set[str]) -> None:
    org = p.organisation_number
    candidates = list(nav.index.get(org, []))
    for sub in subunit_orgs:
        candidates.extend(dict(ad, via_subunit=sub) for ad in nav.index.get(sub, []))
    if not nav.index:
        p.mark_field("job_ad", "activity", "failed", "NAV job ads could not be checked on this run.")
        return
    if not candidates:
        p.mark_field("job_ad", "activity", "not_available",
                     f"No active NAV job ad names this organisation number as employer (index built {nav.built_at}).")
        return
    token = await nav.ensure_token(f)
    published = 0
    for ad in candidates[:12]:
        url = f"{NAV}/api/v1/feedentry/{ad['id']}"
        snap = await f.get(url, company=org, headers={"Authorization": f"Bearer {token}"} if token else None,
                           accept_json=True)
        if isinstance(snap, FetchError):
            continue
        body = snap.json()
        if body.get("status") != "ACTIVE" or not body.get("ad_content"):
            continue
        content = body["ad_content"]
        employer = content.get("employer") or {}
        if re.sub(r"\D", "", str(employer.get("orgnr") or "")) not in ({org} | subunit_orgs):
            continue
        title = content.get("title")
        span = json_span(snap.text, "title", title) if title else None
        ev = p.add_evidence(snap, source_class="official_api", span=span, method="nav_job_feed_v1",
                            licence="NAV public job feed terms (arbeidsplassen.nav.no)")
        public_url = content.get("link") or f"{NAV_PUBLIC}{ad['id']}"
        locations = [x.get("city") or x.get("municipal") for x in content.get("workLocations") or [] if isinstance(x, dict)]
        value = {"title": title, "url": public_url, "published": content.get("published"),
                 "expires": content.get("expires"), "locations": [x for x in locations if x],
                 "employer": employer.get("name"), "source": "NAV"}
        if ad.get("via_subunit"):
            value["workplace_organisation_number"] = ad["via_subunit"]
        match = {"method": "employer_orgnr_in_ad", "detail": f"employer.orgnr = {employer.get('orgnr')}"}
        if p.add_claim("job_ad", "activity", value, [ev], as_of=(content.get("published") or "")[:10],
                       label="Open position (NAV)", match=match):
            p.add_claim("hiring_signal", "activity", public_url, [ev], as_of=(content.get("published") or "")[:10],
                        label="Job posting", match=match, extra={"signal_type": "job_posting", "title": title})
            published += 1
    if not published:
        p.mark_field("job_ad", "activity", "not_available",
                     "Indexed NAV ads for this employer are no longer active.")


# ---------------------------------------------------------------- GLEIF
def _spaced(org: str) -> str:
    return f"{org[:3]} {org[3:6]} {org[6:]}"


async def gleif_batch(f: Fetcher, orgs: list[str]) -> dict[str, tuple[Snapshot, dict]]:
    out: dict[str, tuple[Snapshot, dict]] = {}
    for i in range(0, len(orgs), 50):
        chunk = orgs[i:i + 50]
        filt = ",".join(_spaced(o) for o in chunk)
        snap = await f.get("https://api.gleif.org/api/v1/lei-records",
                           params={"filter[entity.registeredAs]": filt, "page[size]": 200}, accept_json=True)
        if isinstance(snap, FetchError):
            continue
        for rec in snap.json().get("data") or []:
            ent = (rec.get("attributes") or {}).get("entity") or {}
            juris = ent.get("jurisdiction")
            nr = re.sub(r"\D", "", ent.get("registeredAs") or "")
            if nr in chunk and (juris in (None, "NO")):
                out[nr] = (snap, rec)
    return out


def gleif_claims(p: Profile, hit: tuple[Snapshot, dict] | None) -> None:
    if not hit:
        return
    snap, rec = hit
    attrs = rec.get("attributes") or {}
    lei = attrs.get("lei") or rec.get("id")
    reg = attrs.get("registration") or {}
    bounds = json_object_bounds(snap.text, f'"lei":"{lei}"')
    span = json_span(snap.text, "lei", lei)
    ev = p.add_evidence(snap, source_class="official_api", span=span, method="gleif_lei_v1", licence="CC0 (GLEIF)")
    p.add_claim("lei", "identity",
                {"lei": lei, "status": reg.get("status"), "next_renewal": reg.get("nextRenewalDate"),
                 "initial_registration": reg.get("initialRegistrationDate"), "last_update": reg.get("lastUpdateDate")},
                [ev], as_of=(reg.get("lastUpdateDate") or "")[:10], label="Legal Entity Identifier",
                match={"method": "registeredAs_equals_orgnr", "detail": _spaced(p.organisation_number)})
    if reg.get("initialRegistrationDate"):
        p.add_claim("public_record", "activity",
                    {"type": "LEI registered", "date": reg["initialRegistrationDate"][:10], "reference": lei,
                     "url": f"https://search.gleif.org/#/record/{lei}"},
                    [ev], as_of=reg["initialRegistrationDate"][:10], label="LEI registration")
    _ = bounds


# ---------------------------------------------------------------- Wikidata
WIKIDATA_API = "https://www.wikidata.org/w/api.php"
SOCIAL_PROPS = {"P2002": "x.com", "P2013": "facebook.com", "P2003": "instagram.com", "P4264": "linkedin.com/company",
                "P2397": "youtube.com/channel", "P7085": "tiktok.com/@"}


async def wikidata_batch(f: Fetcher, orgs: list[str]) -> dict[str, tuple[Snapshot, dict, str]]:
    found: dict[str, str] = {}
    for i in range(0, len(orgs), 40):
        chunk = orgs[i:i + 40]
        query = "haswbstatement:" + "|".join(f"P2333={o}" for o in chunk)
        snap = await f.get(WIKIDATA_API, params={"action": "query", "list": "search", "srsearch": query,
                                                 "srlimit": 50, "format": "json"}, accept_json=True)
        if isinstance(snap, FetchError):
            continue
        for hit in (snap.json().get("query") or {}).get("search") or []:
            found[hit["title"]] = ""
    out: dict[str, tuple[Snapshot, dict, str]] = {}
    for qid in list(found)[:40]:
        snap = await f.get(f"https://www.wikidata.org/wiki/Special:EntityData/{qid}.json", accept_json=True)
        if isinstance(snap, FetchError):
            continue
        entity = (snap.json().get("entities") or {}).get(qid) or {}
        claims = entity.get("claims") or {}
        for c in claims.get("P2333") or []:
            nr = (((c.get("mainsnak") or {}).get("datavalue") or {}).get("value") or "")
            nr = re.sub(r"\D", "", str(nr))
            if nr in orgs:
                out[nr] = (snap, entity, qid)
    return out


def _wd_values(entity: dict, prop: str) -> list[Any]:
    vals = []
    for c in (entity.get("claims") or {}).get(prop) or []:
        if c.get("rank") == "deprecated":
            continue
        dv = (c.get("mainsnak") or {}).get("datavalue") or {}
        if "value" in dv:
            vals.append(dv["value"])
    return vals


def wikidata_claims(p: Profile, hit: tuple[Snapshot, dict, str] | None) -> None:
    if not hit:
        return
    snap, entity, qid = hit
    span = json_span(snap.text, "value", p.organisation_number) or json_span(snap.text, "id", qid)
    ev = p.add_evidence(snap, source_class="open_knowledge_base", span=span, method="wikidata_p2333_v1",
                        licence="CC0 (Wikidata)")
    label = ((entity.get("labels") or {}).get("nb") or (entity.get("labels") or {}).get("en") or {}).get("value")
    p.add_claim("wikidata_item", "identity", {"qid": qid, "label": label, "url": f"https://www.wikidata.org/wiki/{qid}"},
                [ev], label="Wikidata item", match={"method": "P2333_equals_orgnr", "detail": p.organisation_number})
    # Websites and social accounts from Wikidata are candidates only; they are published
    # after the website is proven live and matches (see web.mine).
    p.context["wikidata_websites"] = [v for v in _wd_values(entity, "P856") if isinstance(v, str)]
    socials = {}
    for prop, platform in SOCIAL_PROPS.items():
        for v in _wd_values(entity, prop):
            if isinstance(v, str):
                socials.setdefault(platform, v)
    p.context["wikidata_socials"] = socials
    p.context["wikidata_snap"] = snap
    for v in _wd_values(entity, "P946")[:3]:
        if isinstance(v, str):
            p.add_claim("isin", "identity", v, [p.add_evidence(snap, source_class="open_knowledge_base",
                                                               span=json_span(snap.text, "value", v), method="wikidata_p946_v1",
                                                               licence="CC0 (Wikidata)")], label="ISIN")


# ---------------------------------------------------------------- TED
TED_FIELDS = ["publication-number", "publication-date", "notice-type", "buyer-name", "buyer-identifier",
              "winner-identifier", "winner-name", "notice-title", "contract-nature"]


async def ted_batch(f: Fetcher, orgs: list[str]) -> dict[str, list[tuple[Snapshot, dict, str]]]:
    out: dict[str, list[tuple[Snapshot, dict, str]]] = {}
    for i in range(0, len(orgs), 50):
        chunk = orgs[i:i + 50]
        ids = " ".join(chunk)
        body = {"query": f"winner-identifier IN ({ids}) OR buyer-identifier IN ({ids})",
                "fields": TED_FIELDS, "limit": 250, "scope": "ALL", "sort": [{"field": "publication-date", "order": "desc"}]}
        snap = await f.get("https://api.ted.europa.eu/v3/notices/search", method="POST", body=body, accept_json=True)
        if isinstance(snap, FetchError):
            body.pop("sort")
            snap = await f.get("https://api.ted.europa.eu/v3/notices/search", method="POST", body=body, accept_json=True)
            if isinstance(snap, FetchError):
                continue
        for notice in snap.json().get("notices") or []:
            winner_ids = [re.sub(r"\D", "", str(x)) for x in notice.get("winner-identifier") or []]
            # The identifier list can include every tenderer; only a single-winner notice is unambiguous.
            winners = set(winner_ids) if len(set(winner_ids)) == 1 else set()
            buyer_ids = {re.sub(r"\D", "", str(x)) for x in notice.get("buyer-identifier") or []}
            # Joint qualification systems list hundreds of buyers and say nothing about one of them.
            buyers = buyer_ids if len(buyer_ids) <= 5 else set()
            for o in chunk:
                if o in winners:
                    out.setdefault(o, []).append((snap, notice, "winner"))
                elif o in buyers:
                    out.setdefault(o, []).append((snap, notice, "buyer"))
    return out


def _first_text(v: Any) -> str | None:
    if isinstance(v, dict):
        for lang in ("nor", "nob", "eng"):
            if v.get(lang):
                return v[lang][0] if isinstance(v[lang], list) else v[lang]
        for val in v.values():
            return val[0] if isinstance(val, list) else val
    if isinstance(v, list):
        return v[0] if v else None
    return v


def ted_claims(p: Profile, hits: list[tuple[Snapshot, dict, str]] | None) -> None:
    for snap, notice, role in (hits or [])[:15]:
        pub = notice.get("publication-number")
        span = json_span(snap.text, "publication-number", pub)
        ev = p.add_evidence(snap, source_class="official_api", span=span, method="ted_search_v1",
                            licence="TED notices, free reuse (EU Publications Office)")
        date = (notice.get("publication-date") or "")[:10]
        value = {"type": "Public contract awarded" if role == "winner" else "Procurement notice published as buyer",
                 "date": date, "reference": pub, "title": _first_text(notice.get("notice-title")),
                 "counterparty": _first_text(notice.get("buyer-name")) if role == "winner" else None,
                 "url": f"https://ted.europa.eu/en/notice/-/detail/{pub}", "source": "TED"}
        p.add_claim("public_record", "activity", value, [ev], as_of=date,
                    label="EU procurement notice",
                    match={"method": f"{role}_identifier_equals_orgnr", "detail": p.organisation_number})


# ---------------------------------------------------------------- Doffin
async def doffin(p: Profile, f: Fetcher) -> None:
    key = os.environ.get("DOFFIN_API_KEY")
    if not key:
        return
    org = p.organisation_number
    snap = await f.get("https://api.doffin.no/public/v2/search", params={"searchString": org, "numHitsPerPage": 20},
                       headers={"Ocp-Apim-Subscription-Key": key}, company=org, accept_json=True)
    if isinstance(snap, FetchError):
        p.error("doffin", snap)
        return
    body = snap.json()
    for hit in body.get("hits") or body.get("notices") or []:
        buyers = hit.get("buyer") or []
        ids = {re.sub(r"\D", "", str(b.get("organizationId") or "")) for b in buyers if isinstance(b, dict)}
        winners = hit.get("winner") or hit.get("winners") or []
        wids = {re.sub(r"\D", "", str(w.get("organizationId") or "")) for w in winners if isinstance(w, dict)}
        role = "buyer" if org in ids else "winner" if org in wids else None
        if not role:
            continue
        nid = hit.get("id") or hit.get("noticeId")
        span = json_span(snap.text, "id", nid) if nid else None
        ev = p.add_evidence(snap, source_class="official_api", span=span, method="doffin_search_v1",
                            licence="Doffin public API terms (DFØ)")
        date = (hit.get("publicationDate") or hit.get("issueDate") or "")[:10]
        p.add_claim("public_record", "activity",
                    {"type": "Norwegian procurement notice" + (" as buyer" if role == "buyer" else " (winner)"),
                     "date": date, "reference": nid, "title": hit.get("heading"),
                     "url": f"https://doffin.no/notices/{nid}", "source": "Doffin"},
                    [ev], as_of=date, label="Doffin notice",
                    match={"method": f"{role}_organizationId_equals_orgnr", "detail": org})
