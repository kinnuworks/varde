"""Brønnøysundregistrene: entity, roles, sub-units, accounts and group structure.

Every fact here is keyed by the organisation number in the request URL, so it
carries no attribution risk. Spans quote the exact JSON pair from the saved
response. Role responses are saved with birth dates removed before hashing.
"""
from __future__ import annotations

import json
import re
from typing import Any

from ..net import Fetcher, FetchError, Snapshot
from ..profile import Profile, json_object_bounds, json_span

API = "https://data.brreg.no/enhetsregisteret/api"
ACCOUNTS = "https://data.brreg.no/regnskapsregisteret/regnskap"
LICENCE = "NLOD 2.0 (Brønnøysundregistrene)"
CLASS = "official_registry"

_BIRTH = re.compile(rb'"fodselsdato"\s*:\s*"\d{4}-\d{2}-\d{2}"\s*,?')


def _redact_birth_dates(data: bytes) -> bytes:
    cleaned = _BIRTH.sub(b"", data)
    return cleaned.replace(b",}", b"}")


def _ev(p: Profile, snap: Snapshot, span: str | None, method: str, note: str | None = None) -> str | None:
    return p.add_evidence(snap, source_class=CLASS, span=span, method=method, licence=LICENCE, note=note)


def _addr(a: dict | None) -> str | None:
    if not a:
        return None
    lines = [x for x in a.get("adresse") or [] if x]
    tail = " ".join(x for x in (a.get("postnummer"), a.get("poststed")) if x)
    parts = lines + ([tail] if tail else [])
    if a.get("landkode") and a.get("landkode") != "NO":
        parts.append(a.get("land") or a["landkode"])
    return ", ".join(parts) or None


