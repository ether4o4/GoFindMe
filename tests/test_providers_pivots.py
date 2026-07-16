"""Zero-setup coverage: keyless sources and the keyless 'pivots' provider.

These guard the fix for the two 'nothing found' dead ends a fresh user hit:
  * a real-name search matched no source at all, and
  * LeakCheck's keyless public breach lookup was filtered out (requires_key).
"""
import pytest

from app import providers as prov
from app.validators import TARGET_TYPES


def test_leakcheck_is_keyless():
    # LeakCheck's public endpoint works with no key, so it must be selectable with
    # zero setup — this is what makes email/username/phone searches return breach
    # exposure on a fresh install and inside the phone app (no CLI tools there).
    assert prov.get_provider("leakcheck").requires_key is False


def test_pivots_registered_and_keyless():
    p = prov.get_provider("pivots")
    assert p is not None
    assert p.requires_key is False and p.vault_key is None


@pytest.mark.parametrize("ttype", [t for t in TARGET_TYPES if t != "image"])
def test_every_searchable_type_has_a_keyless_source(ttype):
    # Regression guard for the 'realname' dead end: with no tools and no API keys,
    # every type a user can search must still have at least one source that runs.
    keyless = [p.name for p in prov.providers_for_type(ttype) if not p.requires_key]
    assert keyless, f"{ttype} has no keyless source — it would return nothing on a fresh install"


async def test_pivots_realname_returns_find_and_optout_links():
    res = await prov.get_provider("pivots").lookup(None, None, "John Smith", "realname")
    assert res.ok
    assert res.summary["check_yourself"], "no self-lookup links"
    assert res.summary["opt_out_pages"], "no data-broker opt-out links"
    # the target is URL-encoded into the query links (never shell/host)
    assert any("John%20Smith" in u for u in res.summary["check_yourself"])
    assert all(u.startswith("https://") for u in res.summary["opt_out_pages"])


async def test_pivots_domain_returns_keyless_open_links():
    res = await prov.get_provider("pivots").lookup(None, None, "example.com", "domain")
    assert res.ok
    assert any("crt.sh" in u for u in res.summary["open_no_key"])


async def test_pivots_unknown_type_falls_back_to_a_link():
    # Never return an empty result — even an unmapped type gets a search link.
    res = await prov.get_provider("pivots").lookup(None, None, "whatever", "username")
    assert res.ok and res.summary.get("open_no_key")
