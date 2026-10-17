"""Find the company's own website, prove it belongs to this organisation number, then mine it.

Publication rules
- A site is published only with proof on the site itself (see `prove`). Search
  results, seeds and name-derived domains are candidates, never evidence.
- Name-based proofs need a distinctive name and fail when the page carries
  another organisation number in an operator position.
- Facts derived from a site (social profiles, news, careers) are published only
  when the site is exclusive to this company.
- Parked, for-sale, placeholder and error pages never count.
"""
from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from html import unescape
from typing import Any
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit

import tldextract
from selectolax.parser import HTMLParser

from ..net import Fetcher, FetchError, Snapshot
from ..profile import Profile, text_span
from ..util import ascii_slug, core_name, digits, fold, valid_orgnr

_TLD = tldextract.TLDExtract(suffix_list_urls=(), cache_dir=None)

WEBMAIL = {
    "gmail.com", "googlemail.com", "hotmail.com", "hotmail.no", "outlook.com", "live.com", "live.no", "msn.com",
    "yahoo.com", "yahoo.no", "icloud.com", "me.com", "mac.com", "online.no", "frisurf.no", "broadpark.no",
    "getmail.no", "start.no", "c2i.net", "altibox.no", "lyse.net", "telenor.no", "epost.no", "mail.com",
    "protonmail.com", "proton.me", "aol.com", "gmx.com", "gmx.net", "hotmail.co.uk", "loqal.no", "tele2.no",
    "bluezone.no", "ebnett.no", "enivest.net", "haugnett.no", "nextgentel.com", "netcom.no", "chello.no",
    "kpnmail.nl", "yandex.com", "email.com", "outlook.no", "post.com", "inbox.com",
}
PLATFORM_DOMAINS = {
    "facebook.com", "instagram.com", "linkedin.com", "x.com", "twitter.com", "youtube.com", "tiktok.com",
    "wix.com", "wixsite.com", "squarespace.com", "wordpress.com", "blogspot.com", "google.com", "sites.google.com",
    "proff.no", "1881.no", "gulesider.no", "purehelp.no", "brreg.no", "finn.no", "mittanbud.no", "bedriftsdatabasen.no",
    "regnskapstall.no", "forvalt.no", "facebook.no", "jimdo.com", "webnode.com", "one.com", "domeneshop.no",
    "hugedomains.com", "sedo.com", "dan.com", "afternic.com", "godaddy.com", "parkingcrew.net", "bodis.com",
}
PARKED = re.compile(
    r"(domain (name )?(is )?for sale|domenet (er )?til salgs|this domain (has been|was) registered|parkert domene|"
    r"domain parking|account suspended|buy this domain|kjøp dette domenet|registrert hos domeneshop|"
    r"this site can.t be reached|default web page|index of /)", re.I)
PARKED_WEAK = re.compile(
    r"(coming soon|kommer snart|under (construction|utvikling|oppbygging)|hello world!|web ?hotel|"
    r"webhotell.{0,40}(aktivert|klar)|it works!|siden er under arbeid)", re.I)
ORG_LABEL = re.compile(
    r"(?:org(?:anisasjons)?\.?\s*-?\s*(?:nr|nummer|no|number)\.?|foretaksregisteret|mva(?:-?nr)?|vat(?:\s*no)?|"
    r"organization number|business id)\s*[:.]?\s*((?:NO\s?)?[89]\d{2}[\s. ]?\d{3}[\s. ]?\d{3})", re.I)
ANY_ORGNR = re.compile(r"(?<!\d)([89]\d{2})[\s. ]?(\d{3})[\s. ]?(\d{3})(?!\d)")
SOCIAL_HOSTS = {
    "facebook.com": "facebook.com", "fb.com": "facebook.com", "instagram.com": "instagram.com",
    "linkedin.com": "linkedin.com", "x.com": "x.com", "twitter.com": "x.com", "youtube.com": "youtube.com",
    "tiktok.com": "tiktok.com", "pinterest.com": "pinterest.com", "vimeo.com": "vimeo.com",
    "threads.net": "threads.net", "snapchat.com": "snapchat.com",
}
SOCIAL_BAD = re.compile(r"(sharer|share\.php|/share|intent/|/dialog/|/plugins/|/hashtag/|/search|/watch\?|"
                        r"/embed|/p/|/reel/|/status/|/posts/|/photos?/|/events?/|/groups?/|/login|/help|/policy|"
                        r"/privacy|/legal|/terms|/about/|/home\b|/tr\b|/l\.php|/permalink|story\.php)", re.I)
SOCIAL_GENERIC = {"facebook", "instagram", "linkedin", "twitter", "youtube", "tiktok", "wix", "squarespace",
                  "wordpress", "shopify", "home", "company", "pages", "profile.php", "people", "in", "user", "c",
                  "channel", "share", "sharer", "x", "intent", "watch", "explore", "accounts", "groups"}
ATS = re.compile(r"(teamtailor\.com|webcruiter\.(no|com)|jobbnorge\.no|recman\.(no|io)|hrmanager\.no|"
                 r"easycruit\.com|reachmee\.com|jobylon\.com|varbi\.com|workable\.com|lever\.co|"
                 r"greenhouse\.io|smartrecruiters\.com|recruitee\.com|talentech\.com|jobbsafari\.no)", re.I)
CAREERS_PATH = re.compile(r"/(karriere|career|careers|jobb|jobs|ledige[-_]stillinger|stillinger|jobbe-hos-oss|"
                          r"jobb-hos-oss|vacancies|rekruttering)(/|$|\.)", re.I)
