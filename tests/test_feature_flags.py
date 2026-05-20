"""Tests for db/feature_flags.py."""

from __future__ import annotations

import pytest


@pytest.fixture()
def db(tmp_db):
    yield tmp_db[0]


# ── set_flag / get_flag ────────────────────────────────────────────────────────


def test_set_flag_creates_new_flag(db):
    from db.feature_flags import get_flag, set_flag

    set_flag("my_flag", enabled=True, rollout_pct=100)
    row = get_flag("my_flag")
    assert row is not None
    assert row["name"] == "my_flag"
    assert row["enabled"] == 1


def test_set_flag_updates_existing_flag(db):
    from db.feature_flags import get_flag, set_flag

    set_flag("flag_a", enabled=True, rollout_pct=100)
    set_flag("flag_a", enabled=False, rollout_pct=0)
    row = get_flag("flag_a")
    assert row is not None
    assert row["enabled"] == 0
    assert row["rollout_pct"] == 0


def test_get_flag_returns_none_for_missing(db):
    from db.feature_flags import get_flag

    assert get_flag("nonexistent_flag") is None


def test_set_flag_stores_description(db):
    from db.feature_flags import get_flag, set_flag

    set_flag("described_flag", description="My description")
    row = get_flag("described_flag")
    assert row is not None
    assert row["description"] == "My description"


def test_set_flag_stores_user_emails(db):
    from db.feature_flags import get_flag, set_flag

    set_flag("email_flag", user_emails="a@b.com,c@d.com")
    row = get_flag("email_flag")
    assert row is not None
    assert row["user_emails"] == "a@b.com,c@d.com"


# ── is_enabled ────────────────────────────────────────────────────────────────


def test_is_enabled_returns_false_for_missing_flag(db):
    from db.feature_flags import is_enabled

    assert is_enabled("does_not_exist") is False


def test_is_enabled_returns_false_when_disabled(db):
    from db.feature_flags import is_enabled, set_flag

    set_flag("disabled_flag", enabled=False, rollout_pct=100)
    assert is_enabled("disabled_flag") is False


def test_is_enabled_returns_true_when_pct_100(db):
    from db.feature_flags import is_enabled, set_flag

    set_flag("full_rollout", enabled=True, rollout_pct=100)
    assert is_enabled("full_rollout") is True


def test_is_enabled_returns_false_when_pct_0(db):
    from db.feature_flags import is_enabled, set_flag

    set_flag("zero_pct", enabled=True, rollout_pct=0)
    assert is_enabled("zero_pct") is False


def test_is_enabled_user_email_in_allowlist(db):
    from db.feature_flags import is_enabled, set_flag

    set_flag("allowlist_flag", enabled=True, rollout_pct=0, user_emails="allowed@test.com")
    assert is_enabled("allowlist_flag", user_email="allowed@test.com") is True


def test_is_enabled_user_email_not_in_allowlist(db):
    from db.feature_flags import is_enabled, set_flag

    set_flag("allowlist_flag2", enabled=True, rollout_pct=0, user_emails="other@test.com")
    assert is_enabled("allowlist_flag2", user_email="notlisted@test.com") is False


def test_is_enabled_email_case_insensitive(db):
    from db.feature_flags import is_enabled, set_flag

    set_flag("case_flag", enabled=True, rollout_pct=0, user_emails="User@Test.COM")
    assert is_enabled("case_flag", user_email="user@test.com") is True


def test_is_enabled_partial_rollout_deterministic(db):
    from db.feature_flags import is_enabled, set_flag

    set_flag("partial_flag", enabled=True, rollout_pct=50)
    # Same call must always return same result
    result1 = is_enabled("partial_flag", user_email="test@example.com")
    result2 = is_enabled("partial_flag", user_email="test@example.com")
    assert result1 == result2


def test_is_enabled_partial_rollout_without_email(db):
    from db.feature_flags import is_enabled, set_flag

    set_flag("partial_no_email", enabled=True, rollout_pct=50)
    # Without email, rollout_pct > 0 but < 100 → False (needs email for deterministic hash)
    assert is_enabled("partial_no_email") is False


# ── delete_flag ───────────────────────────────────────────────────────────────


def test_delete_flag_returns_true_when_existed(db):
    from db.feature_flags import delete_flag, set_flag

    set_flag("to_delete")
    assert delete_flag("to_delete") is True


def test_delete_flag_returns_false_when_missing(db):
    from db.feature_flags import delete_flag

    assert delete_flag("never_existed") is False


def test_delete_flag_removes_flag(db):
    from db.feature_flags import delete_flag, get_flag, set_flag

    set_flag("remove_me")
    delete_flag("remove_me")
    assert get_flag("remove_me") is None


# ── list_flags ────────────────────────────────────────────────────────────────


def test_list_flags_empty(db):
    from db.feature_flags import list_flags

    result = list_flags()
    assert isinstance(result, list)


def test_list_flags_returns_all(db):
    from db.feature_flags import list_flags, set_flag

    set_flag("flag_x")
    set_flag("flag_y")
    names = [f["name"] for f in list_flags()]
    assert "flag_x" in names
    assert "flag_y" in names


def test_list_flags_sorted_by_name(db):
    from db.feature_flags import list_flags, set_flag

    set_flag("zzz_flag")
    set_flag("aaa_flag")
    names = [f["name"] for f in list_flags()]
    aaa_idx = names.index("aaa_flag")
    zzz_idx = names.index("zzz_flag")
    assert aaa_idx < zzz_idx
