"""Polite crawl that ties public websites to organisation numbers (cache builder, not part of the run).

For each domain: resolve it, read robots.txt, fetch the front page and, when the
front page shows no organisation number, one contact/about page. From the
visible text it keeps only identifiers: labelled organisation numbers, Norwegian
phone numbers and email addresses. No page content is stored.

Output: JSONL rows {domain, final_url, orgnrs, phones, emails, title}. Matching
to companies happens in build_website_seeds.py.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import aiodns
import httpx
from selectolax.parser import HTMLParser

UA = "VardeCacheBuilder/1.0 (+https://github.com/kinnuworks/varde)"
MAX_BYTES = 400_000
ORG_LABEL = re.compile(
    r"(?:org(?:anisasjons)?\.?\s*-?\s*(?:nr|nummer|no|number)\.?|foretaksregisteret|mva(?:-?nr)?|vat(?:\s*no)?|"
    r"organization number)\s*[:.]?\s*((?:NO\s?)?[89]\d{2}[\s. ]?\d{3}[\s. ]?\d{3})", re.I)
NO_MVA = re.compile(r"NO\s?([89]\d{2})[\s. ]?(\d{3})[\s. ]?(\d{3})\s?MVA", re.I)
PHONE = re.compile(r"(?:\+47|0047)?[\s ]?(?<!\d)([2-9]\d)[\s .]?(\d{2})[\s .]?(\d{2})[\s .]?(\d{2})(?!\d)")
EMAIL = re.compile(r"[\w.+-]+@([\w-]+(?:\.[\w-]+)+)")
CONTACT = re.compile(r"(kontakt|contact|om-oss|om_oss|omoss|about|personvern|privacy)", re.I)
W = (3, 2, 7, 6, 5, 4, 3, 2)


def valid(n: str) -> bool:
    if not re.fullmatch(r"[89]\d{8}", n):
        return False
    c = 11 - sum(int(a) * b for a, b in zip(n[:8], W)) % 11
    c = 0 if c == 11 else c
    return c != 10 and c == int(n[8])


def extract(html: str) -> tuple[str, list[str], list[str], list[str], list[str]]:
    tree = HTMLParser(html)
    for node in tree.css("script, style, noscript, svg, template"):
        node.decompose()
    title = (tree.css_first("title").text().strip() if tree.css_first("title") else "")[:200]
    body = tree.body or tree.root
    text = re.sub(r"\s+", " ", body.text(separator=" ") if body else "")
    orgs = {re.sub(r"\D", "", m.group(1))[-9:] for m in ORG_LABEL.finditer(text)}
    orgs |= {"".join(m.groups()) for m in NO_MVA.finditer(text)}
    orgs = sorted(n for n in orgs if valid(n))
    phones = sorted({"".join(m.groups()) for m in PHONE.finditer(text)})[:20]
    emails = sorted({m.group(0).lower() for m in EMAIL.finditer(text)})[:20]
    hrefs = [a.attributes.get("href") or "" for a in tree.css("a[href]")]
    return title, orgs, phones, emails, hrefs


class Crawler:
    def __init__(self, out: Path, concurrency: int) -> None:
        self.out = out
        self.sem = asyncio.Semaphore(concurrency)
        self.resolver = aiodns.DNSResolver(timeout=3, tries=1)
        self.client = httpx.AsyncClient(headers={"User-Agent": UA, "Accept-Language": "nb-NO,nb;q=0.9,en;q=0.5"},
                                        timeout=httpx.Timeout(9.0, connect=5.0), follow_redirects=True,
                                        limits=httpx.Limits(max_connections=concurrency, max_keepalive_connections=0),
                                        verify=False)
        self.done = 0
        self.hits = 0
        self.t0 = time.monotonic()
        self.fh = out.open("a", encoding="utf-8")

    async def resolves(self, host: str) -> bool:
        try:
            await self.resolver.query(host, "A")
            return True
        except aiodns.error.DNSError:
            try:
                await self.resolver.query("www." + host, "A")
                return True
            except aiodns.error.DNSError:
                return False

    async def get(self, url: str) -> httpx.Response | None:
        try:
            async with self.client.stream("GET", url) as r:
                chunks, size = [], 0
                async for chunk in r.aiter_bytes():
                    size += len(chunk)
                    chunks.append(chunk)
                    if size > MAX_BYTES:
                        break
                r._content = b"".join(chunks)  # noqa: SLF001
                return r
        except (httpx.HTTPError, UnicodeError, ValueError):
            return None

    async def robots(self, origin: str) -> RobotFileParser:
        rp = RobotFileParser()
        r = await self.get(origin + "/robots.txt")
        if r is None or r.status_code >= 400:
            rp.parse([])
        else:
            rp.parse(r.text[:100_000].splitlines())
        return rp

    async def crawl(self, domain: str) -> None:
        async with self.sem:
            row: dict = {"domain": domain}
            try:
                if not await self.resolves(domain):
                    row["error"] = "dns"
                    return
                origin = f"https://{domain}"
                rp = await self.robots(origin)
                if not (rp.can_fetch(UA, origin + "/") and rp.can_fetch("VardeCacheBuilder", origin + "/")):
                    row["error"] = "robots"
                    return
                r = await self.get(origin + "/")
                if r is None:
                    r = await self.get(f"http://{domain}/")
                if r is None or r.status_code >= 400 or "html" not in r.headers.get("content-type", "html"):
                    row["error"] = "fetch" if r is None else f"http_{r.status_code}"
                    return
                final = str(r.url)
                row["final_url"] = final
                title, orgs, phones, emails, hrefs = extract(r.text)
                row.update(title=title, orgnrs=orgs, phones=phones, emails=emails)
                if not orgs:
                    link = next((urljoin(final, h) for h in hrefs
                                 if CONTACT.search(h) and urlsplit(urljoin(final, h)).hostname == urlsplit(final).hostname), None)
                    if link and rp.can_fetch(UA, link):
                        await asyncio.sleep(0.5)
                        r2 = await self.get(link)
                        if r2 is not None and r2.status_code < 400:
                            _, o2, p2, e2, _ = extract(r2.text)
                            row["orgnrs"] = sorted(set(orgs) | set(o2))
                            row["phones"] = sorted(set(phones) | set(p2))[:30]
                            row["emails"] = sorted(set(emails) | set(e2))[:30]
                            row["contact_url"] = link
                if row.get("orgnrs"):
                    self.hits += 1
            except Exception as exc:  # keep crawling whatever one site does
                row["error"] = type(exc).__name__
            finally:
                self.fh.write(json.dumps(row, ensure_ascii=False) + "\n")
                self.done += 1
                if self.done % 2000 == 0:
                    self.fh.flush()
                    rate = self.done / (time.monotonic() - self.t0)
                    print(f"{self.done} done, {self.hits} with orgnr, {rate:.0f}/s", file=sys.stderr, flush=True)


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("domains")
    ap.add_argument("--out", default="crawl.jsonl")
    ap.add_argument("--concurrency", type=int, default=250)
    args = ap.parse_args()
    out = Path(args.out)
    seen = set()
    if out.exists():
        for line in out.read_text(encoding="utf-8").splitlines():
            try:
                seen.add(json.loads(line)["domain"])
            except (ValueError, KeyError):
                pass
    domains = [d.strip().lower() for d in Path(args.domains).read_text().split() if d.strip()]
    todo = [d for d in dict.fromkeys(domains) if d not in seen]
    print(f"{len(todo)} domains to crawl ({len(seen)} already done)", file=sys.stderr, flush=True)
    c = Crawler(out, args.concurrency)
    queue: asyncio.Queue[str] = asyncio.Queue()
    for d in todo:
        queue.put_nowait(d)

    async def worker() -> None:
        while not queue.empty():
            d = queue.get_nowait()
            try:
                await asyncio.wait_for(c.crawl(d), timeout=60)
            except asyncio.TimeoutError:
                pass

    await asyncio.gather(*(worker() for _ in range(args.concurrency)))
    c.fh.flush()
    c.fh.close()
    await c.client.aclose()


if __name__ == "__main__":
    import warnings
    warnings.filterwarnings("ignore")
    asyncio.run(main())
