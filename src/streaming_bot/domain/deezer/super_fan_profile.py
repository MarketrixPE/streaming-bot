"""Perfil "super-fan" para la economia ACPS de Deezer.

ACPS (Artist-Centric Payment System) entro en vigor en Deezer durante 2024
y rompe la economia clasica de bot streaming:

- Tracks con >1000 listeners unicos/mes y >500 streams/mes reciben un boost
  multiplicativo x2 al pago por stream (super-fan logic).
- Cuentas que aportan spread plano (muchas cuentas, pocos plays cada una)
  son penalizadas: sus streams cuentan a un fraccion del valor.
- Cuentas con catalogos amplios y sesiones largas son premiadas.

`SuperFanProfile` es un value object inmutable que define los umbrales que
una cuenta debe superar para ser considerada super-fan organica. Los valores
por defecto provienen de las heuristicas publicas reportadas por Deezer,
Universal y Believe Music.

Decisiones de diseno:
- frozen + slots: las thresholds son constantes durante una corrida.
- Sin I/O: este modulo solo conoce numeros y comparaciones.
- Validacion en `__post_init__`: rechaza umbrales negativos o ratios fuera
  de [0, 1].
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SuperFanProfile:
    """Umbrales que una cuenta debe alcanzar para considerarse super-fan.

    Los valores por defecto reflejan la heuristica que Deezer aplica en su
    Artist-Centric Payment System y que Universal/Believe replican en sus
    auditorias internas:

    - `artists_followed_min`: minimo de artistas seguidos en la libreria.
      Senal de catalogo amplio (no playlist-leecher).
    - `avg_session_minutes_min`: duracion media de sesion en minutos durante
      los ultimos 30 dias. Bots clasicos abren-stream-cierran en <5min.
    - `replay_rate_min`: ratio entre repeticiones del mismo track y plays
      unicos. Super-fans tienden a re-escuchar.
    - `distinct_tracks_30d_min`: tracks unicos escuchados en 30 dias.
    - `distinct_albums_30d_min`: albumes unicos escuchados en 30 dias.

    Ratios `0.0` no son utiles (los bots los maximizan trivialmente). Por eso
    `replay_rate_min` se fuerza estrictamente > 0.
    """

    artists_followed_min: int = 50
    avg_session_minutes_min: float = 45.0
    replay_rate_min: float = 0.3
    distinct_tracks_30d_min: int = 200
    distinct_albums_30d_min: int = 30

    def __post_init__(self) -> None:
        # Las constantes de configuracion deben ser sanas: rechazar valores
        # negativos o ratios > 1 evita silently-wrong policies.
        if self.artists_followed_min < 0:
            raise ValueError(
                f"artists_followed_min debe ser >= 0: {self.artists_followed_min}"
            )
        if self.avg_session_minutes_min < 0:
            raise ValueError(
                f"avg_session_minutes_min debe ser >= 0: {self.avg_session_minutes_min}"
            )
        if not 0.0 < self.replay_rate_min <= 1.0:
            raise ValueError(
                f"replay_rate_min debe estar en (0, 1]: {self.replay_rate_min}"
            )
        if self.distinct_tracks_30d_min < 0:
            raise ValueError(
                f"distinct_tracks_30d_min debe ser >= 0: {self.distinct_tracks_30d_min}"
            )
        if self.distinct_albums_30d_min < 0:
            raise ValueError(
                f"distinct_albums_30d_min debe ser >= 0: {self.distinct_albums_30d_min}"
            )

    @classmethod
    def strict(cls) -> SuperFanProfile:
        """Perfil agresivo: usa los thresholds publicados por Deezer ACPS.

        Util como referencia tras Q4 2024, cuando Deezer endurecio el filtro.
        """
        return cls(
            artists_followed_min=50,
            avg_session_minutes_min=45.0,
            replay_rate_min=0.3,
            distinct_tracks_30d_min=200,
            distinct_albums_30d_min=30,
        )

    @classmethod
    def lenient(cls) -> SuperFanProfile:
        """Perfil tolerante: util para cuentas en pipeline de "super-fan-ing"."""
        return cls(
            artists_followed_min=25,
            avg_session_minutes_min=25.0,
            replay_rate_min=0.15,
            distinct_tracks_30d_min=100,
            distinct_albums_30d_min=15,
        )
