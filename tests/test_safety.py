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