JOB_WORDS = re.compile(r"(karriere|stilling|jobb|career|job|vacanc|ansett|rekrutt|søk|apply|work with us|join our team)", re.I)
CAREERS_TEXT = re.compile(r"^(karriere|ledige stillinger|stillinger|jobb hos oss|jobbe hos oss|careers?|jobs|"
                          r"jobb|vi ansetter|bli en av oss|work with us|join us|ledig stilling)$", re.I)
NEWS_PATH = re.compile(r"/(nyheter|nyhet|aktuelt|news|blogg?|presse|artikler|articles|media|press)(/|$)", re.I)
STUB_NEWS = re.compile(r"(hello world|hei,? verden|hallo,? verden|this is your first post|lorem ipsum|sample page|eksempelside|velkommen til wordpress)", re.I)
GENERIC_WORDS = {"holding", "invest", "eiendom", "service", "consulting", "bygg", "transport", "drift", "utvikling",
                 "handel", "norge", "norway", "nordic", "gruppen", "group", "partner", "partners", "regnskap", "data",
                 "it", "media", "design", "solutions", "eiendommer", "capital", "management", "ventures", "systems",
                 "maskin", "elektro", "entreprenør", "rør", "vvs", "tak", "trans", "shipping", "energi", "film", "musikk"}


@dataclass
class Candidate:
    url: str
    source: str           # registry_website | registry_email | nav_homepage | wikidata | seed | name_derived
    note: str | None = None


@dataclass
class Proof:
    method: str
    detail: str
    span: str
    strength: int          # 3 = organisation number on site, 2 = registry-declared or contact match, 1 = name+address


@dataclass
class PageView:
    snap: Snapshot
    tree: HTMLParser
    text: str              # visible text
    links: list[tuple[str, str, str]] = field(default_factory=list)  # (absolute href, raw href, anchor text)


def registered_domain(url_or_host: str) -> str | None:
    host = urlsplit(url_or_host if "://" in url_or_host else "http://" + url_or_host).hostname or ""
    ext = _TLD(host)
    if not ext.domain or not ext.suffix:
        return None
    return f"{ext.domain}.{ext.suffix}".lower()


def normalise_url(url: str) -> str | None:
    url = url.strip().strip("/")
    if not url or " " in url or "@" in url:
        return None
    if not re.match(r"^https?://", url, re.I):
        url = "https://" + url
    parts = urlsplit(url)
    if not parts.hostname or "." not in parts.hostname:
        return None
    return urlunsplit(("https", parts.netloc.lower(), parts.path or "/", "", ""))


def view(snap: Snapshot) -> PageView:
    tree = HTMLParser(snap.text)
    for node in tree.css("script, style, noscript, template, svg"):
        if node.tag == "script" and (node.attributes.get("type") or "").lower() == "application/ld+json":
            continue
        node.decompose()
    body = tree.body or tree.root
    text = re.sub(r"\s+", " ", body.text(separator=" ") if body else "").strip()
    links = []
    for a in tree.css("a[href]"):
        raw = a.attributes.get("href") or ""
        if raw.startswith(("mailto:", "tel:", "javascript:", "#")):
            links.append((raw, raw, (a.text() or "").strip()))
            continue
        links.append((urljoin(snap.final_url, unescape(raw)), raw, re.sub(r"\s+", " ", (a.text() or "")).strip()))
    return PageView(snap, tree, text, links)


def orgnr_mentions(page_text: str) -> tuple[set[str], set[str]]:
    """(labelled numbers, all valid numbers) found in visible text."""
    labelled = {digits(m.group(1))[-9:] for m in ORG_LABEL.finditer(page_text)}
    labelled = {n for n in labelled if valid_orgnr(n)}
    every = {"".join(m.groups()) for m in ANY_ORGNR.finditer(page_text)}
    return labelled, {n for n in every if valid_orgnr(n)}


def _raw_find(html: str, pattern: str) -> str | None:
    m = re.search(pattern, html)
    return m.group(0) if m else None


def visible_span(html: str, needle_pattern: str, context: int = 40) -> str | None:
    """Exact HTML around a match that sits in element text (between > and <), not in a script or attribute."""
    for m in re.finditer(needle_pattern, html, re.I):
        start, end = m.start(), m.end()
        left = html.rfind(">", 0, start)
        lt = html.rfind("<", 0, start)
        if left < lt:
            continue  # inside a tag
        tag_open = html.rfind("<", 0, left + 1)
        if re.match(r"<(script|style)\b", html[tag_open:tag_open + 8], re.I):
            continue
        right = html.find("<", end)
        if right < 0:
            continue
        lo = max(left + 1, start - context)
        hi = min(right, end + context)
        return html[lo:hi].strip() or None
    return None


def _orgnr_raw_pattern(org: str) -> str:
    a, b, c = org[:3], org[3:6], org[6:]
    sep = r"(?:\s|&nbsp;|&#160;| |\.|-)?"
    return rf"(?<!\d){a}{sep}{b}{sep}{c}(?!\d)"


def visible_name_span(html: str, legal_name: str) -> str | None:
    """Exact HTML text where the name appears as element text (not inside a URL or attribute)."""
    for needle in (legal_name, core_name(legal_name)):
        if len(needle) < 3:
            continue
        m = re.search(r">[^<>]{0,60}?" + re.escape(needle).replace(r"\ ", r"(?:\s|&nbsp;)+") + r"[^<>]{0,40}", html, re.I)
        if m:
            return m.group(0)[1:].strip() or None
    return None


