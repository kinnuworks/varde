from varde.net import Snapshot
from varde.profile import Profile, json_object_bounds, json_span
from varde.refresh import diff
from varde.synthesis import validate
from varde.util import core_name, read_inputs, valid_orgnr
from varde.web.site import Candidate, _social, find_date, orgnr_mentions, prove, view


def snap(text: str, url: str = "https://example.no/") -> Snapshot:
    return Snapshot(url=url, final_url=url, status=200, retrieved_at="2026-10-17T00:00:00Z",
                    sha256="0" * 64, path="snapshots/00/x.html", content_type="text/html", text=text)


def entity_profile(org="979543883", name="DIPS AS", **rec) -> Profile:
    p = Profile(org, "t")
    p.legal_name = name
    p.context["entity"] = {"navn": name, "organisasjonsnummer": org, **rec}
    return p


def test_orgnr_checksum():
    assert valid_orgnr("979543883")
    assert valid_orgnr("923609016")
    assert not valid_orgnr("979543884")
    assert not valid_orgnr("12345678")


def test_json_span_is_exact_slice():
    text = '[{"journalnr":"1","x":{"sumDriftsinntekter":10.00}},{"journalnr":"2","x":{"sumDriftsinntekter":20.00}}]'
    start, end = json_object_bounds(text, '"journalnr":"2"')
    span = json_span(text, "sumDriftsinntekter", start=start, end=end)
    assert span == '"sumDriftsinntekter":20.00' and span in text


def test_orgnr_on_page_proves_site():
    p = entity_profile()
    html = "<html><body><h1>DIPS AS</h1>" + "<p>Helse og teknologi.</p>" * 20 + "<footer>Org.nr: 979 543 883</footer></body></html>"
    proof, reason = prove(p, view(snap(html)), Candidate("https://example.no/", "seed"))
    assert proof and proof.method == "orgnr_on_page" and proof.span in html


def test_other_orgnr_without_ours_is_rejected():
    p = entity_profile(telefon="75592000")
    html = "<html><body><h1>DIPS AS</h1>" + "<p>Tekst om firmaet.</p>" * 20 + "<p>Org.nr 923 609 016</p><p>75 59 20 00</p></body></html>"
    proof, reason = prove(p, view(snap(html)), Candidate("https://example.no/", "seed"))
    assert proof is None and "other organisation number" in reason


def test_parked_page_never_counts():
    p = entity_profile()
    html = "<html><body><h1>Domenet er til salgs</h1>" + "<p>DIPS AS 979 543 883</p>" * 2 + "x" * 200 + "</body></html>"
    proof, reason = prove(p, view(snap(html)), Candidate("https://example.no/", "seed"))
    assert proof is None


def test_name_alone_is_not_enough():
    p = entity_profile(name="NORDIC HOLDING AS")
    html = "<html><body><h1>Nordic Holding AS</h1>" + "<p>Vi leverer tjenester.</p>" * 20 + "</body></html>"
    proof, _ = prove(p, view(snap(html)), Candidate("https://nordicholding.no/", "name_derived"))
    assert proof is None


def test_social_normalisation():
    assert _social("https://www.linkedin.com/company/avm-valves-as/") == "linkedin.com/company/avm-valves-as"
    assert _social("https://www.facebook.com/sharer.php?u=x") is None
    assert _social("https://twitter.com/intent/tweet") is None
    assert _social("https://www.instagram.com/dips_as/") == "instagram.com/dips_as"


def test_dates():
    assert find_date("Publisert 12. oktober 2026 av redaksjonen")[0] == "2026-10-12"
    assert find_date("03.02.2025")[0] == "2025-02-03"


def test_inputs_never_drop(tmp_path):
    f = tmp_path / "b.txt"
    f.write_text("979543883\n979543883\nabc\n923609016\n")
    assert read_inputs(f) == ["979543883", "abc", "923609016"]


def test_summary_validator_rejects_unsupported_numbers():
    p = entity_profile()
    s = snap('{"antallAnsatte":351}')
    e = p.add_evidence(s, source_class="official_registry", span='"antallAnsatte":351', method="t", licence="x")
    c = p.add_claim("registered_employees", "identity", 351, [e])
    assert validate(p, {"text": "The register shows 351 employees.", "claim_ids": [c["id"]]})
    assert not validate(p, {"text": "The register shows 352 employees.", "claim_ids": [c["id"]]})


def test_refresh_is_idempotent_and_typed():
    def build(role_name):
        p = entity_profile()
        s = snap('{"navn":"' + role_name + '"}')
        e = p.add_evidence(s, source_class="official_registry", span='"navn":"' + role_name + '"', method="t", licence="x")
        p.add_claim("role", "leadership", {"role": "Daglig leder", "name": role_name}, [e])
        return p
    first = build("Kari Nordmann")
    env = {"run": {"run_id": "r1"}, "claims": first.claims, "evidence": first.evidence}
    same = build("Kari Nordmann")
    diff(same, env)
    assert same.changes == []
    other = build("Ola Nordmann")
    diff(other, env)
    assert {c["type"] for c in other.changes} == {"new_role", "ended_role"}
    assert all(c["previous"] is None or c["previous"]["evidence"] for c in other.changes)


def test_core_name():
    assert core_name("DIPS AS") == "dips"
    assert core_name("Norsk Hydro ASA") == "norsk hydro"


def test_directory_pages_never_prove_identity():
    p = entity_profile()
    rows = "".join(f"<li>Firma {i} AS, org.nr {n}</li>" for i, n in enumerate(["923609016", "984851006", "914778271"]))
    html = "<html><body><h1>Bransjeoversikt</h1>" + "<p>Liste over firmaer i bransjen.</p>" * 10 + "<ul>" + rows + "<li>DIPS AS, org.nr 979 543 883</li></ul></body></html>"
    proof, reason = prove(p, view(snap(html)), Candidate("https://katalog.no/", "search"))
    assert proof is None and "other organisation numbers" in reason
