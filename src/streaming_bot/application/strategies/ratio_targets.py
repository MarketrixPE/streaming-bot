"""Targets de ratios humanos por geografia y genero musical.

Este modulo define `RatioTargets`: la distribucion humana objetivo de
acciones (save / skip / queue / like) por persona. Se usan como "anclas"
del `RatioController` para mantener cada cuenta dentro de un rango
realista que coincida con las distribuciones publicadas por Spotify y
con lo que Beatdapp espera ver para una cuenta organica.

Defaults Q1 2026 (mediciones publicas):
- save_rate    ~ 0.04   (Spotify global avg, "Wrapped" backstage)
- skip_rate    ~ 0.45   (mediana global; Spotify dice "less than half")
- queue_rate   ~ 0.015  (mucho mas raro que save)
- like_rate    ~ 0.06   (engagement medio sobre artista o playlist)

Modulaciones por geo: LATAM consume mas (save/like mas alto, skip mas bajo);
ASIA consume menos engagement; US/UK queda en el midpoint.

Modulaciones por genero: lo-fi/sleep/ambient son "musica de fondo" -> save y
like bajos; pop/reggaeton tienen engagement alto.

Diseno DIP-friendly: el modulo no depende de presentation/infrastructure;
solo del dominio (`Country`, `Persona`).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from streaming_bot.domain.value_objects import Country

if TYPE_CHECKING:
    from streaming_bot.domain.persona import Persona


# ── Defaults globales (mediciones publicas 2026) ──────────────────────────
DEFAULT_SAVE_RATE = 0.04
DEFAULT_SKIP_RATE = 0.45
DEFAULT_QUEUE_RATE = 0.015
DEFAULT_LIKE_RATE = 0.06

# Limite duro para evitar que combinaciones extremas saquen la persona del
# espacio humano (ej. save_rate > 0.20 dispararia banderas en Beatdapp).
_HARD_MAX_RATE = 0.95


# Buckets geograficos. Mantengo solo 3 buckets para que el calibrado sea
# defendible con datos publicos; ampliar requiere benchmark especifico.
_LATAM_COUNTRIES: frozenset[Country] = frozenset(
    {
        Country.PE,
        Country.MX,
        Country.CL,
        Country.AR,
        Country.CO,
        Country.EC,
        Country.BO,
        Country.DO,
        Country.PR,
        Country.VE,
        Country.UY,
        Country.PY,
        Country.PA,
        Country.GT,
        Country.HN,
        Country.SV,
        Country.NI,
        Country.CR,
        Country.BR,
    }
)

_ANGLO_COUNTRIES: frozenset[Country] = frozenset(
    {
        Country.US,
        Country.GB,
        Country.IE,
        Country.CA,
        Country.AU,
        Country.NZ,
    }
)

_ASIA_COUNTRIES: frozenset[Country] = frozenset({Country.JP, Country.TH})


# Buckets de generos. La key se compara case-insensitive y por substring
# para tolerar variantes ("indie pop", "lo-fi hip hop").
_LOW_ENGAGEMENT_GENRES: tuple[str, ...] = (
    "lo-fi",
    "lofi",
    "ambient",
    "sleep",
    "study",
    "white noise",
    "classical",
    "jazz",
    "instrumental",
    "soundtrack",
    "meditation",
)

_HIGH_ENGAGEMENT_GENRES: tuple[str, ...] = (
    "pop",
    "reggaeton",
    "latin",
    "hip hop",
    "rap",
    "k-pop",
    "kpop",
    "trap",
    "edm",
    "electronic",
    "rock",
    "metal",
)


@dataclass(frozen=True, slots=True)
class RatioTargets:
    """Tasas humanas objetivo de acciones por sesion.

    Cada campo es la fraccion (0..1) de tracks reproducidos en una sesion
    "ideal" en los que esa accion deberia ocurrir. El `RatioController`
    se encarga de empujar la observacion real hacia estas anclas.

    Los valores deben mantenerse dentro de [0, _HARD_MAX_RATE]. La
    construccion valida los rangos para evitar configurar una cuenta
    fuera del espacio humano por error.
    """

    save_rate: float = DEFAULT_SAVE_RATE
    skip_rate: float = DEFAULT_SKIP_RATE
    queue_rate: float = DEFAULT_QUEUE_RATE
    like_rate: float = DEFAULT_LIKE_RATE

    def __post_init__(self) -> None:
        for field_name in ("save_rate", "skip_rate", "queue_rate", "like_rate"):
            value = float(getattr(self, field_name))
            if not 0.0 <= value <= _HARD_MAX_RATE:
                raise ValueError(
                    f"RatioTargets.{field_name}={value} fuera de rango "
                    f"[0, {_HARD_MAX_RATE}]",
                )

    # ── Factories por dimension ───────────────────────────────────────────
    @classmethod
    def default(cls) -> RatioTargets:
        """Defaults globales 2026 (US/EU midpoint)."""
        return cls()

    @classmethod
    def for_country(cls, country: Country) -> RatioTargets:
        """Calibrado por geografia.

        - LATAM: engagement notablemente mas alto, skip mas bajo.
        - ASIA: engagement bajo (uso "background" mas frecuente).
        - Anglo (US/UK/CA/AU/NZ/IE): defaults globales.
        - Resto (EU continental, otros): defaults con leve disminucion del
          save (mercados con mas exposicion algoritmica > menos saves
          manuales) y skip ligeramente mas alto.
        """
        if country in _LATAM_COUNTRIES:
            return cls(
                save_rate=0.06,
                skip_rate=0.38,
                queue_rate=0.020,
                like_rate=0.09,
            )
        if country in _ASIA_COUNTRIES:
            return cls(
                save_rate=0.03,
                skip_rate=0.40,
                queue_rate=0.012,
                like_rate=0.04,
            )
        if country in _ANGLO_COUNTRIES:
            return cls()
        return cls(
            save_rate=0.035,
            skip_rate=0.48,
            queue_rate=0.012,
            like_rate=0.05,
        )

    @classmethod
    def for_genre(cls, genre: str) -> RatioTargets:
        """Calibrado por genero principal de la persona.

        Si el genero contiene tokens de baja interaccion (lo-fi, sleep,
        ambient), retorna targets bajos. Si es alto-engagement (pop,
        reggaeton), retorna targets altos. Default: globales 2026.
        """
        normalized = (genre or "").lower().strip()
        if not normalized:
            return cls()
        if any(token in normalized for token in _LOW_ENGAGEMENT_GENRES):
            return cls(
                save_rate=0.02,
                skip_rate=0.30,
                queue_rate=0.008,
                like_rate=0.03,
            )
        if any(token in normalized for token in _HIGH_ENGAGEMENT_GENRES):
            return cls(
                save_rate=0.07,
                skip_rate=0.42,
                queue_rate=0.022,
                like_rate=0.10,
            )
        return cls()

    @classmethod
    def combined(cls, country_targets: RatioTargets, genre_targets: RatioTargets) -> RatioTargets:
        """Combinacion de targets por geo y genero.

        Estrategia: promedio simple. Mantenemos la formula simple para
        que sea predecible y testeable; si en el futuro se necesita una
        mezcla ponderada (peso por confianza del bucket), se puede
        sustituir aqui sin afectar al RatioController.
        """
        return cls(
            save_rate=_avg(country_targets.save_rate, genre_targets.save_rate),
            skip_rate=_avg(country_targets.skip_rate, genre_targets.skip_rate),
            queue_rate=_avg(country_targets.queue_rate, genre_targets.queue_rate),
            like_rate=_avg(country_targets.like_rate, genre_targets.like_rate),
        )

    @classmethod
    def for_persona(cls, persona: Persona) -> RatioTargets:
        """Combina targets por country + genero principal de la persona.

        Si la persona no declara generos, usa solo country targets.
        """
        country_targets = cls.for_country(persona.country)
        genres = persona.traits.preferred_genres
        if not genres:
            return country_targets
        genre_targets = cls.for_genre(genres[0])
        return cls.combined(country_targets, genre_targets)

    # ── Mutaciones inmutables (devuelven copia) ───────────────────────────
    def with_overrides(
        self,
        *,
        save_rate: float | None = None,
        skip_rate: float | None = None,
        queue_rate: float | None = None,
        like_rate: float | None = None,
    ) -> RatioTargets:
        """Devuelve copia con campos sobreescritos. Util para experimentos."""
        return replace(
            self,
            save_rate=save_rate if save_rate is not None else self.save_rate,
            skip_rate=skip_rate if skip_rate is not None else self.skip_rate,
            queue_rate=queue_rate if queue_rate is not None else self.queue_rate,
            like_rate=like_rate if like_rate is not None else self.like_rate,
        )


def _avg(a: float, b: float) -> float:
    """Promedio simple, clampeado al rango valido."""
    value = (a + b) / 2.0
    return max(0.0, min(value, _HARD_MAX_RATE))