def name_visible(page_text: str, legal_name: str) -> bool:
    core = core_name(legal_name)
    if len(core) < 3:
        return False
    text = " " + fold(page_text) + " "
    return f" {core} " in text


def distinctive(legal_name: str) -> bool:
    words = core_name(legal_name).split()
    if not words:
        return False
    meaningful = [w for w in words if w not in GENERIC_WORDS and len(w) > 2]
    return bool(meaningful) and len("".join(words)) >= 5


def phone_digits(value: str | None) -> str | None:
    d = digits(value)
    if d.startswith("47") and len(d) == 10:
        d = d[2:]
    if d.startswith("0047"):
        d = d[4:]
    return d if len(d) == 8 else None


def page_has_phone(page_text: str, phone: str) -> str | None:
    pattern = r"(?<!\d)" + r"[\s. -]?".join(phone) + r"(?!\d)"
    m = re.search(pattern, page_text)
    return m.group(0) if m else None


def prove(p: Profile, pv: PageView, cand: Candidate) -> tuple[Proof | None, str | None]:
    """Return (proof, rejection reason)."""
    org = p.organisation_number
    rec = p.context.get("entity") or {}
    legal = p.legal_name or ""
    text = pv.text
    html = pv.snap.text
    if len(text) < 120 or PARKED.search(text[:4000]) or (len(text) < 1500 and PARKED_WEAK.search(text)):
        return None, "parked, placeholder or empty page"
    labelled, every = orgnr_mentions(text)
    group = {g for g in p.context.get("group_orgs", set())} | {s.get("organisasjonsnummer") for s in p.context.get("subunits", [])}
    others_labelled = labelled - {org} - group
    raw = _raw_find(html, _orgnr_raw_pattern(org))
    crowd = (labelled | every) - {org} - group
    if len(crowd) >= 3:
        return None, f"page lists {len(crowd)} other organisation numbers (directory, supplier or client list)"
    if org in every and raw:
        span = visible_span(html, _orgnr_raw_pattern(org), context=50) or text_span(html, raw, context=50) or raw
        return Proof("orgnr_on_page", f"organisation number {org} printed on {pv.snap.final_url}", span, 3), None
    if others_labelled:
        return None, f"page names other organisation number(s) {sorted(others_labelled)[:3]}"
    named = name_visible(text, legal)
    reg_domain = registered_domain(rec.get("hjemmeside") or "") if rec.get("hjemmeside") else None
    cand_domain = registered_domain(pv.snap.final_url)
    if not named:
        return None, "legal name not visible on the page"
    name_span = visible_name_span(html, legal)
    phone = phone_digits(rec.get("telefon") or rec.get("mobil"))
    if phone:
        found = page_has_phone(html, phone)
        if found:
            span = visible_span(html, r"(?<!\d)" + r"[\s.\u00a0-]?".join(phone) + r"(?!\d)") or text_span(html, found, context=40) or found
            return Proof("registry_phone_and_name", f"registry phone {phone} and legal name on page", span, 2), None
    email = (rec.get("epostadresse") or "").lower()
    if email and email in html.lower():
        idx = html.lower().find(email)
        raw_email = html[idx:idx + len(email)]
        span = visible_span(html, re.escape(email)) or text_span(html, raw_email, context=30) or raw_email
        return Proof("registry_email_and_name", f"registry email {email} and legal name on page", span, 2), None
    if cand.source == "registry_website" and reg_domain and cand_domain == reg_domain and distinctive(legal):
        return Proof("registry_website_and_name", f"declared in Enhetsregisteret (hjemmeside) and shows the name",
                     name_span or "", 2), None
    addr = rec.get("forretningsadresse") or {}
    street = (addr.get("adresse") or [""])[0]
    postcode = addr.get("postnummer") or ""
    if street and postcode and distinctive(legal) and street.casefold() in html.casefold() and postcode in html:
        idx = html.casefold().find(street.casefold())
        raw_street = html[idx:idx + len(street)]
        return Proof("name_and_registered_address", f"legal name with registered address {street}, {postcode}",
                     text_span(html, raw_street, context=40) or raw_street, 1), None
    return None, "name visible but no organisation number, registry contact or address on the page"


def exclusive(p: Profile, pv: PageView) -> tuple[bool, str | None]:
    labelled, _ = orgnr_mentions(pv.text)
    group = set(p.context.get("group_orgs", set()))
    others = labelled - {p.organisation_number} - group
    if others:
        return False, f"site also names organisation number(s) {sorted(others)[:3]}"
    return True, None


