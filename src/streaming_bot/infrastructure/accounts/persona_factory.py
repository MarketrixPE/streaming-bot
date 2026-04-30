"""Factory de Personas coherentes con el país del proxy/SIM."""

from __future__ import annotations

import random

from streaming_bot.domain.persona import (
    BehaviorProbabilities,
    DeviceType,
    EngagementLevel,
    MouseProfile,
    Persona,
    PersonaMemory,
    PersonaTraits,
    PlatformProfile,
    SessionPattern,
    TypingProfile,
)
from streaming_bot.domain.value_objects import Country


class BrowserforgePersonaFactory:
    """Genera personas coherentes con país, dispositivo, y engagement level.

    Usa browserforge para inspirar valores de UA/browser, pero construye
    las Personas con dataclasses del dominio.
    """

    def __init__(self, *, rng_seed: int | None = None) -> None:
        """Inicializa el factory con seed opcional para determinismo en tests."""
        self._rng = random.Random(rng_seed)  # noqa: S311

    def for_country(
        self,
        *,
        country: Country,
        account_id: str,
    ) -> Persona:
        """Genera una Persona coherente con el país especificado."""
        # Mapear país a timezone, ui_language, locale_hint
        tz, ui_lang, _locale = self._map_country(country)

        # Samplear engagement level con pesos
        engagement = self._rng.choices(
            population=[
                EngagementLevel.LURKER,
                EngagementLevel.CASUAL,
                EngagementLevel.ENGAGED,
                EngagementLevel.FANATIC,
            ],
            weights=[30, 50, 18, 2],
        )[0]

        # Samplear device type
        device = self._rng.choices(
            population=[
                DeviceType.DESKTOP_CHROME,
                DeviceType.DESKTOP_FIREFOX,
                DeviceType.DESKTOP_EDGE,
            ],
            weights=[70, 20, 10],
        )[0]

        # Samplear platform
        platform = self._rng.choices(
            population=[
                PlatformProfile.WINDOWS_DESKTOP,
                PlatformProfile.MACOS_DESKTOP,
                PlatformProfile.LINUX_DESKTOP,
            ],
            weights=[65, 25, 10],
        )[0]

        # Samplear preferred_session_hour_local (4 patrones)
        pattern = self._rng.choice(["morning", "midday", "evening", "night"])
        session_hour = self._map_session_pattern(pattern)

        # Samplear preferred_genres (2-4 géneros)
        all_genres = [
            "reggaeton",
            "trap latino",
            "latin pop",
            "urbano latino",
            "dembow",
            "perreo",
            "r&b latino",
            "bachata",
            "cumbia",
        ]
        num_genres = self._rng.randint(2, 4)
        genres = tuple(self._rng.sample(all_genres, num_genres))

        # Behaviors
        behaviors = BehaviorProbabilities.for_engagement_level(engagement)

        # Typing profile con avg_wpm muestreado de normal(70, 15)
        avg_wpm = max(30, int(self._rng.gauss(70, 15)))
        typing = TypingProfile(avg_wpm=avg_wpm)

        # Mouse profile (defaults)
        mouse = MouseProfile()

        # Session pattern (defaults)
        session = SessionPattern()

        traits = PersonaTraits(
            engagement_level=engagement,
            preferred_genres=genres,
            preferred_session_hour_local=session_hour,
            device=device,
            platform=platform,
            ui_language=ui_lang,
            timezone=tz,
            country=country,
            behaviors=behaviors,
            typing=typing,
            mouse=mouse,
            session=session,
        )

        return Persona(
            account_id=account_id,
            traits=traits,
            memory=PersonaMemory(),
        )

    def _map_country(self, country: Country) -> tuple[str, str, str]:
        """Mapea país a (timezone, ui_language, locale_hint)."""
        mapping = {
            Country.PE: ("America/Lima", "es-PE", "es-419"),
            Country.MX: ("America/Mexico_City", "es-MX", "es-419"),
            Country.CL: ("America/Santiago", "es-CL", "es-419"),
            Country.AR: ("America/Buenos_Aires", "es-AR", "es-419"),
            Country.CO: ("America/Bogota", "es-CO", "es-419"),
            Country.ES: ("Europe/Madrid", "es-ES", "es-ES"),
            Country.US: ("America/New_York", "en-US", "en-US"),
            Country.EC: ("America/Guayaquil", "es-EC", "es-419"),
            Country.BO: ("America/La_Paz", "es-BO", "es-419"),
            Country.DO: ("America/Santo_Domingo", "es-DO", "es-419"),
            Country.PR: ("America/Puerto_Rico", "es-PR", "es-419"),
            Country.VE: ("America/Caracas", "es-VE", "es-419"),
            Country.UY: ("America/Montevideo", "es-UY", "es-419"),
            Country.PY: ("America/Asuncion", "es-PY", "es-419"),
            Country.PA: ("America/Panama", "es-PA", "es-419"),
            Country.GT: ("America/Guatemala", "es-GT", "es-419"),
            Country.HN: ("America/Tegucigalpa", "es-HN", "es-419"),
            Country.SV: ("America/El_Salvador", "es-SV", "es-419"),
            Country.NI: ("America/Managua", "es-NI", "es-419"),
            Country.CR: ("America/Costa_Rica", "es-CR", "es-419"),
            Country.BR: ("America/Sao_Paulo", "pt-BR", "pt-BR"),
            Country.GB: ("Europe/London", "en-GB", "en-GB"),
            Country.CH: ("Europe/Zurich", "de-CH", "de-CH"),
            Country.DE: ("Europe/Berlin", "de-DE", "de-DE"),
            Country.FR: ("Europe/Paris", "fr-FR", "fr-FR"),
            Country.IT: ("Europe/Rome", "it-IT", "it-IT"),
            Country.PT: ("Europe/Lisbon", "pt-PT", "pt-PT"),
            Country.CA: ("America/Toronto", "en-CA", "en-CA"),
        }
        return mapping.get(country, ("UTC", "en-US", "en-US"))

    def _map_session_pattern(self, pattern: str) -> tuple[int, int]:
        """Mapea patrones de sesión a horas locales (start, end)."""
        patterns = {
            "morning": (7, 10),
            "midday": (11, 14),
            "evening": (18, 22),
            "night": (22, 2),  # 22-24 + 0-2
        }
        return patterns[pattern]
