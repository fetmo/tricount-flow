import pytest

from tricount_flow.config import Config, ConfigError


def make_cfg():
    cfg = Config(credentials_path="/tmp/creds.json")
    cfg.upsert("household", "https://tricount.com/tHOME", me="Moritz")
    cfg.upsert("trip", "https://tricount.com/tTRIP")
    return cfg


def test_upsert_sets_first_as_default():
    cfg = Config(credentials_path="/tmp/creds.json")
    cfg.upsert("household", "https://tricount.com/tHOME")
    assert cfg.default == "household"
    cfg.upsert("trip", "https://tricount.com/tTRIP")
    assert cfg.default == "household"  # unchanged


def test_set_default_and_set_me():
    cfg = make_cfg()
    cfg.set_default("trip")
    assert cfg.default == "trip"
    cfg.set_me("trip", "Anna")
    assert cfg.tricounts["trip"].me == "Anna"


def test_rename_updates_default_and_order():
    cfg = make_cfg()  # default = household
    cfg.rename("household", "home")
    assert "home" in cfg.tricounts and "household" not in cfg.tricounts
    assert cfg.default == "home"
    assert list(cfg.tricounts) == ["home", "trip"]  # order preserved


def test_rename_conflict():
    cfg = make_cfg()
    with pytest.raises(ConfigError):
        cfg.rename("trip", "household")


def test_remove_reassigns_default():
    cfg = make_cfg()  # default = household
    cfg.remove("household")
    assert cfg.default == "trip"
    cfg.remove("trip")
    assert cfg.default is None


def test_aliases_for_token_detects_duplicates():
    cfg = make_cfg()
    cfg.upsert("home2", "https://tricount.com/tHOME")  # same token as household
    dupes = cfg.aliases_for_token("tHOME", exclude="home2")
    assert dupes == ["household"]


def test_resolve_name_precedence(monkeypatch):
    cfg = make_cfg()  # default = household
    # explicit wins
    assert cfg.resolve_name("trip") == "trip"
    # env var beats default
    monkeypatch.setenv("TRICOUNT", "trip")
    assert cfg.resolve_name(None) == "trip"
    # explicit still beats env var
    assert cfg.resolve_name("household") == "household"
    monkeypatch.delenv("TRICOUNT")
    assert cfg.resolve_name(None) == "household"


def test_unknown_alias_errors():
    cfg = make_cfg()
    with pytest.raises(ConfigError):
        cfg.resolve_name("nope")