# ---------------------------------------------------------------- discovery
def candidates(p: Profile, seeds: dict[str, list[str]] | None, nav_homepages: list[str]) -> list[Candidate]:
    rec = p.context.get("entity") or {}
    out: list[Candidate] = []
    seen: set[str] = set()

    def add(url: str | None, source: str) -> None:
        norm = normalise_url(url or "")
        if not norm:
            return
        dom = registered_domain(norm)
        if not dom or dom in seen or dom in PLATFORM_DOMAINS or dom in WEBMAIL:
            return
        seen.add(dom)
        out.append(Candidate(norm, source))

    add(rec.get("hjemmeside"), "registry_website")
    email = rec.get("epostadresse") or ""
    if "@" in email:
        add(email.split("@", 1)[1], "registry_email")
    for url in p.context.get("wikidata_websites", []):
        add(url, "wikidata")
    for url in nav_homepages:
        add(url, "nav_homepage")
    for dom in (seeds or {}).get(p.organisation_number, []):
        add(dom, "seed")
    form_code = (rec.get("organisasjonsform") or {}).get("kode")
    if distinctive(p.legal_name or "") and form_code not in ("ENK", "BRL", "ESEK"):
        core = core_name(p.legal_name or "")
        words = [ascii_slug(w) for w in core.split() if ascii_slug(w)]
        slug = "".join(words)
        filler = {"avd", "avdeling", "og", "i", "a", "the", "and", "co"}
        words = [w for w in words if w not in filler] or words
        slug = "".join(words)
        trimmed = [w for w in words if w not in ("holding", "invest", "gruppen", "group", "norge", "norway")]
        variants = [slug]
        if 1 < len(words) <= 4:
            variants.append("-".join(words))
        if form_code in ("AS", "ASA") and 4 <= len(slug) <= 20:
            add(f"{slug}.as", "name_derived")
        if trimmed and trimmed != words and len("".join(trimmed)) >= 5:
            variants.append("".join(trimmed))
        for v in variants:
            if len(v) >= 5:
                add(f"{v}.no", "name_derived")
        if len(slug) >= 6:
            add(f"{slug}.com", "name_derived")
    return out[:8]


# ---------------------------------------------------------------- mining
def _social(href: str) -> str | None:
    parts = urlsplit(href)
    host = (parts.hostname or "").lower().removeprefix("www.").removeprefix("m.").removeprefix("no.")
    platform = SOCIAL_HOSTS.get(host)
    if not platform or SOCIAL_BAD.search(parts.path + ("?" + parts.query if parts.query else "")):
        return None
    segs = [unquote(s) for s in parts.path.split("/") if s]
    if not segs:
        return None
    if platform == "linkedin.com":
        if len(segs) < 2 or segs[0] not in ("company", "school", "showcase"):
            return None
        handle = f"{segs[0]}/{segs[1]}"
    elif platform == "youtube.com":
        if segs[0].startswith("@"):
            handle = segs[0]
        elif segs[0] in ("channel", "c", "user") and len(segs) > 1:
            handle = f"{segs[0]}/{segs[1]}"
        else:
            return None
    elif platform == "facebook.com" and segs[0] == "profile.php":
        m = re.search(r"id=(\d+)", parts.query)
        if not m:
            return None
        handle = f"profile.php?id={m.group(1)}"
    else:
        handle = segs[0]
    base = handle.split("/")[-1].lstrip("@").lower()
    if base in SOCIAL_GENERIC or len(base) < 2:
        return None
    return f"{platform}/{handle}".lower()


def _reads_like_prose(text: str) -> bool:
    """Reject navigation dumps: repeated chunks or mostly capitalised menu words."""
    words = text.split()
    if len(words) < 6:
        return False
    for i in range(0, max(1, len(text) - 40), 10):
        chunk = text[i:i + 30]
        if len(chunk) == 30 and text.count(chunk) > 1:
            return False
    caps = sum(1 for w in words if w[:1].isupper())
    return caps / len(words) < 0.5


def _jsonld(pv: PageView) -> list[dict]:
    out = []
    for node in pv.tree.css('script[type="application/ld+json"]'):
        try:
            data = json.loads(node.text() or "")
        except ValueError:
            continue
        stack = [data]
        while stack:
            item = stack.pop()
            if isinstance(item, list):
                stack.extend(item)
            elif isinstance(item, dict):
                out.append(item)
                if "@graph" in item:
                    stack.append(item["@graph"])
    return out


def _types(item: dict) -> set[str]:
    t = item.get("@type")
    return {x for x in (t if isinstance(t, list) else [t]) if isinstance(x, str)}


ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?)?")


def _date_ok(value: str | None, founded: str | None) -> str | None:
    if not value:
        return None
    m = ISO_DATE.search(value)
    if not m:
        return None
    d = m.group(0)
    if d[:4] < "1995" or d[:10] > p_today():
        return None
    if founded and d[:10] < founded[:10]:
        return None
    return d


def p_today() -> str:
    from datetime import date
    return date.today().isoformat()