async def entity(p: Profile, f: Fetcher) -> dict | None:
    org = p.organisation_number
    snap = await f.get(f"{API}/enheter/{org}", company=org, accept_json=True)
    if isinstance(snap, FetchError):
        if snap.status == 410:
            p.add_absence_evidence(snap.url, source_class=CLASS, method="brreg_entity_v1",
                                   note="Brønnøysund returns 410 Gone: the entity has been deleted from the register.")
            p.mark("identity", "not_available", "Entity deleted from Enhetsregisteret")
        p.error("brreg_entity", snap)
        p.mark("identity", snap.state, f"Enhetsregisteret lookup failed: {snap.reason}")
        return None
    rec = snap.json()
    p.context["entity"] = rec
    p.context["entity_snap"] = snap
    t = snap.text
    m = "brreg_entity_v1"
    p.legal_name = rec.get("navn")

    def claim(field_name: str, key: str, value: Any, *, raw: Any = None, label: str | None = None,
              as_of: str | None = None, extra: dict | None = None) -> None:
        if value in (None, "", [], {}):
            return
        span = json_span(t, key, raw if raw is not None else None)
        p.add_claim(field_name, "identity", value, [_ev(p, snap, span, m)], label=label, as_of=as_of,
                    match={"method": "orgnr_in_request", "detail": f"{API}/enheter/{org}"}, extra=extra)

    claim("legal_name", "navn", rec.get("navn"), raw=rec.get("navn"), label="Legal name")
    p.add_claim("organisation_number", "identity", org,
                [_ev(p, snap, json_span(t, "organisasjonsnummer", org), m)], label="Organisation number")
    form = rec.get("organisasjonsform") or {}
    if form.get("kode"):
        p.add_claim("legal_form", "identity", {"code": form.get("kode"), "description": form.get("beskrivelse")},
                    [_ev(p, snap, json_span(t, "beskrivelse", form.get("beskrivelse")), m)], label="Legal form")
    for n, key in enumerate(("naeringskode1", "naeringskode2", "naeringskode3"), 1):
        code = rec.get(key) or {}
        if code.get("kode"):
            p.add_claim("industry", "identity", {"code": code["kode"], "description": code.get("beskrivelse"), "rank": n},
                        [_ev(p, snap, json_span(t, key), m)], label="Industry (NACE)")
    if rec.get("forretningsadresse"):
        p.add_claim("registered_address", "identity", _addr(rec["forretningsadresse"]),
                    [_ev(p, snap, json_span(t, "forretningsadresse"), m)], label="Business address")
    if rec.get("postadresse"):
        p.add_claim("postal_address", "identity", _addr(rec["postadresse"]),
                    [_ev(p, snap, json_span(t, "postadresse"), m)], label="Postal address")
    if rec.get("harRegistrertAntallAnsatte") and rec.get("antallAnsatte") is not None:
        p.add_claim("registered_employees", "identity", rec["antallAnsatte"],
                    [_ev(p, snap, json_span(t, "antallAnsatte"), m)], label="Employees in the register",
                    as_of=rec.get("registreringsdatoAntallAnsatteEnhetsregisteret"))
    elif rec.get("harRegistrertAntallAnsatte") is False:
        p.mark_field("registered_employees", "identity", "not_available",
                     "The register shows no registered employee count for this entity.",
                     [_ev(p, snap, json_span(t, "harRegistrertAntallAnsatte"), m)])
    claim("founded", "stiftelsesdato", rec.get("stiftelsesdato"), raw=rec.get("stiftelsesdato"), label="Founded")
    claim("registered_date", "registreringsdatoEnhetsregisteret", rec.get("registreringsdatoEnhetsregisteret"),
          raw=rec.get("registreringsdatoEnhetsregisteret"), label="Registered in Enhetsregisteret")
    cap = rec.get("kapital") or {}
    if cap.get("belop") is not None:
        p.add_claim("share_capital", "identity",
                    {"amount": cap["belop"], "currency": cap.get("valuta"), "type": cap.get("type"),
                     "shares": cap.get("antallAksjer"), "since": cap.get("innfortDato")},
                    [_ev(p, snap, json_span(t, "kapital"), m)], label="Share capital")
    if rec.get("vedtektsfestetFormaal"):
        claim("statutory_purpose", "vedtektsfestetFormaal", " ".join(rec["vedtektsfestetFormaal"]),
              label="Purpose in the articles", as_of=rec.get("vedtektsdato"))
    if rec.get("aktivitet"):
        claim("registered_activity", "aktivitet", " ".join(rec["aktivitet"]), label="Registered activity")
    if rec.get("hjemmeside"):
        claim("registry_website", "hjemmeside", rec["hjemmeside"], raw=rec["hjemmeside"], label="Website in the register")
    if rec.get("telefon") or rec.get("mobil"):
        key = "telefon" if rec.get("telefon") else "mobil"
        claim("registry_phone", key, rec[key], raw=rec[key], label="Phone in the register")
    form_code = form.get("kode")
    if rec.get("epostadresse") and form_code not in ("ENK",):
        claim("registry_email", "epostadresse", rec["epostadresse"], raw=rec["epostadresse"], label="Email in the register")
    sector = rec.get("institusjonellSektorkode") or {}
    if sector.get("kode"):
        p.add_claim("institutional_sector", "identity", {"code": sector["kode"], "description": sector.get("beskrivelse")},
                    [_ev(p, snap, json_span(t, "institusjonellSektorkode"), m)], label="Institutional sector")
    for key, label in (("registrertIMvaregisteret", "Registered for VAT"),
                       ("registrertIForetaksregisteret", "In the Register of Business Enterprises"),
                       ("registrertIFrivillighetsregisteret", "In the Register of Non-Profit Organisations"),
                       ("registrertIStiftelsesregisteret", "In the Register of Foundations")):
        if key in rec:
            p.add_claim(f"register_{key}", "identity", bool(rec[key]), [_ev(p, snap, json_span(t, key), m)], label=label)
    status = []
    for key, label in (("konkurs", "Bankrupt"), ("underAvvikling", "Being wound up"),
                       ("underTvangsavviklingEllerTvangsopplosning", "Under compulsory dissolution")):
        if key in rec:
            p.add_claim(f"status_{key}", "identity", bool(rec[key]), [_ev(p, snap, json_span(t, key), m)], label=label)
            if rec[key]:
                status.append(label)
    for key, label in (("konkursdato", "Bankruptcy date"), ("underAvviklingDato", "Winding-up date"),
                       ("tvangsavvikletPgaManglendeSlettingDato", "Compulsory dissolution date")):
        if rec.get(key):
            claim(f"status_{key}", key, rec[key], raw=rec[key], label=label)
    p.context["status_flags"] = status
    if rec.get("historiskeNavn"):
        p.add_claim("former_names", "identity",
                    [{"name": h.get("navn"), "from": h.get("fraDato"), "to": h.get("tilDato")} for h in rec["historiskeNavn"]],
                    [_ev(p, snap, json_span(t, "historiskeNavn"), m)], label="Former names")
    if rec.get("sisteInnsendteAarsregnskap"):
        claim("latest_filed_accounts_year", "sisteInnsendteAarsregnskap", rec["sisteInnsendteAarsregnskap"],
              raw=rec["sisteInnsendteAarsregnskap"], label="Latest annual accounts submitted")
    if "erIKonsern" in rec:
        p.add_claim("in_group", "identity", bool(rec["erIKonsern"]), [_ev(p, snap, json_span(t, "erIKonsern"), m)],
                    label="Part of a group")
    if rec.get("overordnetEnhet"):
        claim("parent_unit", "overordnetEnhet", rec["overordnetEnhet"], raw=rec["overordnetEnhet"], label="Parent unit in the public sector")
    p.mark("identity", "available")
    return rec


