# Varde

Varde researches Norwegian companies from their organisation numbers. For each number it returns one profile in which every published fact carries its source URL, the time it was retrieved, a SHA-256 of the saved response, the exact quoted text and the method that tied it to that organisation number. What it cannot find or cannot prove is marked with an explicit state, never as zero.

A varde is the stone cairn that marks a trail in the Norwegian mountains.

## Run it

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync --frozen
uv run --frozen varde run --organisations batch.jsonl --output out/envelopes.jsonl
```

`batch.jsonl` can be JSONL rows (`{"organisation_number": "..."}`, the public universe format works as is), a JSON list, or plain text with one number per line. Every distinct input gets exactly one envelope, including invalid numbers, deleted entities and companies where every source failed.

The Signalpost starter flags are accepted, so a harness written for the starter kit can call Varde unchanged:

```bash
uv run --frozen varde run --organisations smoke/companies.jsonl --bulk brreg-enheter.csv \
  --profiles-output out/profiles.jsonl --output out/envelopes.jsonl \
  --report out/run-report.json --run-id smoke-001 --expected-count 100
```

`--bulk`, `--workers`, `--resume`, `--checkpoint-every` and `--modules` are accepted and ignored.

Other options: `--previous <envelopes.jsonl>` diffs against an earlier run; `--state-dir <dir>` keeps run history and diffs against the latest run automatically; `--max-requests`, `--time-budget` (seconds, default 2400), `--per-company-requests` (default 40) and `--concurrency` (default 24) set the budgets. The same budgets can be set with `VARDE_MAX_REQUESTS`, `VARDE_TIME_BUDGET`, `VARDE_PER_COMPANY` and `VARDE_CONCURRENCY`.

## Output

Written next to `--output`:

| File | Contents |
|---|---|
| `envelopes.jsonl` | One terminal envelope per input (the scored output) |
| `profiles.jsonl` | The same facts flattened for reading |
| `run-report.json` | Runtime, requests by host, p50/p95 per company, coverage by field family, contract checks |
| `report.html` | A self-contained report to search, compare and verify profiles; works offline and on a phone |
| `snapshots/` | Every response that backs a claim, named by its SHA-256 |

An envelope holds `legal_name`, seven `sections` (identity and public brand, latest accounts and history, leadership and workplaces, verified website and company-owned profiles, hiring and dated activity, evidence, refresh), `claims`, `evidence`, a cited `summary` with `unknowns`, `changes` since the previous run, `errors` and `operations`.

```json
{"id": "c41", "field": "official_website", "section": "web_presence", "value": "avm.no",
 "availability": "available", "confidence": 0.99, "evidence_ids": ["e52"],
 "match": {"method": "orgnr_on_page", "detail": "organisation number 990764522 printed on https://avm.no/", "candidate_source": "registry_website"},
 "url": "https://avm.no/", "exclusive": true}
{"id": "e52", "source_url": "https://avm.no/", "source_class": "company_owned", "retrieved_at": "2026-10-17T08:02:51Z",
 "content_sha256": "…", "snapshot_path": "snapshots/3f/3f….html", "claim_span": "Org nr: 990 764 522",
 "span_exact": true, "extraction_method": "website_identity_v1"}