async def mine(p: Profile, f: Fetcher, home: PageView, ev_site: str | None) -> None:
    org = p.organisation_number
    site_dom = registered_domain(home.snap.final_url) or ""
    founded = (p.context.get("entity") or {}).get("stiftelsesdato")
    method = "site_mining_v1"
    lic = "Company-owned page; facts quoted under fair use with source link"

    def ev(pv: PageView, span: str | None) -> str | None:
        return p.add_evidence(pv.snap, source_class="company_owned", span=span, method=method, licence=lic)

    # Description
    for sel in ('meta[name="description"]', 'meta[property="og:description"]'):
        node = home.tree.css_first(sel)
        content = (node.attributes.get("content") or "").strip() if node else ""
        if 40 <= len(content) <= 600 and _reads_like_prose(content):
            raw = _raw_find(home.snap.text, re.escape(content[:60]))
            if raw:
                p.add_claim("website_description", "web_presence", unescape(content), [ev(home, raw)],
                            label="How the company describes itself", match={"method": "verified_site", "detail": site_dom})
            break
    title = home.tree.css_first("title")
    if title and title.text().strip():
        raw_title = _raw_find(home.snap.text, r"<title[^>]*>[^<]{1,200}</title>")
        if raw_title:
            p.add_claim("website_title", "web_presence", re.sub(r"\s+", " ", unescape(title.text())).strip(),
                        [ev(home, raw_title)], label="Website title")

    # Social profiles: links on the verified site, plus JSON-LD sameAs.
    pages = [home] + [x for x in p.context.get("extra_pages", []) if x is not home]
    socials: dict[str, str] = {}
    origin: dict[str, PageView] = {}
    for page in pages:
        for absolute, raw, _text in page.links:
            handle = _social(absolute)
            if handle and handle not in socials:
                socials[handle] = raw
                origin[handle] = page
        for item in _jsonld(page):
            same = item.get("sameAs")
            for url in same if isinstance(same, list) else [same] if isinstance(same, str) else []:
                handle = _social(url)
                if handle and handle not in socials:
                    socials[handle] = url.replace("/", "\\/") if url.replace("/", "\\/") in page.snap.text else url
                    origin[handle] = page
    by_platform: dict[str, list[str]] = {}
    for handle in socials:
        by_platform.setdefault(handle.split("/")[0], []).append(handle)
    for handle, raw in socials.items():
        platform = handle.split("/")[0]
        if len(by_platform[platform]) > 2:
            continue  # many accounts on one platform usually means a directory or partner list
        page = origin[handle]
        if raw not in page.snap.text:
            continue
        span = text_span(page.snap.text, raw, context=20) or raw
        original = unescape(raw) if raw.startswith("http") else "https://" + handle
        p.add_claim("social_profile", "web_presence", handle, [ev(page, span)],
                    label=f"{platform.split('.')[0].capitalize()} profile linked from the verified website",
                    match={"method": "linked_from_verified_site", "detail": site_dom},
                    extra={"url": original.replace("\\/", "/")})
    wd = p.context.get("wikidata_socials") or {}
    wd_sites = {registered_domain(u) for u in p.context.get("wikidata_websites", [])}
    if wd and site_dom in wd_sites and p.context.get("wikidata_snap") is not None:
        snap = p.context["wikidata_snap"]
        for platform, ident in wd.items():
            handle = f"{platform}/{ident}".lower() if not platform.endswith("@") else f"{platform}{ident}".lower()
            if any(h.startswith(platform.split("/")[0]) for h in socials):
                continue
            span = f'"value":"{ident}"'
            if span in snap.text:
                e = p.add_evidence(snap, source_class="open_knowledge_base", span=span, method="wikidata_social_v1",
                                   licence="CC0 (Wikidata)")
                p.add_claim("social_profile", "web_presence", handle, [e],
                            label="Social profile listed on the company's Wikidata item",
                            match={"method": "wikidata_item_with_matching_website", "detail": site_dom},
                            extra={"url": "https://" + handle.replace("youtube.com/channel/", "youtube.com/channel/")})

    # Hiring: careers pages and applicant-tracking boards linked from the site.
    hiring_urls: dict[str, tuple[str, str]] = {}
    hiring_page: dict[str, PageView] = {}
    for page in pages:
        for absolute, raw, text in page.links:
            if absolute.startswith(("mailto:", "tel:")):
                continue
            dom = registered_domain(absolute) or ""
            if ATS.search(absolute):
                key, kind = absolute.split("#")[0], "applicant_tracking_board"
            elif dom == site_dom and ((CAREERS_PATH.search(urlsplit(absolute).path) and (not text or JOB_WORDS.search(text)
                                                                                          or len(text) < 3))
                                      or CAREERS_TEXT.match(text or "")):
                key, kind = absolute.split("#")[0].rstrip("/"), "careers_page"
            else:
                continue
            if key not in hiring_urls:
                hiring_urls[key] = (raw, kind)
                hiring_page[key] = page
    for url, (raw, kind) in list(hiring_urls.items())[:3]:
        page = hiring_page[url]
        if raw not in page.snap.text:
            continue
        span = text_span(page.snap.text, raw, context=30) or raw
        p.add_claim("hiring_signal", "activity", url, [ev(page, span)],
                    label="Careers page on the verified website" if kind == "careers_page" else "Job board linked from the verified website",
                    match={"method": "linked_from_verified_site", "detail": site_dom}, extra={"signal_type": kind})
    boards = [u for u, (_r, kind) in hiring_urls.items() if kind == "applicant_tracking_board" and "teamtailor.com" in u]
    if boards:
        board = urlsplit(boards[0])
        rss_url = f"{board.scheme}://{board.netloc}/jobs.rss"
        snap = await f.get(rss_url, company=org)
        if not isinstance(snap, FetchError) and "<rss" in snap.text[:500]:
            channel = re.search(r"<channel>.*?<title>(.*?)</title>", snap.text, re.S)
            first = (core_name(p.legal_name or "").split() or [""])[0]
            if channel and first and first in fold(unescape(channel.group(1))):
                bv = PageView(snap, HTMLParser(""), snap.text)
                for item in list(re.finditer(r"<item>.*?</item>", snap.text, re.S))[:15]:
                    block = item.group(0)
                    t = re.search(r"<title>(.*?)</title>", block, re.S)
                    link = re.search(r"<link>(.*?)</link>", block, re.S)
                    d = re.search(r"<pubDate>(.*?)</pubDate>", block, re.S)
                    if not t or not link:
                        continue
                    title_txt = unescape(re.sub(r"<!\[CDATA\[|\]\]>", "", t.group(1))).strip()
                    when = _rss_date(d.group(1)) if d else None
                    e = ev(bv, t.group(0))
                    url = link.group(1).strip()
                    match = {"method": "company_board_linked_from_verified_site", "detail": board.netloc}
                    p.add_claim("job_ad", "activity", {"title": title_txt, "url": url, "published": when,
                                                       "source": "company job board"},
                                [e], as_of=(when or "")[:10], label="Open position on the company's job board", match=match)
                    p.add_claim("hiring_signal", "activity", url, [e], as_of=(when or "")[:10], label="Job posting",
                                match=match, extra={"signal_type": "job_posting", "title": title_txt})
    for item in _jsonld(home):
        if "JobPosting" in _types(item) and item.get("title"):
            posted = _date_ok(str(item.get("datePosted") or ""), founded)
            raw = _raw_find(home.snap.text, re.escape(json.dumps(item["title"], ensure_ascii=False)[1:-1][:60]))
            if raw:
                p.add_claim("job_ad", "activity", {"title": item["title"], "published": posted, "source": "company website",
                                                   "url": item.get("url") or home.snap.final_url},
                            [ev(home, raw)], as_of=(posted or "")[:10], label="Job posting on the company website")

    # Dated news: RSS/Atom first, then JSON-LD articles, then a news listing page.
    news: list[tuple[str, str, PageView, str, str | None]] = []
    feed_link = None
    for node in home.tree.css('link[rel="alternate"]'):
        typ = (node.attributes.get("type") or "").lower()
        href = node.attributes.get("href")
        if href and ("rss" in typ or "atom" in typ) and "comments" not in href:
            feed_link = urljoin(home.snap.final_url, href)
            break
    if not feed_link:
        origin = "{0.scheme}://{0.netloc}".format(urlsplit(home.snap.final_url))
        low = home.snap.text[:200_000].lower()
        if "wp-content" in low or "wordpress" in low:
            feed_link = origin + "/feed/"
        elif "wix.com" in low or "wixstatic" in low:
            feed_link = origin + "/blog-feed.xml"
        elif "squarespace" in low:
            feed_link = origin + "/blog?format=rss"
    if feed_link and registered_domain(feed_link) == site_dom:
        snap = await f.get(feed_link, company=org)
        if not isinstance(snap, FetchError):
            fv = PageView(snap, HTMLParser(snap.text), snap.text)
            for item in re.finditer(r"<(item|entry)\b.*?</\1>", snap.text, re.S | re.I):
                block = item.group(0)
                t = re.search(r"<title[^>]*>(.*?)</title>", block, re.S | re.I)
                d = re.search(r"<(pubDate|published|updated|dc:date)[^>]*>(.*?)</\1>", block, re.S | re.I)
                link = re.search(r"<link[^>]*>(.*?)</link>|<link[^>]*href=\"([^\"]+)\"", block, re.S | re.I)
                if not t or not d:
                    continue
                title_txt = unescape(re.sub(r"<!\[CDATA\[|\]\]>|<[^>]+>", "", t.group(1))).strip()
                when = _rss_date(d.group(2))
                when = _date_ok(when, founded) if when else None
                if title_txt and when and not STUB_NEWS.search(title_txt) and not re.search(r"[?&]p=1(?!\d)", block):
                    href = (link.group(1) or link.group(2) or "").strip() if link else ""
                    news.append((title_txt, when, fv, t.group(0), href or feed_link))
                if len(news) >= 10:
                    break
    if not news:
        for item in _jsonld(home):
            if _types(item) & {"NewsArticle", "BlogPosting", "Article"} and item.get("headline") and item.get("datePublished"):
                when = _date_ok(str(item["datePublished"]), founded)
                raw = _raw_find(home.snap.text, re.escape(json.dumps(item["headline"], ensure_ascii=False)[1:-1][:60]))
                if when and raw:
                    news.append((item["headline"], when, home, raw, item.get("url") or home.snap.final_url))
    if not news:
        listing = next((a for a, _r, _t in home.links if registered_domain(a) == site_dom and NEWS_PATH.search(urlsplit(a).path)), None)
        tries = [listing] if listing else []
        if not tries:
            origin = "{0.scheme}://{0.netloc}".format(urlsplit(home.snap.final_url))
            tries = [origin + "/nyheter", origin + "/aktuelt"]
        for url in tries:
            snap = await f.get(url, company=org)
            if isinstance(snap, FetchError) or "html" not in (snap.content_type or "html"):
                continue
            if registered_domain(snap.final_url) != site_dom or snap.final_url.rstrip("/") == home.snap.final_url.rstrip("/"):
                continue
            lv = view(snap)
            found = _listing_news(lv, founded)
            if not found:
                found = await _article_dates(f, org, lv, site_dom, founded)
            news.extend(found)
            if news:
                break
    news = _drop_bursts(news)
    seen_titles: set[str] = set()
    for title_txt, when, pv, raw, href in sorted(news, key=lambda x: x[1], reverse=True)[:10]:
        key = fold(title_txt)
        if key in seen_titles or raw not in pv.snap.text:
            continue
        seen_titles.add(key)
        p.add_claim("dated_news", "activity", f"{title_txt} ({when})", [ev(pv, raw)], as_of=when[:10],
                    label="Dated news from the company's own website",
                    match={"method": "verified_site", "detail": site_dom},
                    extra={"title": title_txt, "published": when, "url": href})


