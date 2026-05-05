"""Tests de `RatioTargets`: defaults 2026, factories por geo y genero."""

from __future__ import annotations

import pytest

from streaming_bot.application.strategies.ratio_targets import (
    DEFAULT_LIKE_RATE,
    DEFAULT_QUEUE_RATE,
    DEFAULT_SAVE_RATE,
    DEFAULT_SKIP_RATE,
    RatioTargets,
)
from streaming_bot.domain.persona import (
    BehaviorProbabilities,
    DeviceType,
    EngagementLevel,
    Persona,
    PersonaTraits,
    PlatformProfile,
    SessionPattern,
)
from streaming_bot.domain.persona import (
    MouseProfile as PersonaMouseProfile,
)
from streaming_bot.domain.persona import (
    TypingProfile as PersonaTypingProfile,
)
from streaming_bot.domain.value_objects import Country


def _make_persona(*, country: Country, genre: str | None = None) -> Persona:
    """Helper que construye una Persona minima (solo lo que el test necesita)."""
    genres: tuple[str, ...] = (genre,) if genre else ()
    traits = PersonaTraits(
        engagement_level=EngagementLevel.CASUAL,
        preferred_genres=genres,
        preferred_session_hour_local=(18, 23),
        device=DeviceType.DESKTOP_CHROME,
        platform=PlatformProfile.MACOS_DESKTOP,
        ui_language="es-ES",
        timezone="America/Lima",
        country=country,
        behaviors=BehaviorProbabilities(),
        typing=PersonaTypingProfile(),
        mouse=PersonaMouseProfile(),
        session=SessionPattern(),
    )
    return Persona(account_id="acc-test", traits=traits)


class TestDefaults:
    def test_default_uses_global_2026_anchors(self) -> None:
        targets = RatioTargets.default()
        assert targets.save_rate == DEFAULT_SAVE_RATE
        assert targets.skip_rate == DEFAULT_SKIP_RATE
        assert targets.queue_rate == DEFAULT_QUEUE_RATE
        assert targets.like_rate == DEFAULT_LIKE_RATE

    def test_constants_are_within_human_range(self) -> None:
        """Los anchors no deben acercarse a 1.0 (eso seria red flag puro)."""
        assert DEFAULT_SAVE_RATE < 0.10
        assert DEFAULT_SKIP_RATE < 0.50
        assert DEFAULT_QUEUE_RATE < 0.05
        assert DEFAULT_LIKE_RATE < 0.10

    def test_invalid_save_rate_raises(self) -> None:
        with pytest.raises(ValueError, match="save_rate"):
            RatioTargets(save_rate=1.5)

    def test_invalid_negative_skip_raises(self) -> None:
        with pytest.raises(ValueError, match="skip_rate"):
            RatioTargets(skip_rate=-0.01)


class TestForCountry:
    def test_latam_has_higher_engagement_than_us(self) -> None:
        latam = RatioTargets.for_country(Country.PE)
        anglo = RatioTargets.for_country(Country.US)
        assert latam.save_rate > anglo.save_rate
        assert latam.like_rate > anglo.like_rate
        assert latam.skip_rate < anglo.skip_rate

    def test_asia_has_lower_engagement(self) -> None:
        asia = RatioTargets.for_country(Country.JP)
        anglo = RatioTargets.for_country(Country.US)
        assert asia.save_rate < anglo.save_rate
        assert asia.like_rate < anglo.like_rate

    def test_anglo_returns_defaults(self) -> None:
        anglo = RatioTargets.for_country(Country.GB)
        assert anglo.save_rate == DEFAULT_SAVE_RATE
        assert anglo.skip_rate == DEFAULT_SKIP_RATE

    def test_unknown_bucket_returns_safe_fallback(self) -> None:
        # Un pais europeo no anglo: tiene su propio bucket.
        eu = RatioTargets.for_country(Country.DE)
        assert eu.save_rate < DEFAULT_SAVE_RATE
        assert eu.skip_rate >= DEFAULT_SKIP_RATE


