from varde.pipeline import stop_envelopes, validate
from varde.profile import Profile
from varde.web.site import candidates


def company(name: str, form: str = "AS", org: str = "979543883") -> Profile:
    p = Profile(org, "t")
    p.legal_name = name
    p.context["entity"] = {"navn": name, "organisasjonsnummer": org, "organisasjonsform": {"kode": form}}
    return p


def domains(p: Profile) -> list[str]:
    return [c.url for c in candidates(p, {}, [])]


def test_name_that_is_a_domain_becomes_a_candidate():
    assert "https://innregistrering.no/" in domains(company("INNREGISTRERING.NO AS"))


def test_first_distinctive_word_is_a_candidate():
    assert "https://kredah.no/" in domains(company("KREDAH INKASSO AS"))
    # a place or trade word on its own is not a brand
    assert "https://norsk.no/" not in domains(company("NORSK STEININDUSTRI AS"))


def test_sole_proprietor_names_are_never_guessed():
    assert domains(company("KARI NORDMANN TAKST", form="ENK")) == []


def test_stopped_run_still_has_one_envelope_per_input():
    done = company("DIPS AS")
    done.mark("identity", "available")
    half = company("HALF AS", org="923609016")
    orgs = ["979543883", "923609016", "123"]
    live = {"orgs": orgs, "profiles": {"979543883": done, "923609016": half}, "done": {"979543883"},
            "timing": {}, "previous": {}, "run_id": "t"}
    envs = stop_envelopes(live, "received SIGTERM")
    assert [e["organisation_number"] for e in envs] == orgs
    assert validate(envs, orgs)["passed"]
    half_env = envs[1]
    assert half_env["sections"]["web_presence"]["state"] == "failed"
    assert any("SIGTERM" in str(x) for x in half_env["errors"])
    assert envs[2]["run"]["terminal_status"] == "failed"


def test_tag_links_are_not_news():
    from varde.net import Snapshot
    from varde.web.site import _listing_news, view
    html = ("<html><body><div class='post'><a href='/blog?tag=fysisk+trening+hund'>fysisk trening hund</a> Aug 23, 2026</div>"
            "<div class='post'><a href='/blog/katt'>3 gode grunner til å sjekke katten</a> Aug 22, 2026</div></body></html>")
    snap = Snapshot(url="https://x.no/blog", final_url="https://x.no/blog", status=200, retrieved_at="2026-11-07T00:00:00Z",
                    sha256="0" * 64, path="s.html", content_type="text/html", text=html)
    titles = [x[0] for x in _listing_news(view(snap), None)]
    assert titles == ["3 gode grunner til å sjekke katten"]



def _declared_setup(page_html: str, name: str = "PERVACO AS", url: str = "https://www.pervaco.no/"):
    from varde.net import Snapshot
    from varde.web.site import Candidate
    p = company(name)
    p.context["entity"]["hjemmeside"] = "www.pervaco.no"
    body = '{"organisasjonsnummer":"979543883","navn":"' + name + '","hjemmeside":"www.pervaco.no"}'
    p.context["entity_snap"] = Snapshot(url="https://data.brreg.no/x", final_url="https://data.brreg.no/x", status=200,
                                        retrieved_at="2026-11-07T00:00:00Z", sha256="1" * 64, path="e.json",
                                        content_type="application/json", text=body)
    snap = Snapshot(url=url, final_url=url, status=200, retrieved_at="2026-11-07T00:00:00Z", sha256="2" * 64,
                    path="s.html", content_type="text/html", text=page_html)
    return p, Candidate(url, "registry_website"), snap


def test_declared_website_is_published_on_the_registers_word():
    from varde.web.site import _publish_declared
    p, cand, snap = _declared_setup("<html><title>Pervaco</title><body>" + "Rengjøring og service. " * 20 + "</body></html>")
    assert _publish_declared(p, cand, snap)
    site = p.published("official_website")[0]
    assert site["value"] == "pervaco.no" and site["match"]["method"] == "declared_in_register"
    assert not site["exclusive"]


def test_declared_manager_site_that_never_names_the_company_is_not_published():
    from varde.web.site import _publish_declared
    p, cand, snap = _declared_setup("<html><title>BATE</title><body>" + "Boligbyggelag. " * 20 + "Org.nr 946 450 197</body></html>",
                                    name="SAMEIET ST OLAV", url="https://www.bate.no/")
    assert not _publish_declared(p, cand, snap)


def test_domain_must_spell_the_name_without_an_org_number():
    from varde.web.site import domain_spells_name
    assert not domain_spells_name("https://crownstead.no/", "IDEN CAPITAL AS")
    assert not domain_spells_name("https://meieridammen.no/", "NORGESHUS AS")
    assert domain_spells_name("https://grelektro.no/", "GR ELEKTRO AS")
    assert domain_spells_name("https://7k.no/", "KONSULENTBYRÅET 7K AS")


def test_declared_site_without_the_name_is_not_published():
    from varde.web.site import _publish_declared
    p, cand, snap = _declared_setup("<html><title>Crownstead</title><body>" + "Digitale løsninger for lokale virksomheter. " * 10 + "</body></html>",
                                    name="IDEN CAPITAL AS", url="https://crownstead.no/")
    assert not _publish_declared(p, cand, snap)
