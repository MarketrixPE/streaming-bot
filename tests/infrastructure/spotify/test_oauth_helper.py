"""Tests para oauth_helper (solo unit-test de PKCE, no http.server real)."""

from __future__ import annotations

import base64
import hashlib

from streaming_bot.infrastructure.spotify.oauth_helper import _generate_pkce_pair


def test_generate_pkce_pair_creates_valid_s256() -> None:
    """_generate_pkce_pair() genera un code_verifier y code_challenge S256 válidos."""
    verifier, challenge = _generate_pkce_pair()

    assert len(verifier) >= 43
    assert len(verifier) <= 128

    expected_challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("utf-8")).digest())
        .decode("utf-8")
        .rstrip("=")
    )

    assert challenge == expected_challenge


def test_pkce_pair_is_url_safe() -> None:
    """El code_verifier y code_challenge son URL-safe (sin =, +, /)."""
    verifier, challenge = _generate_pkce_pair()

    assert "=" not in verifier
    assert "=" not in challenge
    assert "+" not in verifier
    assert "+" not in challenge
    assert "/" not in verifier
    assert "/" not in challenge
