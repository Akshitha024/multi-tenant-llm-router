from __future__ import annotations

from pathlib import Path

from router.auth.keys import TenantStore

FIX = Path(__file__).parent / "fixtures"


def test_load_two_tenants() -> None:
    s = TenantStore()
    s.load(FIX / "tenants.yaml")
    assert {t.tenant_id for t in s.all()} == {"t1", "t2"}


def test_lookup_finds_t1() -> None:
    s = TenantStore()
    s.load(FIX / "tenants.yaml")
    t = s.lookup("secret-t1")
    assert t is not None
    assert t.tenant_id == "t1"
    assert "a3" in t.allowed_adapters


def test_lookup_rejects_wrong_key() -> None:
    s = TenantStore()
    s.load(FIX / "tenants.yaml")
    assert s.lookup("nope") is None
    assert s.lookup("") is None


def test_get_by_id() -> None:
    s = TenantStore()
    s.load(FIX / "tenants.yaml")
    t = s.get("t2")
    assert t is not None
    assert t.rate_limit_rps == 5.0