MONTHS = {"januar": 1, "january": 1, "jan": 1, "februar": 2, "february": 2, "feb": 2, "mars": 3, "march": 3, "mar": 3,
          "april": 4, "apr": 4, "mai": 5, "may": 5, "juni": 6, "june": 6, "jun": 6, "juli": 7, "july": 7, "jul": 7,
          "august": 8, "aug": 8, "september": 9, "sep": 9, "sept": 9, "oktober": 10, "october": 10, "okt": 10, "oct": 10,
          "november": 11, "nov": 11, "desember": 12, "december": 12, "des": 12, "dec": 12}
DATE_PATTERNS = [
    (re.compile(r"(?<!\d)(\d{1,2})\.\s?(" + "|".join(sorted(MONTHS, key=len, reverse=True)) + r")\.?\s+(20\d{2})", re.I), "dmy_name"),
    (re.compile(r"(" + "|".join(sorted(MONTHS, key=len, reverse=True)) + r")\.?\s+(\d{1,2}),?\s+(20\d{2})", re.I), "mdy_name"),
    (re.compile(r"(?<!\d)(\d{1,2})\.(\d{1,2})\.(20\d{2})(?!\d)"), "dmy_dot"),
    (re.compile(r"(?<!\d)(20\d{2})-(\d{2})-(\d{2})(?!\d)"), "iso"),
]


