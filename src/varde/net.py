"""One budgeted HTTP client for every outbound request.

Every fetch goes through `Fetcher.get`, which enforces:
- a batch-wide request cap and wall-clock deadline, plus a per-company cap;
- robots.txt (RFC 9309) on the first URL and on every redirect hop;
- refusal of private, loopback, link-local and other non-public addresses;
- per-host concurrency and a response-size cap.

Each successful response body is stored once, named by its SHA-256, so every
claim can point at the exact bytes it was read from.
"""
from __future__ import annotations

import asyncio
import ipaddress
import json
import socket
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpx

from . import __version__
from .util import sha256_bytes, utc_now

USER_AGENT = f"Varde/{__version__} (+https://github.com/kinnuworks/varde; company research agent)"
MAX_BYTES = 2_000_000
MAX_REDIRECTS = 5

# Hosts whose robots.txt we have read and that publish documented open APIs.
API_HOSTS = {
    "data.brreg.no", "api.gleif.org", "pam-stilling-feed.nav.no", "api.ted.europa.eu",
    "query.wikidata.org", "www.wikidata.org", "api.doffin.no", "dof-notices-prod-api.azure-api.net",
}


@dataclass
class Snapshot:
    url: str
    final_url: str
    status: int
    retrieved_at: str
    sha256: str
    path: str
    content_type: str
    text: str
    redirects: list[str] = field(default_factory=list)

    def json(self) -> Any:
        return json.loads(self.text)


@dataclass
class FetchError:
    url: str
    reason: str          # blocked_robots | blocked_policy | timeout | network | http_<code> | budget | too_large
    status: int | None = None
    retrieved_at: str = field(default_factory=utc_now)

    @property
    def state(self) -> str:
        if self.reason.startswith("blocked"):
            return "blocked"
        if self.reason == "http_404" or self.reason == "http_410":
            return "not_available"
        return "failed"


class Budget:
    def __init__(self, max_requests: int, deadline_s: float, per_company: int) -> None:
        self.max_requests = max_requests
        self.deadline = time.monotonic() + deadline_s
        self.per_company = per_company
        self.used = 0
        self.by_company: dict[str, int] = {}
        self.by_host: dict[str, int] = {}

    def remaining_s(self) -> float:
        return self.deadline - time.monotonic()

    def take(self, host: str, company: str | None) -> bool:
        if self.used >= self.max_requests or self.remaining_s() <= 0:
            return False
        if company is not None and self.by_company.get(company, 0) >= self.per_company:
            return False
        self.used += 1
        self.by_host[host] = self.by_host.get(host, 0) + 1
        if company is not None:
            self.by_company[company] = self.by_company.get(company, 0) + 1
        return True


class SnapshotStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def put(self, body: bytes, content_type: str) -> tuple[str, str]:
        digest = sha256_bytes(body)
        ext = ".json" if "json" in content_type else ".xml" if "xml" in content_type else ".html"
        rel = Path(digest[:2]) / f"{digest}{ext}"
        target = self.root / rel
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(body)
        return digest, f"snapshots/{rel.as_posix()}"


def _public_ip(ip: str) -> bool:
    addr = ipaddress.ip_address(ip)
    return not (addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_multicast
                or addr.is_reserved or addr.is_unspecified)