ROLE_GROUPS = {"DAGL", "LEDE", "STYR", "REVI", "REGN", "KONT", "DTPR", "DTSO", "KOMP", "INNH", "FFØR", "BEST", "SAM", "EIKM", "KIRK"}


async def roles(p: Profile, f: Fetcher) -> None:
    org = p.organisation_number
    snap = await f.get(f"{API}/enheter/{org}/roller", company=org, accept_json=True, redact=_redact_birth_dates)
    if isinstance(snap, FetchError):
        p.error("brreg_roles", snap)
        p.mark_field("roles", "leadership", "not_available" if snap.state == "not_available" else snap.state,
                     f"Role lookup: {snap.reason}")
        return
    body = snap.json()
    t = snap.text
    m = "brreg_roles_v1"
    note = "Birth dates removed from the saved response before hashing."
    count = 0
    people: list[dict] = []
    for group in body.get("rollegrupper") or []:
        changed = group.get("sistEndret")
        for role in group.get("roller") or []:
            if role.get("avregistrert") or role.get("fratraadt"):
                continue
            rtype = role.get("type") or {}
            holder = None
            span = None
            if role.get("person"):
                person = role["person"]
                name = person.get("navn") or {}
                full = " ".join(x for x in (name.get("fornavn"), name.get("mellomnavn"), name.get("etternavn")) if x)
                holder = {"kind": "person", "name": full}
                if person.get("erDoed"):
                    holder["deceased"] = True
                span = json_span(t, "navn", name)
            elif role.get("enhet"):
                unit = role["enhet"]
                holder = {"kind": "entity", "name": " ".join(unit.get("navn") or []) if isinstance(unit.get("navn"), list) else unit.get("navn"),
                          "organisation_number": unit.get("organisasjonsnummer")}
                span = json_span(t, "organisasjonsnummer", unit.get("organisasjonsnummer"))
            if not holder:
                continue
            value = {"role": rtype.get("beskrivelse"), "role_code": rtype.get("kode"), **holder}
            ev = p.add_evidence(snap, source_class=CLASS, span=span, method=m, licence=LICENCE, note=note)
            if p.add_claim("role", "leadership", value, [ev], as_of=changed, label=rtype.get("beskrivelse"),
                           match={"method": "orgnr_in_request", "detail": f"{API}/enheter/{org}/roller"}):
                count += 1
                people.append(value)
    p.context["roles"] = people
    if count == 0:
        p.mark_field("roles", "leadership", "not_available", "The register lists no current roles.",
                     [p.add_absence_evidence(snap.final_url, source_class=CLASS, method=m,
                                             note="Role response has no active role holders.", snap=snap)])


