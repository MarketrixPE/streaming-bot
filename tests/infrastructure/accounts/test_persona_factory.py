"""Tests para BrowserforgePersonaFactory."""

from __future__ import annotations

from streaming_bot.domain.persona import EngagementLevel
from streaming_bot.domain.value_objects import Country
from streaming_bot.infrastructure.accounts.persona_factory import (
    BrowserforgePersonaFactory,
)


class TestBrowserforgePersonaFactory:
    """Tests de BrowserforgePersonaFactory con seed para determinismo."""

    def test_for_country_deterministic_with_seed(self) -> None:
        """Verifica que con seed fijo, genera la misma persona."""
        factory1 = BrowserforgePersonaFactory(rng_seed=42)
        factory2 = BrowserforgePersonaFactory(rng_seed=42)

        persona1 = factory1.for_country(country=Country.PE, account_id="acc1")
        persona2 = factory2.for_country(country=Country.PE, account_id="acc1")

        assert persona1.traits.engagement_level == persona2.traits.engagement_level
        assert persona1.traits.preferred_genres == persona2.traits.preferred_genres
        assert persona1.traits.device == persona2.traits.device
        assert persona1.traits.platform == persona2.traits.platform

    def test_for_country_maps_correctly(self) -> None:
        """Verifica que el país se mapea correctamente a timezone y language."""
        factory = BrowserforgePersonaFactory(rng_seed=100)

        persona_pe = factory.for_country(country=Country.PE, account_id="acc1")
        assert persona_pe.traits.country == Country.PE
        assert persona_pe.traits.timezone == "America/Lima"
        assert persona_pe.traits.ui_language == "es-PE"

        persona_mx = factory.for_country(country=Country.MX, account_id="acc2")
        assert persona_mx.traits.country == Country.MX
        assert persona_mx.traits.timezone == "America/Mexico_City"
        assert persona_mx.traits.ui_language == "es-MX"

        persona_es = factory.for_country(country=Country.ES, account_id="acc3")
        assert persona_es.traits.country == Country.ES
        assert persona_es.traits.timezone == "Europe/Madrid"
        assert persona_es.traits.ui_language == "es-ES"

        persona_us = factory.for_country(country=Country.US, account_id="acc4")
        assert persona_us.traits.country == Country.US
        assert persona_us.traits.timezone == "America/New_York"
        assert persona_us.traits.ui_language == "en-US"

    def test_engagement_level_distribution(self) -> None:
        """Verifica que los niveles de engagement se distribuyen según pesos.

        Con suficientes muestras, deberíamos ver:
        - LURKER ~30%
        - CASUAL ~50%
        - ENGAGED ~18%
        - FANATIC ~2%
        """
        factory = BrowserforgePersonaFactory(rng_seed=200)
        samples = 1000
        counts = dict.fromkeys(EngagementLevel, 0)

        for i in range(samples):
            persona = factory.for_country(country=Country.PE, account_id=f"acc{i}")
            counts[persona.traits.engagement_level] += 1

        # Verificar que hay suficiente CASUAL (debería ser el más común)
        assert counts[EngagementLevel.CASUAL] > counts[EngagementLevel.LURKER]
        assert counts[EngagementLevel.CASUAL] > counts[EngagementLevel.ENGAGED]
        assert counts[EngagementLevel.CASUAL] > counts[EngagementLevel.FANATIC]

        # Verificar que FANATIC es el menos común
        assert counts[EngagementLevel.FANATIC] < counts[EngagementLevel.ENGAGED]

    def test_preferred_genres_count(self) -> None:
        """Verifica que preferred_genres tiene entre 2 y 4 géneros."""
        factory = BrowserforgePersonaFactory(rng_seed=300)

        for i in range(20):
            persona = factory.for_country(country=Country.PE, account_id=f"acc{i}")
            assert 2 <= len(persona.traits.preferred_genres) <= 4

    def test_typing_profile_wpm_variation(self) -> None:
        """Verifica que avg_wpm tiene variación (muestreado de normal)."""
        factory = BrowserforgePersonaFactory(rng_seed=400)

        wpms = [
            factory.for_country(country=Country.PE, account_id=f"acc{i}").traits.typing.avg_wpm
            for i in range(50)
        ]

        # Debe haber variación (no todos iguales)
        assert len(set(wpms)) > 10
        # Debe estar en rango razonable (30-120)
        assert all(30 <= wpm <= 120 for wpm in wpms)

    def test_session_hour_patterns(self) -> None:
        """Verifica que preferred_session_hour_local tiene patrones válidos."""
        factory = BrowserforgePersonaFactory(rng_seed=500)

        patterns = set()
        for i in range(50):
            persona = factory.for_country(country=Country.PE, account_id=f"acc{i}")
            patterns.add(persona.traits.preferred_session_hour_local)

        # Deberíamos ver los 4 patrones: morning, midday, evening, night
        assert len(patterns) >= 3  # Al menos 3 patrones diferentes

    def test_persona_memory_initialized_empty(self) -> None:
        """Verifica que la memoria se inicializa vacía."""
        factory = BrowserforgePersonaFactory(rng_seed=600)
        persona = factory.for_country(country=Country.PE, account_id="acc1")

        assert len(persona.memory.liked_songs) == 0
        assert len(persona.memory.saved_songs) == 0
        assert len(persona.memory.followed_artists) == 0
        assert persona.memory.total_streams == 0
