"""Tests del dominio ``InstagramAccount``."""

from __future__ import annotations

import pytest

from streaming_bot.domain.meta.instagram_account import (
    InstagramAccount,
    InstagramAccountStatus,
)


class TestInstagramAccountInvariants:
    def test_new_starts_in_warming(self) -> None:
        account = InstagramAccount.new(
            username="lo_fi_drift",
            persona_id="p-001",
            artist_uri="catalog:artist:lumen-drift",
        )
        assert account.status is InstagramAccountStatus.WARMING
        assert account.is_postable is False

    def test_new_assigns_id(self) -> None:
        a = InstagramAccount.new(
            username="x",
            persona_id="p",
            artist_uri="catalog:artist:y",
        )
        assert a.id

    def test_empty_username_raises(self) -> None:
        with pytest.raises(ValueError, match="username"):
            InstagramAccount.new(
                username="",
                persona_id="p",
                artist_uri="catalog:artist:y",
            )

    def test_empty_persona_id_raises(self) -> None:
        with pytest.raises(ValueError, match="persona_id"):
            InstagramAccount.new(
                username="u",
                persona_id="",
                artist_uri="catalog:artist:y",
            )

    def test_empty_artist_uri_raises(self) -> None:
        with pytest.raises(ValueError, match="artist_uri"):
            InstagramAccount.new(
                username="u",
                persona_id="p",
                artist_uri="",
            )

    def test_default_device_fingerprint_is_empty_dict(self) -> None:
        a = InstagramAccount.new(
            username="u", persona_id="p", artist_uri="catalog:artist:y",
        )
        assert a.device_fingerprint == {}


class TestInstagramAccountTransitions:
    def test_mark_active_promotes(self) -> None:
        a = InstagramAccount.new(
            username="u", persona_id="p", artist_uri="catalog:artist:y",
        )
        a.mark_active()
        assert a.status is InstagramAccountStatus.ACTIVE
        assert a.is_postable is True

    def test_mark_challenge_records_reason(self) -> None:
        a = InstagramAccount.new(
            username="u", persona_id="p", artist_uri="catalog:artist:y",
        )
        a.mark_active()
        a.mark_challenge("recaptcha")
        assert a.status is InstagramAccountStatus.CHALLENGE
        assert "recaptcha" in a.notes
        assert a.is_postable is False

    def test_mark_banned(self) -> None:
        a = InstagramAccount.new(
            username="u", persona_id="p", artist_uri="catalog:artist:y",
        )
        a.mark_banned("ToS violation")
        assert a.status is InstagramAccountStatus.BANNED
        assert "ToS" in a.notes
        assert a.is_postable is False

    def test_record_login_sets_timestamp(self) -> None:
        a = InstagramAccount.new(
            username="u", persona_id="p", artist_uri="catalog:artist:y",
        )
        assert a.last_login_at is None
        a.record_login()
        assert a.last_login_at is not None

    def test_device_fingerprint_is_independent_copy(self) -> None:
        seed = {"device_id": "abc"}
        a = InstagramAccount.new(
            username="u",
            persona_id="p",
            artist_uri="catalog:artist:y",
            device_fingerprint=seed,
        )
        seed["device_id"] = "MUTATED"
        assert a.device_fingerprint == {"device_id": "abc"}