async def subunits(p: Profile, f: Fetcher) -> None:
    org = p.organisation_number
    snap = await f.get(f"{API}/underenheter", params={"overordnetEnhet": org, "size": 100}, company=org, accept_json=True)
    if isinstance(snap, FetchError):
        p.error("brreg_subunits", snap)
        p.mark_field("workplace", "leadership", snap.state, f"Sub-unit lookup: {snap.reason}")
        return
    body = snap.json()
    units = (body.get("_embedded") or {}).get("underenheter") or []
    t = snap.text
    m = "brreg_subunits_v1"
    p.context["subunits"] = units
    for unit in units:
        sub_org = unit.get("organisasjonsnummer")
        bounds = json_object_bounds(t, f'"organisasjonsnummer":"{sub_org}"')
        start, end = bounds if bounds else (0, None)
        addr = _addr(unit.get("beliggenhetsadresse") or unit.get("postadresse"))
        value = {"name": unit.get("navn"), "organisation_number": sub_org, "address": addr,
                 "municipality": (unit.get("beliggenhetsadresse") or {}).get("kommune"),
                 "employees": unit.get("antallAnsatte") if unit.get("harRegistrertAntallAnsatte") else None,
                 "industry": (unit.get("naeringskode1") or {}).get("beskrivelse"),
                 "started": unit.get("oppstartsdato")}
        span = json_span(t, "beliggenhetsadresse", start=start, end=end) or json_span(t, "organisasjonsnummer", sub_org)
        p.add_claim("workplace", "leadership", value, [_ev(p, snap, span, m)], label="Registered workplace",
                    as_of=unit.get("registreringsdatoEnhetsregisteret"),
                    match={"method": "parent_orgnr_in_request", "detail": f"overordnetEnhet={org}"})
    total = (body.get("page") or {}).get("totalElements")
    if not units:
        p.mark_field("workplace", "leadership", "not_available", "No registered sub-units (workplaces).",
                     [p.add_absence_evidence(snap.final_url, source_class=CLASS, method=m,
                                             note="Sub-unit search returned no results.", snap=snap)])
    elif total and total > len(units):
        p.context["subunits_total"] = total


FIN_FIELDS = [
    ("revenue", "sumDriftsinntekter", "Total operating income"),
    ("sales_revenue", "salgsinntekter", "Sales revenue"),
    ("operating_result", "driftsresultat", "Operating result"),
    ("salary_costs", "loennskostnad", "Salary costs"),
    ("profit_before_tax", "ordinaertResultatFoerSkattekostnad", "Result before tax"),
    ("annual_result", "aarsresultat", "Annual result"),
    ("total_assets", "sumEiendeler", "Total assets"),
    ("cash", "sumBankinnskuddOgKontanter", "Bank deposits and cash"),
    ("equity", "sumEgenkapital", "Total equity"),
    ("total_debt", "sumGjeld", "Total debt"),
]


def _find_number(obj: Any, key: str) -> Any:
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == key and not isinstance(v, (dict, list)):
                return v
        for v in obj.values():
            found = _find_number(v, key)
            if found is not None:
                return found
    return None


async def accounts(p: Profile, f: Fetcher) -> None:
    org = p.organisation_number
    snap = await f.get(f"{ACCOUNTS}/{org}", company=org, accept_json=True)
    if isinstance(snap, FetchError):
        p.error("brreg_accounts", snap)
        if snap.status == 404:
            p.mark_field("annual_accounts", "financials", "not_available",
                         "Regnskapsregisteret returned no structured accounts for this entity.")
        elif snap.status == 500:
            p.mark_field("annual_accounts", "financials", "not_available",
                         "Regnskapsregisteret's open API does not cover this account format (banks and insurers).")
        else:
            p.mark_field("annual_accounts", "financials", snap.state, f"Accounts lookup: {snap.reason}")
        return
    try:
        years = snap.json()
    except ValueError:
        p.mark_field("annual_accounts", "financials", "failed", "Accounts response was not JSON.")
        return
    if not years:
        p.mark_field("annual_accounts", "financials", "not_available", "No structured annual accounts returned.",
                     [p.add_absence_evidence(snap.final_url, source_class=CLASS, method="brreg_accounts_v1",
                                             note="Empty list returned.", snap=snap)])
        return
    t = snap.text
    m = "brreg_accounts_v1"
    summary: list[dict] = []
    for year in years:
        journal = year.get("journalnr")
        bounds = json_object_bounds(t, f'"journalnr":"{journal}"') if journal else None
        start, end = bounds if bounds else (0, None)
        period = year.get("regnskapsperiode") or {}
        period_str = f"{period.get('fraDato')}/{period.get('tilDato')}"
        kind = year.get("regnskapstype")
        currency = year.get("valuta")
        row = {"period": period_str, "account_type": kind, "currency": currency, "figures": {}}
        for field_name, key, label in FIN_FIELDS:
            value = _find_number(year, key)
            if value is None:
                continue
            span = json_span(t, key, start=start, end=end)
            if not span:
                continue
            raw = span.split(":", 1)[1]
            claim = p.add_claim(
                field_name, "financials",
                {"amount": raw, "currency": currency, "account_type": kind, "period": period_str},
                [_ev(p, snap, span, m)], period=period_str, as_of=period.get("tilDato"),
                label=label, match={"method": "orgnr_in_request", "detail": f"{ACCOUNTS}/{org}"},
                extra={"journal_number": journal})
            if claim:
                row["figures"][field_name] = raw
        for flag, key in (("audited", "ikkeRevidertAarsregnskap"), ("audit_opted_out", "fravalgRevisjon")):
            v = _find_number(year, key)
            if v is not None:
                span = json_span(t, key, start=start, end=end)
                p.add_claim(f"accounts_{flag}", "financials",
                            {"value": (not v) if flag == "audited" else bool(v), "period": period_str, "account_type": kind},
                            [_ev(p, snap, span, m)], period=period_str,
                            label="Accounts audited" if flag == "audited" else "Audit opted out")
        summary.append(row)
    summary.sort(key=lambda r: (r["period"], r["account_type"] or ""))
    p.context["accounts"] = summary


