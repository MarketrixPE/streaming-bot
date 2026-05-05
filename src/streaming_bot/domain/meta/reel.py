"""``Reel``: video corto vertical 9:16 con audio del catalogo + caption + smart-link.

Reels generan spillover legitimo: Beatdapp ve trafico organico real en Spotify
correlacionado con tu catalogo (no solo bot streams). Un Reel exitoso desplaza
la senal-ruido en antifraude porque mete shares/saves/visitas-perfil reales.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from uuid import uuid4


@dataclass(slots=True)
class ReelMetrics:
    """Contadores agregados que devuelven la API de IG y los smart-links.

    Mutables: se refrescan periodicamente por el spillover orchestrator para
    correlacionar plays/shares con el uplift en Spotify.
    """

    plays: int = 0
    shares: int = 0
    saves: int = 0
    likes: int = 0
    comments: int = 0


@dataclass(slots=True)
class Reel:
    """Reel publicado o pendiente de publicar en una ``InstagramAccount``.

    Invariantes:
    - ``video_path`` apunta al .mp4 9:16 generado por ``IReelBuilder``.
    - ``audio_track_uri`` apunta a la pista cuyo spillover queremos.
    - ``smart_link`` es la URL corta (Linkfire o self-hosted) que aparece
      en bio/story para enrutar a Spotify/Apple/Deezer segun pais.
    """

    id: str
    account_id: str
    audio_track_uri: str
    video_path: Path
    caption: str
    hashtags: tuple[str, ...]
    smart_link: str
    posted_at: datetime | None = None
    media_id: str | None = None
    metrics: ReelMetrics = field(default_factory=ReelMetrics)

    def __post_init__(self) -> None:
        if not self.account_id:
            raise ValueError("Reel.account_id no puede estar vacio")
        if not self.audio_track_uri:
            raise ValueError("Reel.audio_track_uri no puede estar vacio")
        if not self.caption.strip():
            raise ValueError("Reel.caption no puede estar vacio")
        if len(self.caption) > 200:
            raise ValueError(f"Reel.caption excede 200 chars: {len(self.caption)}")

    @classmethod
    def new(
        cls,
        *,
        account_id: str,
        audio_track_uri: str,
        video_path: Path,
        caption: str,
        hashtags: tuple[str, ...],
        smart_link: str,
    ) -> Reel:
        return cls(
            id=str(uuid4()),
            account_id=account_id,
            audio_track_uri=audio_track_uri,
            video_path=video_path,
            caption=caption,
            hashtags=hashtags,
            smart_link=smart_link,
        )

    @property
    def plays(self) -> int:
        return self.metrics.plays

    @property
    def shares(self) -> int:
        return self.metrics.shares

    @property
    def saves(self) -> int:
        return self.metrics.saves

    @property
    def is_posted(self) -> bool:
        return self.posted_at is not None and self.media_id is not None

    def mark_posted(self, *, media_id: str, posted_at: datetime) -> None:
        """Registra publicacion exitosa devuelta por instagrapi."""
        self.media_id = media_id
        self.posted_at = posted_at

    def update_metrics(self, metrics: ReelMetrics) -> None:
        """Refresca los contadores (call-site: spillover orchestrator polling)."""
        self.metrics = metrics

    def full_caption(self) -> str:
        """Caption final con hashtags concatenados.

        Formato: ``<caption>\\n\\n#tag1 #tag2 ...``. Mantiene el cuerpo bajo
        200 chars y deja los hashtags al final (mejor CTR/discoverability).
        """
        if not self.hashtags:
            return self.caption
        tags = " ".join(f"#{tag.lstrip('#')}" for tag in self.hashtags)
        return f"{self.caption}\n\n{tags}"
