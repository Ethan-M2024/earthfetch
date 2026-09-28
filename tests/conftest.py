import pytest


@pytest.fixture(autouse=True)
def fresh_naip_token(monkeypatch):
    # the NAIP SAS token is cached module-wide; a token cached by one test
    # (or a live run) would make a later mocked test skip its token request
    from earthfetch import naip

    monkeypatch.setitem(naip._token, "value", None)
    monkeypatch.setitem(naip._token, "expires", 0.0)