async def group_structure(p: Profile, f: Fetcher) -> None:
    org = p.organisation_number
    rec = p.context.get("entity") or {}
    if not rec.get("erIKonsern"):
        return
    snap = await f.get(f"{API}/konsernstruktur/{org}", company=org, accept_json=True)
    if isinstance(snap, FetchError):
        if snap.status != 404:
            p.error("brreg_group", snap)
        return
    t = snap.text
    m = "brreg_group_v1"
    body = snap.json()

    added = 0

    def walk(node: Any) -> None:
        nonlocal added
        if isinstance(node, list):
            for v in node:
                walk(v)
            return
        if not isinstance(node, dict):
            return
        nr = node.get("organisasjonsnummer")
        if nr and nr != org and added < 60:
            parent = node.get("parentOrganisasjonsnummer")
            if parent == org:
                relation = "subsidiary"
            elif nr == (p.context.get("group_parent") or ""):
                relation = "parent"
            else:
                relation = "group company"
            link = node.get("knytningsform") or {}
            rel = {"organisation_number": nr, "name": node.get("navn"), "relation": relation,
                   "link": link.get("beskrivelse"), "ownership_basis": node.get("grunnlag"),
                   "level": node.get("nivaa"), "parent_organisation_number": parent, "since": node.get("dato")}
            bounds = json_object_bounds(t, f'"organisasjonsnummer":"{nr}"')
            span = json_span(t, "organisasjonsnummer", nr, start=bounds[0], end=bounds[1]) if bounds else None
            if p.add_claim("group_relation", "identity", rel, [_ev(p, snap, span, m)], label="Group company",
                           as_of=node.get("dato"),
                           match={"method": "orgnr_in_request", "detail": f"{API}/konsernstruktur/{org}"}):
                added += 1
        if nr == org and node.get("parentOrganisasjonsnummer"):
            p.context["group_parent"] = node["parentOrganisasjonsnummer"]
        for v in node.values():
            walk(v)

    def find_parent(node: Any) -> None:
        if isinstance(node, list):
            for v in node:
                find_parent(v)
        elif isinstance(node, dict):
            if node.get("organisasjonsnummer") == org and node.get("parentOrganisasjonsnummer"):
                p.context["group_parent"] = node["parentOrganisasjonsnummer"]
            for v in node.values():
                find_parent(v)

    find_parent(body)
    walk(body)


async def held_roles(p: Profile, f: Fetcher) -> None:
    """Roles this entity holds in other entities (partner, owner, board member)."""
    org = p.organisation_number
    snap = await f.get(f"{API}/roller/enheter/{org}/juridiskeroller", company=org, accept_json=True)
    if isinstance(snap, FetchError):
        return
    try:
        body = snap.json()
    except ValueError:
        return
    t = snap.text
    m = "brreg_held_roles_v1"
    added = 0
    for unit in (body.get("enheter") or [])[:40]:
        nr = unit.get("organisasjonsnummer")
        if not nr:
            continue
        bounds = json_object_bounds(t, f'"organisasjonsnummer":"{nr}"')
        for role in unit.get("roller") or []:
            if role.get("avregistrert"):
                continue
            rtype = role.get("type") or {}
            value = {"organisation_number": nr, "name": unit.get("navn"), "role": rtype.get("beskrivelse"),
                     "role_code": rtype.get("kode"), "share": role.get("ansvarsandel")}
            span = json_span(t, "organisasjonsnummer", nr, start=bounds[0], end=bounds[1]) if bounds else None
            if p.add_claim("role_in_other_entity", "identity", value, [_ev(p, snap, span, m)],
                           label="Role held in another entity",
                           match={"method": "orgnr_in_request", "detail": f"{API}/roller/enheter/{org}/juridiskeroller"}):
                added += 1