```

Availability states: `available`, `not_available` (checked, nothing there), `blocked` (robots.txt or the source refused), `not_applicable`, `ambiguous` (found something but could not prove it belongs to this company), `failed` (source error, timeout or budget). Every `available` claim has at least one evidence record whose `claim_span` appears verbatim in the saved snapshot.

Dated register events (founding, registration, articles, former names, filings, employee and address changes) are published as `dated_activity` claims in the form `title (YYYY-MM-DD)`, separate from `dated_news`, which only holds items the company published itself.

Value shapes in the external families: `official_website` is the registered domain (full address in `url`), `social_profile` is `platform.com/handle` in lower case without scheme (original link in `url`), `hiring_signal` is a careers page, job board or job posting URL, and `dated_news` is `title (datetime)` with the source's own date.

## Sources

| Source | Facts | Tie to the organisation number | Licence |
|---|---|---|---|
| Enhetsregisteret API | Name, legal form, industry codes, addresses, registered employees, founding and registration dates, share capital, purpose and activity, website, phone and email in the register, VAT and register memberships, status flags, former names, group membership | Organisation number in the request URL | NLOD 2.0 |
| Roles, sub-units, group structure, roles held in other entities | General manager, board, auditor, accountant; registered workplaces with addresses; parents and subsidiaries with ownership basis; partner shares in other entities | Organisation number in the request URL | NLOD 2.0 |
| Update feed (`/oppdateringer/enheter`) | Dated registry changes over the last 12 months with the fields that changed, each also published as a `dated_activity` event (for example "Employee count updated to 351 (2026-10-14)") quoting the exact change record; dates are given as the calendar day in Norway | Organisation number filter on the feed | NLOD 2.0 |
| Regnskapsregisteret API | Filed accounts for up to three years: operating income, sales, operating result, salary costs, result before tax, annual result, assets, cash, equity, debt, audit flags | Organisation number in the request URL | NLOD 2.0 |
| NAV job feed | Active job ads: title, place, published and expiry dates | Employer organisation number in the ad (workplace numbers mapped to the parent) | NAV public feed terms |
| GLEIF | LEI, status, renewal dates | `registeredAs` equals the organisation number | CC0 |
| Wikidata | Item, ISIN; website and social accounts used only when the website matches the one Varde verified | Property P2333 equals the organisation number | CC0 |
| TED | EU procurement notices won (single-winner notices only, since the identifier list can include every tenderer) or published as buyer (five buyers or fewer) | Winner or buyer identifier equals the organisation number | Free reuse |
| Doffin (when `DOFFIN_API_KEY` is set) | Norwegian procurement notices published by the company as buyer (joint qualification schemes with many buyers are skipped) | Buyer `organizationId` equals the organisation number | Doffin public API terms |
| The company's own website | Official website, description, social profiles it links to, careers pages and job boards it links to, job postings in its structured data, dated news from its feeds and news pages | Proof on the site itself (below) | Company-owned pages, robots.txt obeyed |

Not used: aggregators whose terms forbid automated copying (Proff, Forvalt, 1881, Gule Sider, Purehelp), search-engine result pages, Brønnøysund announcement pages (robots.txt disallows them), Norid holder data (not public), and any scraping of LinkedIn, Meta, Glassdoor or Indeed. Social profiles come only from links on a verified company site or from a Wikidata item whose website matches it.

## How a website is proven

Candidates come from the register's website field, the register's email domain, Wikidata, NAV employer homepages, the declared seed cache and a domain derived from a distinctive legal name. None of these is evidence. A candidate is fetched live and published only when the site itself shows one of:

1. our organisation number (the strongest proof, and the most common);
2. the registry phone or email together with the legal name;
3. the legal name on the website the register declares, for distinctive names;
4. the legal name with the full registered street address and postcode.

A page that names a different organisation number without ours is rejected, and so is any page listing three or more other organisation numbers (directories, supplier and client lists), even when ours is among them. Parked, for-sale, placeholder and empty pages never count. If the site is not exclusive to the company (another organisation number appears on it), only the website itself is published and the facts derived from it are withheld as `ambiguous`.

## Refresh

Pass `--previous` or `--state-dir`. Claims have stable keys (field plus value), so a rerun against unchanged sources produces no changes. Changes are typed (`new_role`, `ended_role`, `changed_address`, `new_filing`, `new_job`, `closed_job`, `new_location`, `changed_website`, `new_public_record`, and more), flagged as material or not, and carry the previous value with its original evidence next to the current claim. When a source fails on a rerun, the last supported value is carried forward with its original evidence and a note.

## Summary

Each profile has a short summary in which every sentence lists the claim ids it rests on. A validator drops any sentence containing a number or date that its cited claims do not contain. Financial figures are copied as filed, with currency, period and account type; Varde never computes, converts or estimates a figure. The `unknowns` list states what was checked and not found, and why.

A model can write the summary instead of the template when `VARDE_LLM_PROVIDER` (`anthropic` or `openai`), `VARDE_MODEL` and the provider's API key are set. The model sees only this company's published claims, never raw pages, and never decides identity. Its sentences must cite claim ids, keep figures exactly as filed and pass the same validator; if fewer than three sentences pass, the template is used. Without these variables the run makes no model calls.

## Budget and cost

All requests go through one client with a batch request cap, a per-company cap, a wall-clock budget, per-host concurrency limits, robots.txt checks on every redirect hop and refusal of private or loopback addresses. Batch sources (GLEIF, Wikidata, TED, the update feed) use one request per chunk of companies. A 100-company random sample takes about 20 seconds and 600 requests.

| Item | Cost |
|---|---|
| Language model | none by default; optional summary writer, about one short call per company |
| APIs | open public APIs, no keys required |
| Expected cost per official run | $0 |

## Declared caches

| File | Contents | Rebuild |
|---|---|---|
| `src/varde/data/nav_index.json.gz` | Active NAV job ads by employer organisation number, with the feed cursor. At run time Varde reads the feed from that cursor to its live end, drops ads that closed, adds new ads for batch companies, and re-fetches every matched ad; only active ads are published | `scripts/build_nav_index.py` |
| `src/varde/data/nace_en.json` | English names of industry codes from Statistics Norway's Klass API (classification 6), CC BY 4.0 | `curl "https://data.ssb.no/api/klass/v1/classifications/6/codes.json?from=2025-01-01&language=en"` |
| `src/varde/data/website_seeds.json.gz` | Candidate website domains by organisation number, with a source tag per domain. Only organisation number, domain and tag are stored | `scripts/crawl_candidates.py`, `scripts/search_candidates.py`, then `scripts/build_website_seeds.py` |

How the website seeds are built. A polite crawl (robots.txt obeyed, front page plus at most one contact or legal page, one request at a time per host, user agent `VardeCacheBuilder/1.0`) covered the `.no` hosts in three Common Crawl indexes (CC-MAIN-2026-30, -34, -39, used under the Common Crawl terms of use), the websites and email domains the register lists for universe companies, and domains derived from distinctive legal names. From each page it kept only identifiers: labelled organisation numbers, phone numbers and email addresses. A domain becomes a candidate when it prints the company's organisation number, or shows a phone or email the register lists for exactly that one entity, or is the email domain the register lists for the company. Pages printing more than four organisation numbers are dropped. For companies with ten or more employees and no website in the register, a search API was queried once with the legal name and town; result domains carrying a distinctive part of the name were kept as candidates, without titles or snippets. Seeds are candidates only: the run fetches each one live and publishes it only with proof on the site itself.

## Tests

```bash
uv run --extra dev pytest -q
```

## Licence

Code: MIT. Data from Brønnøysundregistrene is used under the Norwegian Licence for Open Government Data (NLOD 2.0). GLEIF and Wikidata data are CC0. TED notices may be reused freely. Saved snapshots are third-party content kept only as evidence for published claims.