class Fetcher:
    def __init__(self, store: SnapshotStore, budget: Budget, *, timeout: float = 12.0,
                 per_host: int = 2, global_limit: int = 48) -> None:
        self.store = store
        self.budget = budget
        self.client = httpx.AsyncClient(
            headers={"User-Agent": USER_AGENT, "Accept-Language": "nb-NO,nb;q=0.9,no;q=0.8,en;q=0.6"},
            timeout=httpx.Timeout(timeout, connect=8.0),
            follow_redirects=False,
            limits=httpx.Limits(max_connections=global_limit, max_keepalive_connections=global_limit),
            http2=False,
        )
        self.per_host = per_host
        self._host_locks: dict[str, asyncio.Semaphore] = {}
        self._robots: dict[str, RobotFileParser | None] = {}
        self._robots_locks: dict[str, asyncio.Lock] = {}
        self._dns: dict[str, bool] = {}
        self.api_per_host = {"data.brreg.no": 12, "pam-stilling-feed.nav.no": 6}

    async def close(self) -> None:
        await self.client.aclose()

    def _sem(self, host: str) -> asyncio.Semaphore:
        if host not in self._host_locks:
            self._host_locks[host] = asyncio.Semaphore(self.api_per_host.get(host, self.per_host))
        return self._host_locks[host]

    async def _host_is_public(self, host: str) -> bool:
        if host in self._dns:
            return self._dns[host]
        try:
            ipaddress.ip_address(host)
            ok = _public_ip(host)
        except ValueError:
            try:
                infos = await asyncio.get_running_loop().getaddrinfo(host, None, type=socket.SOCK_STREAM)
                ok = bool(infos) and all(_public_ip(info[4][0]) for info in infos)
            except OSError:
                ok = False
        self._dns[host] = ok
        return ok

    async def _robots_allows(self, url: str, company: str | None) -> bool | None:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if parts.hostname in API_HOSTS:
            return True
        lock = self._robots_locks.setdefault(origin, asyncio.Lock())
        async with lock:
            if origin not in self._robots:
                parser: RobotFileParser | None = RobotFileParser()
                if not self.budget.take(parts.hostname or "", None):
                    return None
                try:
                    r = await self.client.get(origin + "/robots.txt", follow_redirects=True)
                    if r.status_code in (401, 403):
                        parser.parse(["User-agent: *", "Disallow: /"])
                    elif r.status_code >= 400:
                        parser.parse([])
                    else:
                        parser.parse(r.text[:200_000].splitlines())
                except httpx.HTTPError:
                    parser = None  # unreachable host: treated as a network failure below
                self._robots[origin] = parser
        parser = self._robots[origin]
        if parser is None:
            return False
        return parser.can_fetch(USER_AGENT, url) and parser.can_fetch("Varde", url)

    async def get(self, url: str, *, company: str | None = None, params: dict | None = None,
                  headers: dict | None = None, method: str = "GET", body: Any = None,
                  accept_json: bool = False,
                  redact: Callable[[bytes], bytes] | None = None) -> Snapshot | FetchError:
        if params:
            url = str(httpx.URL(url, params=params))
        hops: list[str] = []
        current = url
        for _ in range(MAX_REDIRECTS + 1):
            parts = urlsplit(current)
            host = parts.hostname or ""
            if parts.scheme not in ("http", "https") or not host:
                return FetchError(current, "blocked_policy")
            if not await self._host_is_public(host):
                return FetchError(current, "dns_or_private_address")
            allowed = await self._robots_allows(current, company)
            if allowed is None:
                return FetchError(current, "budget")
            if not allowed:
                reason = "blocked_robots" if self._robots.get(f"{parts.scheme}://{parts.netloc}") else "network"
                return FetchError(current, reason)
            if not self.budget.take(host, company):
                return FetchError(current, "budget")
            response = await self._send(current, method, headers, body, accept_json, host)
            if isinstance(response, FetchError):
                return response
            if response.status_code in (301, 302, 303, 307, 308) and "location" in response.headers:
                hops.append(current)
                current = urljoin(current, response.headers["location"])
                if response.status_code == 303:
                    method, body = "GET", None
                continue
            return self._finish(url, current, response, hops, redact)
        return FetchError(url, "blocked_policy")

    async def _send(self, url: str, method: str, headers: dict | None, body: Any, accept_json: bool,
                    host: str) -> httpx.Response | FetchError:
        hdrs = dict(headers or {})
        if accept_json:
            hdrs.setdefault("Accept", "application/json")
        for attempt in range(2):
            try:
                async with self._sem(host):
                    async with self.client.stream(method, url, headers=hdrs,
                                                  json=body if isinstance(body, (dict, list)) else None) as r:
                        chunks: list[bytes] = []
                        size = 0
                        async for chunk in r.aiter_bytes():
                            size += len(chunk)
                            if size > MAX_BYTES:
                                break
                            chunks.append(chunk)
                        r._content = b"".join(chunks)  # noqa: SLF001 - keep the capped body
                if r.status_code in (429, 502, 503, 504) and attempt == 0:
                    await asyncio.sleep(1.5)
                    continue
                return r
            except httpx.TimeoutException:
                if attempt == 0:
                    continue
                return FetchError(url, "timeout")
            except httpx.HTTPError:
                if attempt == 0:
                    await asyncio.sleep(0.5)
                    continue
                return FetchError(url, "network")
        return FetchError(url, "network")

    def _finish(self, url: str, final_url: str, r: httpx.Response, hops: list[str],
                redact: Callable[[bytes], bytes] | None = None) -> Snapshot | FetchError:
        if r.status_code >= 400:
            return FetchError(final_url, f"http_{r.status_code}", r.status_code)
        content_type = r.headers.get("content-type", "")
        data = r.content or b""
        if redact is not None:
            data = redact(data)
        digest, path = self.store.put(data, content_type)
        try:
            text = data.decode(r.encoding or "utf-8", errors="replace")
        except LookupError:
            text = data.decode("utf-8", errors="replace")
        return Snapshot(url=url, final_url=final_url, status=r.status_code, retrieved_at=utc_now(),
                        sha256=digest, path=path, content_type=content_type, text=text, redirects=hops)