def find_date(text: str) -> tuple[str, str] | None:
    """(ISO date, exact matched text) for the first unambiguous date in `text`."""
    for pattern, kind in DATE_PATTERNS:
        m = pattern.search(text)
        if not m:
            continue
        try:
            if kind == "dmy_name":
                d, mo, y = int(m.group(1)), MONTHS[m.group(2).lower()], int(m.group(3))
            elif kind == "mdy_name":
                mo, d, y = MONTHS[m.group(1).lower()], int(m.group(2)), int(m.group(3))
            elif kind == "dmy_dot":
                d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
            else:
                y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
            from datetime import date
            return date(y, mo, d).isoformat(), m.group(0)
        except (ValueError, KeyError):
            continue
    return None


def _listing_news(lv: PageView, founded: str | None) -> list[tuple[str, str, PageView, str, str]]:
    out: list[tuple[str, str, PageView, str, str]] = []
    site_dom = registered_domain(lv.snap.final_url)
    seen: set[str] = set()
    for node in lv.tree.css("article, li, div, section"):
        links = [a for a in node.css("a[href]") if len((a.text() or "").strip()) >= 12]
        if len(links) != 1:
            continue
        text = re.sub(r"\s+", " ", node.text(separator=" ")).strip()
        if len(text) > 700:
            continue
        a = links[0]
        href = urljoin(lv.snap.final_url, a.attributes.get("href") or "")
        if registered_domain(href) != site_dom or href in seen or href.rstrip("/") == lv.snap.final_url.rstrip("/"):
            continue
        title_txt = re.sub(r"\s+", " ", a.text()).strip()
        head = node.css_first("h1, h2, h3, h4")
        if head and len(head.text().strip()) >= 12:
            title_txt = re.sub(r"\s+", " ", head.text()).strip()
        when = None
        raw = None
        t = node.css_first("time[datetime]")
        if t:
            when = _date_ok(t.attributes.get("datetime"), founded)
            raw = _raw_find(lv.snap.text, r'datetime="' + re.escape(t.attributes.get("datetime") or "") + '"')
        if not when:
            found = find_date(text)
            if found:
                when = _date_ok(found[0], founded)
                raw = found[1] if found[1] in lv.snap.text else None
        if not when or not raw or STUB_NEWS.search(title_txt) or len(title_txt) > 200:
            continue
        seen.add(href)
        out.append((title_txt, when, lv, raw, href))
        if len(out) >= 10:
            break
    return out


def _drop_bursts(items: list) -> list:
    """Catalogue imports publish many posts within minutes; those are not news."""
    if len(items) < 3:
        return items
    times = sorted(x[1] for x in items)
    keep = []
    for item in items:
        t = item[1]
        close = sum(1 for u in times if u[:13] == t[:13])
        if close >= 3 and len(t) > 10:
            continue
        keep.append(item)
    return keep


async def _article_dates(f: Fetcher, org: str, lv: PageView, site_dom: str, founded: str | None) -> list:
    """Open up to three article links from a news listing and read their declared publication date."""
    base = lv.snap.final_url.rstrip("/")
    links = []
    for absolute, _raw, text in lv.links:
        a = absolute.split("#")[0].rstrip("/")
        if (registered_domain(a) == site_dom and a.startswith(base + "/") and a != base and len(text) >= 12
                and a not in [x[0] for x in links] and not STUB_NEWS.search(text)):
            links.append((a, re.sub(r"\s+", " ", text).strip()))
    out = []
    for url, anchor in links[:3]:
        snap = await f.get(url, company=org)
        if isinstance(snap, FetchError):
            continue
        av = view(snap)
        raw = None
        when = None
        for pat in (r'<meta[^>]+property="article:published_time"[^>]+content="([^"]+)"',
                    r'"datePublished"\s*:\s*"([^"]+)"', r'<time[^>]+datetime="([^"]+)"'):
            m = re.search(pat, snap.text)
            if m:
                when = _date_ok(m.group(1), founded)
                raw = m.group(0)
                if when:
                    break
        if not when or not raw:
            continue
        h1 = av.tree.css_first("h1")
        title = re.sub(r"\s+", " ", h1.text()).strip() if h1 else anchor
        if 8 <= len(title) <= 200 and not STUB_NEWS.search(title):
            out.append((title, when, av, raw, snap.final_url))
    return out


def _rss_date(value: str) -> str | None:
    from email.utils import parsedate_to_datetime
    value = unescape(value).strip()
    if ISO_DATE.match(value):
        return value
    try:
        return parsedate_to_datetime(value).isoformat()
    except (TypeError, ValueError, IndexError):
        return None


