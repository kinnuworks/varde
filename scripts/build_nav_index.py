"""Build the declared NAV job-ad index used by the hiring source.

Walks NAV's public job feed (pam-stilling-feed.nav.no) from the start, keeps the
latest status of every ad, then fetches the detail record of each active ad to
read the employer organisation number. Output: src/varde/data/nav_index.json.gz,
a map from organisation number to the active ads that name it as employer.

The live run re-checks every matched ad, so a stale index entry can never be
published as an open position.
"""
from __future__ import annotations

import argparse
import gzip
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import httpx

BASE = "https://pam-stilling-feed.nav.no"
UA = "VardeIndexBuilder/1.0 (+https://github.com/kinnuworks/varde)"


def token(client: httpx.Client) -> str:
    text = client.get(f"{BASE}/api/publicToken").text
    for part in text.split():
        if part.startswith("eyJ"):
            return part.strip()
    raise SystemExit("NAV public token not found")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="src/varde/data/nav_index.json.gz")
    parser.add_argument("--state", default=".cache/nav_feed_state.json")
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()

    state_path = Path(args.state)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state = json.loads(state_path.read_text()) if state_path.exists() else {"next": "/api/v1/feed", "ads": {}}

    client = httpx.Client(headers={"User-Agent": UA}, timeout=60, follow_redirects=True)
    client.headers["Authorization"] = f"Bearer {token(client)}"

    pages = 0
    while state["next"]:
        response = client.get(BASE + state["next"])
        if response.status_code == 401:
            client.headers["Authorization"] = f"Bearer {token(client)}"
            continue
        response.raise_for_status()
        body = response.json()
        for item in body.get("items", []):
            entry = item.get("_feed_entry", {})
            state["ads"][item["id"]] = {
                "status": entry.get("status"),
                "title": entry.get("title"),
                "business": entry.get("businessName"),
                "municipal": entry.get("municipal"),
                "modified": entry.get("sistEndret") or item.get("date_modified"),
            }
        pages += 1
        next_url = body.get("next_url")
        if len(body.get("items") or []) < 1000 or next_url == state["next"]:
            break  # a partial page is the live end of the feed
        state["next"] = next_url
        if pages % 20 == 0:
            state_path.write_text(json.dumps(state))
            active = sum(1 for ad in state["ads"].values() if ad["status"] == "ACTIVE")
            print(f"pages={pages} ads={len(state['ads'])} active={active}", file=sys.stderr, flush=True)
    state_path.write_text(json.dumps(state))

    active_ids = [ad_id for ad_id, ad in state["ads"].items() if ad["status"] == "ACTIVE"]
    print(f"feed done: {len(state['ads'])} ads, {len(active_ids)} active", file=sys.stderr, flush=True)

    details: dict[str, dict] = state.setdefault("details", {})
    todo = [ad_id for ad_id in active_ids if ad_id not in details]

    def fetch(ad_id: str) -> tuple[str, dict | None]:
        for attempt in range(4):
            try:
                r = client.get(f"{BASE}/api/v1/feedentry/{ad_id}")
                if r.status_code in (429, 503):
                    time.sleep(2 * (attempt + 1))
                    continue
                if r.status_code != 200:
                    return ad_id, None
                return ad_id, r.json()
            except httpx.HTTPError:
                time.sleep(1 + attempt)
        return ad_id, None

    done = 0
    with ThreadPoolExecutor(args.workers) as pool:
        for ad_id, body in pool.map(fetch, todo):
            done += 1
            if body:
                ad = body.get("ad_content") or body
                employer = ad.get("employer") or {}
                details[ad_id] = {
                    "orgnr": employer.get("orgnr") or ad.get("orgnr"),
                    "employer": employer.get("name"),
                    "homepage": employer.get("homepage"),
                    "title": ad.get("title"),
                    "published": ad.get("published"),
                    "expires": ad.get("expires"),
                    "updated": ad.get("updated") or body.get("sistEndret"),
                    "url": ad.get("sourceurl") or ad.get("link"),
                    "locations": [loc.get("city") or loc.get("municipal") for loc in ad.get("workLocations", []) if isinstance(loc, dict)],
                }
            if done % 500 == 0:
                state_path.write_text(json.dumps(state))
                print(f"details {done}/{len(todo)}", file=sys.stderr, flush=True)
    state_path.write_text(json.dumps(state))

    index: dict[str, list[dict]] = {}
    for ad_id in active_ids:
        detail = details.get(ad_id)
        if not detail or not detail.get("orgnr"):
            continue
        org = "".join(ch for ch in str(detail["orgnr"]) if ch.isdigit())
        if len(org) != 9:
            continue
        index.setdefault(org, []).append({"id": ad_id, **{k: v for k, v in detail.items() if k != "orgnr"}})

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "source": f"{BASE}/api/v1/feed",
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "active_ads": len(active_ids),
        "organisations": len(index),
        "index": index,
    }
    with gzip.open(out, "wt", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
    print(f"wrote {out}: {len(index)} organisations", file=sys.stderr)


if __name__ == "__main__":
    main()