class TestForGenre:
    def test_lofi_is_low_engagement(self) -> None:
        lofi = RatioTargets.for_genre("lo-fi")
        assert lofi.save_rate <= 0.03
        assert lofi.like_rate <= 0.05

    def test_lofi_lowercase_variants(self) -> None:
        for variant in ("lofi", "Lo-Fi Hip Hop", "LOFI BEATS", "lofi study"):
            target = RatioTargets.for_genre(variant)
            assert target.save_rate <= 0.03

    def test_pop_is_high_engagement(self) -> None:
        pop = RatioTargets.for_genre("pop")
        assert pop.save_rate >= 0.06
        assert pop.like_rate >= 0.08

    def test_reggaeton_is_high_engagement(self) -> None:
        reggaeton = RatioTargets.for_genre("reggaeton")
        defaults = RatioTargets.default()
        assert reggaeton.save_rate > defaults.save_rate
        assert reggaeton.like_rate > defaults.like_rate

    def test_unknown_genre_returns_defaults(self) -> None:
        unknown = RatioTargets.for_genre("klingon-sea-shanties")
        defaults = RatioTargets.default()
        assert unknown == defaults

    def test_empty_genre_returns_defaults(self) -> None:
        assert RatioTargets.for_genre("") == RatioTargets.default()


class TestCombined:
    def test_combined_is_average(self) -> None:
        country = RatioTargets(save_rate=0.06, skip_rate=0.40, queue_rate=0.020, like_rate=0.09)
        genre = RatioTargets(save_rate=0.02, skip_rate=0.30, queue_rate=0.008, like_rate=0.03)
        combined = RatioTargets.combined(country, genre)
        assert combined.save_rate == pytest.approx((0.06 + 0.02) / 2)
        assert combined.skip_rate == pytest.approx((0.40 + 0.30) / 2)
        assert combined.queue_rate == pytest.approx((0.020 + 0.008) / 2)
        assert combined.like_rate == pytest.approx((0.09 + 0.03) / 2)


class TestForPersona:
    def test_persona_with_genre_combines_dimensions(self) -> None:
        # PE + lo-fi: deberia quedar entre los dos buckets, no en defaults.
        persona = _make_persona(country=Country.PE, genre="lo-fi")
        targets = RatioTargets.for_persona(persona)
        only_country = RatioTargets.for_country(Country.PE)
        only_genre = RatioTargets.for_genre("lo-fi")
        assert targets.save_rate == pytest.approx(
            (only_country.save_rate + only_genre.save_rate) / 2,
        )
        assert targets.skip_rate == pytest.approx(
            (only_country.skip_rate + only_genre.skip_rate) / 2,
        )

    def test_persona_without_genres_uses_only_country(self) -> None:
        persona = _make_persona(country=Country.MX, genre=None)
        targets = RatioTargets.for_persona(persona)
        assert targets == RatioTargets.for_country(Country.MX)

    def test_persona_us_pop_higher_than_persona_us_lofi(self) -> None:
        pop_persona = _make_persona(country=Country.US, genre="pop")
        lofi_persona = _make_persona(country=Country.US, genre="lo-fi")
        pop_targets = RatioTargets.for_persona(pop_persona)
        lofi_targets = RatioTargets.for_persona(lofi_persona)
        assert pop_targets.save_rate > lofi_targets.save_rate
        assert pop_targets.like_rate > lofi_targets.like_rate


class TestOverrides:
    def test_with_overrides_returns_new_instance(self) -> None:
        base = RatioTargets.default()
        modified = base.with_overrides(save_rate=0.10)
        assert modified.save_rate == 0.10
        assert modified.skip_rate == base.skip_rate
        assert base.save_rate == DEFAULT_SAVE_RATE  # base no se muta

    def test_with_overrides_validates(self) -> None:
        with pytest.raises(ValueError, match="save_rate"):
            RatioTargets.default().with_overrides(save_rate=2.0)
