"""``SmartLink``: URL corta con geo-routing a DSPs.

Linkfire-style: un solo enlace en la bio de IG / story redirige a:
- PE -> Spotify (mercado dominante actual)
- US -> Apple Music (preferencia hispano-americana iOS)
- DE/UK -> Spotify
- BR -> Deezer (cuota residual)
- fallback global -> Spotify

El servicio adapter (Linkfire/self-hosted) hace el 302 con tracking, este
``SmartLink`` solo modela el mapping inmutable y la metadata canonica.
"""

from __future__ import annotations

from dataclasses import dataclass

from streaming_bot.domain.value_objects import Country


class DSP(str):
    """Identificador de DSP destino. ``str``-based para serializar facil.

    Definimos las constantes mas usadas como class-vars en lugar de Enum
    para que el adapter Linkfire pueda recibir DSP arbitrarios sin
    necesitar cambiar el codigo (ej. "youtube_music", "tidal", etc.).
    """

    SPOTIFY = "spotify"
    APPLE_MUSIC = "apple_music"
    DEEZER = "deezer"
    SOUNDCLOUD = "soundcloud"
    AMAZON_MUSIC = "amazon_music"
    TIDAL = "tidal"
    YOUTUBE_MUSIC = "youtube_music"


@dataclass(frozen=True, slots=True)
class SmartLink:
    """Link inmutable con destinos por (Country, DSP).

    Invariantes:
    - ``short_id`` es el path-tail de la URL publica (ej. ``aB3xZ``).
    - ``target_dsps`` mapea cada pais a un dict ``{dsp -> url}``. Si un pais
      no esta en el dict, el adapter aplica fallback global (primer DSP de
      ``Country.US`` o el primero disponible).
    - ``track_uri`` es el URI canonico del catalogo (``catalog:track:...``)
      para correlacion downstream con el spillover orchestrator.
    """

    short_id: str
    target_dsps: dict[Country, dict[str, str]]
    track_uri: str

    def __post_init__(self) -> None:
        if not self.short_id:
            raise ValueError("SmartLink.short_id no puede estar vacio")
        if not self.track_uri:
            raise ValueError("SmartLink.track_uri no puede estar vacio")
        if not self.target_dsps:
            raise ValueError("SmartLink.target_dsps no puede estar vacio")

    def url_for(
        self,
        *,
        country: Country,  # noqa: ARG002 - forward-compat: adapters podrian banear el country en la URL
        base_url: str,
    ) -> str:
        """URL publica resuelta. El redirect 302 lo hace el adapter.

        ``country`` se mantiene en la firma para que adapters futuros que
        baken el pais en la URL (``/PE/{short_id}``) puedan usarlo sin
        cambiar callers.
        """
        return f"{base_url.rstrip('/')}/{self.short_id}"

    def resolve(self, *, country: Country, dsp: str | None = None) -> str | None:
        """Devuelve el URL de destino para ``country`` y ``dsp``.

        Si ``dsp`` es None devuelve el primer URL disponible para el pais.
        Si el pais no esta mapeado, devuelve None y el adapter aplica el
        fallback global (responsabilidad del adapter, no del value object).
        """
        country_targets = self.target_dsps.get(country)
        if not country_targets:
            return None
        if dsp is None:
            return next(iter(country_targets.values()))
        return country_targets.get(dsp)
