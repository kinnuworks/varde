"""Search-based website candidates for the declared seed cache (cache builder, not part of the run).

For companies likely to have a website the register does not list (most employees
first), query a search API with the legal name and town and keep only result domains
that carry a distinctive part of the name. Output rows: {orgnr, domains, provider}.
Search results are candidates only: the run fetches each domain live and publishes it
only with proof on the site itself. Raw result titles and snippets are not stored.
"""
from __future__ import annotations

import argparse
import asyncio
import gzip
import json
import os
import sys
from pathlib import Path

import httpx
import tldextract

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from varde.util import ascii_slug, core_name  # noqa: E402
from varde.web.site import PLATFORM_DOMAINS, distinctive  # noqa: E402

TLD = tldextract.TLDExtract(suffix_list_urls=(), cache_dir=None)
SKIP = PLATFORM_DOMAINS | {"wikipedia.org", "linkedin.com", "proff.no", "purehelp.no", "1881.no", "gulesider.no",
                           "regnskapstall.no", "forvalt.no", "brreg.no", "finn.no", "bedrift.no", "kompass.com",
                           "allabolag.se", "opencorporates.com", "dnb.com", "bloomberg.com", "zoominfo.com",
                           "crunchbase.com", "glassdoor.com", "indeed.com", "facebook.com", "instagram.com",
                           "youtube.com", "nav.no", "arbeidsplassen.no", "kununu.com", "hitta.se", "eniro.no",
                           "vg.no", "dn.no", "e24.no", "nrk.no", "aftenposten.no", "tu.no", "finansavisen.no"}


def domain(url: str) -> str | None:
    e = TLD(url)
    return f"{e.domain}.{e.suffix}".lower() if e.domain and e.suffix else None


def plausible(dom: str, name: str) -> bool:
    label = ascii_slug(dom.split(".")[0])
    words = [ascii_slug(w) for w in core_name(name).split() if len(ascii_slug(w)) >= 3]
    return any(w in label for w in words if w not in ("holding", "norge", "group", "gruppen", "invest", "eiendom"))


async def serper(client: httpx.AsyncClient, q: str) -> list[str]:
    r = await client.post("https://google.serper.dev/search", json={"q": q, "gl": "no", "hl": "no", "num": 10},
                          headers={"X-API-KEY": os.environ["SERPER_API_KEY"]})
    r.raise_for_status()
    return [x.get("link", "") for x in r.json().get("organic", [])]


async def brave(client: httpx.AsyncClient, q: str) -> list[str]:
    r = await client.get("https://api.search.brave.com/res/v1/web/search", params={"q": q, "country": "no", "count": 10},
                         headers={"X-Subscription-Token": os.environ["BRAVE_API_KEY"], "Accept": "application/json"})
    r.raise_for_status()
    return [x.get("url", "") for x in (r.json().get("web") or {}).get("results", [])]


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--universe", required=True)
    ap.add_argument("--out", default="search_candidates.jsonl")
    ap.add_argument("--provider", choices=["serper", "brave"], required=True)
    ap.add_argument("--limit", type=int, default=2400)
    ap.add_argument("--skip", type=int, default=0, help="skip this many targets (to split work across providers)")
    ap.add_argument("--qps", type=float, default=5)
    args = ap.parse_args()

    rows = [json.loads(l) for l in gzip.open(args.universe, "rt")]
    targets = [r for r in rows if not r.get("website") and (r.get("employees") or 0) >= 10
               and r["legal_form"] not in ("ENK", "BRL", "ESEK") and distinctive(r["name"])]
    targets.sort(key=lambda r: -(r.get("employees") or 0))
    out = Path(args.out)
    done = {json.loads(l)["orgnr"] for l in out.open()} if out.exists() else set()
    targets = [r for r in targets[args.skip:] if r["organisation_number"] not in done][:args.limit]
    print(f"{len(targets)} companies to search with {args.provider}", file=sys.stderr, flush=True)
    fn = serper if args.provider == "serper" else brave
    found = 0
    async with httpx.AsyncClient(timeout=20) as client:
        with out.open("a") as fh:
            for i, r in enumerate(targets):
                town = (r.get("municipality") or "").title()
                q = f"{core_name(r['name'])} {town}".strip()
                try:
                    links = await fn(client, q)
                except httpx.HTTPStatusError as exc:
                    print(f"stopped at {i}: HTTP {exc.response.status_code}", file=sys.stderr)
                    break
                except httpx.HTTPError:
                    continue
                doms = []
                for link in links:
                    d = domain(link)
                    if d and d not in SKIP and d not in doms and plausible(d, r["name"]):
                        doms.append(d)
                fh.write(json.dumps({"orgnr": r["organisation_number"], "domains": doms[:3], "provider": args.provider}) + "\n")
                fh.flush()
                found += bool(doms)
                if (i + 1) % 200 == 0:
                    print(f"{i + 1} searched, {found} with candidates", file=sys.stderr, flush=True)
                await asyncio.sleep(1 / args.qps)
    print(f"done: {found} companies with candidates", file=sys.stderr)


if __name__ == "__main__":
    asyncio.run(main())