async def batch_names(fetcher: Fetcher, orgs: list[str]) -> dict[str, str]:
    """Legal names for a batch, 100 per request (used only to pre-select NAV ads)."""
    out: dict[str, str] = {}
    for i in range(0, len(orgs), 100):
        chunk = orgs[i:i + 100]
        snap = await fetcher.get(f"{API}/enheter", params={"organisasjonsnummer": ",".join(chunk), "size": 100},
                                 accept_json=True)
        if isinstance(snap, FetchError):
            continue
        for rec in (snap.json().get("_embedded") or {}).get("enheter") or []:
            out[rec.get("organisasjonsnummer")] = rec.get("navn") or ""
    return out


async def update_feed(fetcher: Fetcher, orgs: list[str], since: str) -> tuple[Snapshot | None, dict[str, list[dict]]]:
    """Dated registry changes for a batch, with JSON-Patch diffs (one request per 100 numbers)."""
    out: dict[str, list[dict]] = {}
    last: Snapshot | None = None
    for i in range(0, len(orgs), 100):
        chunk = orgs[i:i + 100]
        snap = await fetcher.get(f"{API}/oppdateringer/enheter",
                                 params={"dato": since, "organisasjonsnummer": ",".join(chunk),
                                         "includeChanges": "true", "size": 1000}, accept_json=True)
        if isinstance(snap, FetchError):
            continue
        last = snap
        try:
            body = snap.json()
        except ValueError:
            continue
        for upd in (body.get("_embedded") or {}).get("oppdaterteEnheter") or []:
            nr = upd.get("organisasjonsnummer")
            out.setdefault(nr, []).append({"update": upd, "snap": snap})
    return last, out


FIELD_EN = {
    "antallAnsatte": "employees", "navn": "name", "forretningsadresse": "business address", "postadresse": "postal address",
    "hjemmeside": "website", "epostadresse": "email", "telefon": "phone", "mobil": "mobile", "naeringskode1": "industry code",
    "organisasjonsform": "legal form", "kapital": "share capital", "konkurs": "bankruptcy flag",
    "underAvvikling": "winding-up flag", "sisteInnsendteAarsregnskap": "latest filed accounts year",
    "registreringsdatoAntallAnsatteEnhetsregisteret": "employee count registration date",
    "registreringsdatoAntallAnsatteNAVAaregisteret": "employee count date (NAV Aa-register)",
    "vedtektsdato": "articles date", "vedtektsfestetFormaal": "statutory purpose", "aktivitet": "registered activity",
    "registrertIMvaregisteret": "VAT registration", "institusjonellSektorkode": "institutional sector",
}


def feed_events(p: Profile, items: list[dict]) -> None:
    m = "brreg_update_feed_v1"
    items = sorted(items, key=lambda i: i["update"].get("dato") or "", reverse=True)[:12]
    for item in items:
        upd, snap = item["update"], item["snap"]
        uid = upd.get("oppdateringsid")
        bounds = json_object_bounds(snap.text, f'"oppdateringsid":{uid}') if uid is not None else None
        start, end = bounds if bounds else (0, None)
        span = json_span(snap.text, "dato", upd.get("dato"), start=start, end=end)
        changes = [c for c in (upd.get("endringer") or []) if isinstance(c, dict)]
        paths = sorted({re.sub(r"/\d+", "", c.get("path", "")).strip("/") for c in changes if c.get("path")})
        details = []
        for c in changes:
            path = c.get("path", "")
            v = c.get("value")
            if c.get("op") in ("replace", "add") and isinstance(v, (str, int, float, bool)) and path.count("/") <= 3:
                details.append({"field": FIELD_EN.get(path.strip("/").split("/")[0], path.strip("/")), "path": path, "new_value": v})
        value = {"date": upd.get("dato"), "type": upd.get("endringstype"), "changed_fields": paths[:20],
                 "changes": details[:8]}
        ev = p.add_evidence(snap, source_class=CLASS, span=span, method=m, licence=LICENCE)
        p.add_claim("registry_update", "activity", value, [ev], as_of=(upd.get("dato") or "")[:10],
                    label="Registry update", match={"method": "orgnr_in_feed_record", "detail": "oppdateringer/enheter"})