# ---------------------------------------------------------------- driver
async def website(p: Profile, f: Fetcher, seeds: dict[str, list[str]] | None, nav_homepages: list[str]) -> None:
    org = p.organisation_number
    cands = candidates(p, seeds, nav_homepages)
    if not cands:
        p.mark_field("official_website", "web_presence", "not_available",
                     "No website in the register, no company email domain and no other candidate to check.")
        return
    rejected: list[str] = []
    for cand in cands:
        snap = await f.get(cand.url, company=org)
        if isinstance(snap, FetchError) and snap.reason in ("network", "timeout") and cand.url.startswith("https://"):
            snap = await f.get("http://" + cand.url[len("https://"):], company=org)
        if isinstance(snap, FetchError):
            rejected.append(f"{cand.url}: {snap.reason}")
            continue
        if "html" not in snap.content_type and snap.content_type:
            rejected.append(f"{cand.url}: not an HTML page")
            continue
        if registered_domain(snap.final_url) in PLATFORM_DOMAINS:
            rejected.append(f"{cand.url}: redirects to a platform")
            continue
        pv = view(snap)
        proof, reason = prove(p, pv, cand)
        contact_pv = None
        if not proof and reason and "parked" not in reason and "other organisation" not in reason:
            links = []
            for a, _r, t in pv.links:
                if registered_domain(a) != registered_domain(snap.final_url) or a in links:
                    continue
                if re.search(r"(kontakt|contact|om-oss|om_oss|about|personvern|privacy|salgsbetingelser|vilkar|vilkår|"
                             r"policies/|terms|impressum|kjopsvilkar|kjøpsvilkår)", a, re.I):
                    links.append(a)
            def rank(a: str) -> int:
                if re.search(r"kontakt|contact", a, re.I):
                    return 0
                if re.search(r"kjopsvilkar|kjøpsvilkår|salgsbetingelser|vilkar|vilkår|terms|policies/", a, re.I):
                    return 1
                if re.search(r"om-oss|om_oss|about", a, re.I):
                    return 2
                return 3
            links.sort(key=rank)
            for link in links[:4]:
                csnap = await f.get(link, company=org)
                if isinstance(csnap, FetchError):
                    continue
                contact_pv = view(csnap)
                proof, reason2 = prove(p, contact_pv, cand)
                if proof:
                    break
                if reason2 and "other organisation" in reason2:
                    reason = reason2
                    break
        if not proof or not proof.span:
            rejected.append(f"{cand.url}: {reason or 'proof has no quotable span'}")
            continue
        proof_pv = contact_pv if contact_pv and proof else pv
        e = p.add_evidence(proof_pv.snap, source_class="company_owned", span=proof.span, method="website_identity_v1",
                           licence="Company-owned page; quoted as identity proof",
                           note=f"Candidate source: {cand.source}. {proof.detail}.")
        if not e:
            rejected.append(f"{cand.url}: proof span not in snapshot")
            continue
        dom = registered_domain(snap.final_url)
        excl, why = exclusive(p, pv)
        p.add_claim("official_website", "web_presence", dom, [e],
                    label="Official website", confidence=0.99 if proof.strength == 3 else 0.95,
                    match={"method": proof.method, "detail": proof.detail, "candidate_source": cand.source},
                    extra={"url": snap.final_url, "exclusive": excl})
        p.context["verified_site"] = snap.final_url
        if excl:
            if contact_pv is not None and contact_pv is not pv and exclusive(p, contact_pv)[0]:
                p.context["extra_pages"] = [contact_pv]
            elif not any(_social(a) for a, _r, _t in pv.links):
                link = next((a for a, _r, _t in pv.links if registered_domain(a) == dom
                             and re.search(r"(kontakt|contact)", a, re.I)), None)
                if link:
                    csnap = await f.get(link, company=org)
                    if not isinstance(csnap, FetchError):
                        cv = view(csnap)
                        if exclusive(p, cv)[0]:
                            p.context["extra_pages"] = [cv]
            await mine(p, f, pv, e)
        else:
            p.mark_field("social_profile", "web_presence", "ambiguous", f"Site-derived facts withheld: {why}.")
        return
    transient = ("network", "timeout", "budget")
    if rejected and any(any(r.endswith(": " + t) for t in transient) for r in rejected) and not p.context.get("web_retried"):
        p.context["web_retry"] = True
        p.context["web_retried"] = True
    reg = (p.context.get("entity") or {}).get("hjemmeside")
    esnap = p.context.get("entity_snap")
    if reg and esnap is not None and any(r.startswith(normalise_url(reg) or "~") and "other organisation" in r for r in rejected):
        from ..profile import json_span
        e = p.add_evidence(esnap, source_class="official_registry", span=json_span(esnap.text, "hjemmeside", reg),
                           method="brreg_entity_v1", licence="NLOD 2.0 (Brønnøysundregistrene)",
                           note="The register declares this website; the site itself names another organisation (often a manager or parent).")
        p.add_claim("related_website", "web_presence", registered_domain(normalise_url(reg) or reg),
                    [e], label="Website declared in the register, run by another organisation",
                    match={"method": "declared_in_register", "detail": "hjemmeside; site names another organisation number"},
                    extra={"exclusive": False, "url": normalise_url(reg)})
    if rejected and all(r.endswith(": blocked_robots") for r in rejected):
        state = "blocked"
    elif any("name visible" in r or "other organisation" in r for r in rejected):
        state = "ambiguous"
    else:
        state = "not_available"
    p.mark_field("official_website", "web_presence", state,
                 "No candidate could be proven to belong to this organisation number. Checked: " + "; ".join(rejected[:4]))
