"""CLI con Typer + Rich. Reemplaza por completo a los `input()` y `.bat`."""

from __future__ import annotations

import asyncio
import contextlib
import json
import signal
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any

import anyio
import typer
from cryptography.fernet import Fernet
from rich.console import Console
from rich.table import Table
from sqlalchemy import text as _sql_text

from streaming_bot.application.import_catalog import (
    ImportCatalogService,
    ImportSummary,
    TierClassifier,
)
from streaming_bot.application.stream_song import StreamSongRequest
from streaming_bot.config import load_settings
from streaming_bot.container import Container
from streaming_bot.domain.artist import Artist
from streaming_bot.domain.label import DistributorType, Label
from streaming_bot.domain.ports.account_creator import AccountCreationRequest
from streaming_bot.domain.ports.artist_repo import IArtistRepository
from streaming_bot.domain.ports.label_repo import ILabelRepository
from streaming_bot.domain.ports.song_repo import ISongRepository
from streaming_bot.domain.song import SongTier
from streaming_bot.domain.value_objects import Country
from streaming_bot.infrastructure.monitors.panic_kill_switch import (
    FilesystemPanicKillSwitch,
)
from streaming_bot.infrastructure.observability import get_logger, start_metrics_server
from streaming_bot.infrastructure.persistence.postgres.database import (
    make_engine as _make_engine,
)
from streaming_bot.infrastructure.persistence.postgres.database import (
    make_session_factory as _make_session_factory,
)
from streaming_bot.infrastructure.persistence.postgres.database import (
    transactional_session as _transactional_session,
)
from streaming_bot.infrastructure.persistence.postgres.repos import (
    PostgresArtistRepository as _PgArtistRepo,
)
from streaming_bot.infrastructure.persistence.postgres.repos import (
    PostgresLabelRepository as _PgLabelRepo,
)
from streaming_bot.infrastructure.persistence.postgres.repos import (
    PostgresSongRepository as _PgSongRepo,
)
from streaming_bot.infrastructure.repos import (
    EncryptedAccountRepository,
    JsonArtistRepository,
    JsonLabelRepository,
    JsonSongRepository,
)
from streaming_bot.presentation.strategies import DemoTodoMVCStrategy

app = typer.Typer(
    name="streaming-bot",
    help="Browser automation framework con Clean Architecture.",
    no_args_is_help=True,
)
console = Console()

# ── Subcommand groups ────────────────────────────────────────────────────────
catalog_app = typer.Typer(name="catalog", help="Gestion del catalogo de canciones.")
artist_app = typer.Typer(name="artist", help="Gestion de artistas.")
label_app = typer.Typer(name="label", help="Gestion de labels/distribuidores.")
pilot_app = typer.Typer(name="pilot", help="Estado del piloto de ramp-up.")
panic_app = typer.Typer(name="panic", help="Kill-switch global.")
spotify_app = typer.Typer(name="spotify", help="Operaciones contra Spotify Web API.")
camouflage_app = typer.Typer(name="camouflage", help="Pool de canciones de camuflaje.")
playlist_app = typer.Typer(name="playlist", help="Composicion y sync de playlists.")
account_app = typer.Typer(name="account", help="Creacion y warming de cuentas.")

app.add_typer(catalog_app)
app.add_typer(artist_app)
app.add_typer(label_app)
app.add_typer(pilot_app)
app.add_typer(panic_app)
app.add_typer(spotify_app)
app.add_typer(camouflage_app)
app.add_typer(playlist_app)
app.add_typer(account_app)


# ── Container minimo para CLI (JSON-backed; reemplazable por Postgres) ───────
DEFAULT_CATALOG_DIR = Path("./data/catalog")
DEFAULT_FLAGGED_PATH = Path("./data/flagged_oct2025.csv")
DEFAULT_KILL_SWITCH_PATH = Path("./.kill_switch_active")


@dataclass(slots=True)
class _CatalogContainer:
    """Container minimo para el CLI de catalogo.

    Cablea repos JSON locales mientras el agente de container-wiring no haya
    portado todo a Postgres. La interfaz (los Protocols) es estable; cuando
    Postgres este disponible, solo cambia la fabrica.
    """

    artists: IArtistRepository
    labels: ILabelRepository
    songs: ISongRepository
    classifier: TierClassifier
    flagged_path: Path

    @classmethod
    def build(cls, base_dir: Path = DEFAULT_CATALOG_DIR) -> _CatalogContainer:
        base_dir.mkdir(parents=True, exist_ok=True)
        return cls(
            artists=JsonArtistRepository(base_dir),
            labels=JsonLabelRepository(base_dir),
            songs=JsonSongRepository(base_dir),
            classifier=TierClassifier(),
            flagged_path=DEFAULT_FLAGGED_PATH,
        )

    def make_import_service(self) -> ImportCatalogService:
        return ImportCatalogService(
            artists=self.artists,
            labels=self.labels,
            songs=self.songs,
            classifier=self.classifier,
            logger=get_logger("streaming_bot.import_catalog"),
            flagged_oct2025_path=self.flagged_path,
        )


@app.command()
def keygen() -> None:
    """Genera una nueva master key Fernet (cópiala a SB_STORAGE__MASTER_KEY)."""
    key = Fernet.generate_key().decode()
    console.print("[bold green]Nueva master key:[/bold green]")
    console.print(f"[yellow]{key}[/yellow]")
    console.print(
        "\nGuárdala en .env como [bold]SB_STORAGE__MASTER_KEY[/bold] y NUNCA la commits.",
    )


@app.command("import-accounts")
def import_accounts(
    file: Annotated[
        str,
        typer.Argument(help="Ruta a accounts.txt (formato user:pass por línea)"),
    ],
    country: Annotated[
        Country,
        typer.Option(help="País asignado a las cuentas importadas"),
    ] = Country.US,
) -> None:
    """Importa cuentas desde un .txt plano y las cifra en el repo."""
    settings = load_settings()
    repo = EncryptedAccountRepository(
        path=settings.storage.accounts_path,
        master_key=settings.storage.master_key,
    )

    async def _run() -> None:
        path = anyio.Path(file)
        content = await path.read_text(encoding="utf-8")
        n = await repo.import_plaintext(content.splitlines(), country)
        console.print(
            f"[green]Importadas {n} cuentas a {settings.storage.accounts_path}[/green]",
        )

    asyncio.run(_run())


@app.command()
def run(
    target_url: Annotated[
        str,
        typer.Option("--url", help="URL objetivo. Default: SB_DEMO_URL del .env"),
    ] = "",
    strategy: Annotated[
        str,
        typer.Option(help="Nombre de la estrategia (de momento: demo_todomvc)"),
    ] = "demo_todomvc",
    dry_run: Annotated[
        bool,
        typer.Option(help="Lista lo que ejecutaría sin abrir el browser"),
    ] = False,
) -> None:
    """Ejecuta el orquestador contra todas las cuentas activas."""
    settings = load_settings()
    container = Container.build(settings)
    url = target_url or settings.demo_url

    if settings.observability.metrics_enabled:
        start_metrics_server(settings.observability.metrics_port)
        console.print(
            f"[dim]Métricas Prometheus en http://localhost:"
            f"{settings.observability.metrics_port}/metrics[/dim]",
        )

    site_strategy = _build_strategy(strategy)

    async def _run() -> None:
        accounts = await container.accounts.all()
        if not accounts:
            console.print("[red]No hay cuentas. Importa con `streaming-bot import-accounts`.[/red]")
            raise typer.Exit(code=1)

        active = [a for a in accounts if a.status.is_usable]
        console.print(
            f"[bold]Cuentas:[/bold] {len(active)} activas / {len(accounts)} totales · "
            f"[bold]concurrencia:[/bold] {settings.concurrency} · "
            f"[bold]target:[/bold] {url}",
        )
        if dry_run:
            return

        requests = [StreamSongRequest(account_id=a.id, target_url=url) for a in active]

        orchestrator = container.make_orchestrator(site_strategy)
        try:
            with contextlib.suppress(AttributeError):
                await container.browser.start()  # type: ignore[attr-defined]

            loop = asyncio.get_event_loop()
            stop_event = asyncio.Event()
            for sig in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(sig, stop_event.set)

            run_task = asyncio.create_task(orchestrator.run(requests))
            stop_task = asyncio.create_task(stop_event.wait())
            done, _ = await asyncio.wait(
                {run_task, stop_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if stop_task in done and not run_task.done():
                run_task.cancel()
                try:
                    await run_task
                except asyncio.CancelledError:
                    console.print("[yellow]Cancelado por el usuario.[/yellow]")
                    return

            summary = run_task.result()
            _print_summary(summary)
        finally:
            await container.browser.close()

    asyncio.run(_run())


def _build_strategy(name: str):  # type: ignore[no-untyped-def]
    if name == "demo_todomvc":
        return DemoTodoMVCStrategy()
    msg = f"estrategia desconocida: {name}"
    raise typer.BadParameter(msg)


def _print_summary(summary) -> None:  # type: ignore[no-untyped-def]
    table = Table(title="Resumen del batch")
    table.add_column("Total")
    table.add_column("Éxitos", style="green")
    table.add_column("Fallos", style="red")
    table.add_row(str(summary.total), str(summary.succeeded), str(summary.failed))
    console.print(table)


# ── Catalog commands ─────────────────────────────────────────────────────────


@catalog_app.command("import")
def catalog_import(
    file: Annotated[Path, typer.Argument(exists=True, readable=True)],
    artist_id: Annotated[
        str | None,
        typer.Option("--artist-id", help="Forzar Artist ID"),
    ] = None,
    label_id: Annotated[
        str | None,
        typer.Option("--label-id", help="Forzar Label ID"),
    ] = None,
    distributor: Annotated[
        DistributorType | None,
        typer.Option("--distributor", help="Distribuidor (auto-detectado si se omite)"),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="No persiste; solo reporta"),
    ] = False,
) -> None:
    """Importa un catalogo desde xlsx/csv y clasifica tier+flag por cancion."""
    container = _CatalogContainer.build()
    service = container.make_import_service()

    async def _run() -> ImportSummary:
        return await service.import_file(
            path=file,
            artist_id=artist_id,
            label_id=label_id,
            distributor=distributor,
            dry_run=dry_run,
        )

    summary = asyncio.run(_run())
    _print_import_summary(summary, file)


@catalog_app.command("list")
def catalog_list(
    tier: Annotated[SongTier | None, typer.Option("--tier", help="Filtrar por tier")] = None,
    artist_id: Annotated[
        str | None, typer.Option("--artist-id", help="Filtrar por Artist ID")
    ] = None,
    limit: Annotated[int, typer.Option("--limit", help="Maximo de filas")] = 50,
) -> None:
    """Lista canciones del catalogo aplicando filtros opcionales."""
    container = _CatalogContainer.build()

    async def _run() -> list[Any]:
        repo = container.songs
        list_all = getattr(repo, "list_all", None)
        if list_all is None:
            return []
        songs: list[Any] = list(await list_all())
        return songs

    songs = asyncio.run(_run())
    filtered = [
        s
        for s in songs
        if (tier is None or s.tier == tier)
        and (artist_id is None or s.primary_artist_id == artist_id)
    ]
    filtered = filtered[:limit]

    table = Table(title=f"Catalogo ({len(filtered)} canciones)")
    table.add_column("Tier", style="cyan")
    table.add_column("Titulo", style="bold")
    table.add_column("Artista")
    table.add_column("ISRC")
    table.add_column("Avg/dia", justify="right")
    table.add_column("Flag")
    for song in filtered:
        table.add_row(
            song.tier.value,
            song.title,
            song.artist_name,
            song.metadata.isrc or "-",
            f"{song.baseline_streams_per_day:.1f}",
            "X" if song.spike_oct2025_flag else "",
        )
    console.print(table)


@catalog_app.command("sync-to-db")
def catalog_sync_to_db(
    dsn: Annotated[
        str,
        typer.Option(
            "--dsn",
            help="DSN async (sqlite+aiosqlite:///... o postgresql+asyncpg://...)",
            envvar="DATABASE_URL",
        ),
    ] = "sqlite+aiosqlite:///./data/streaming_bot.db",
    truncate: Annotated[
        bool,
        typer.Option("--truncate", help="Borra tablas songs/artists/labels antes de migrar"),
    ] = False,
) -> None:
    """Migra el catalogo desde repos JSON locales a la base de datos.

    Util cuando el dashboard apunta a Postgres/SQLite y se importo via JSON.
    Idempotente: respeta IDs/spotify_uri existentes, solo upserta.
    """
    container = _CatalogContainer.build()

    async def _run() -> tuple[int, int, int]:
        engine = _make_engine(dsn)
        factory = _make_session_factory(engine)

        artists = await container.artists.list_all()
        labels = await container.labels.list_all()
        list_all = getattr(container.songs, "list_all", None)
        songs: list[Any] = list(await list_all()) if list_all is not None else []

        try:
            async with _transactional_session(factory) as session:
                if truncate:
                    await session.execute(_sql_text("DELETE FROM songs"))
                    await session.execute(_sql_text("DELETE FROM artists"))
                    await session.execute(_sql_text("DELETE FROM labels"))

                label_repo = _PgLabelRepo(session)
                for label in labels:
                    await label_repo.save(label)

                artist_repo = _PgArtistRepo(session)
                for artist in artists:
                    await artist_repo.save(artist)

                song_repo = _PgSongRepo(session)
                for song in songs:
                    await song_repo.update(song)
        finally:
            await engine.dispose()

        return len(artists), len(labels), len(songs)

    n_artists, n_labels, n_songs = asyncio.run(_run())
    console.print(
        f"[green]Sincronizado a {dsn}[/green] · "
        f"artists={n_artists} labels={n_labels} songs={n_songs}",
    )


@catalog_app.command("stats")
def catalog_stats() -> None:
    """Imprime distribucion por tier + flagged + total target_streams_per_day."""
    container = _CatalogContainer.build()

    async def _run() -> tuple[Counter[SongTier], int, int]:
        repo = container.songs
        list_all = getattr(repo, "list_all", None)
        songs: list[Any] = list(await list_all()) if list_all is not None else []
        by_tier: Counter[SongTier] = Counter(s.tier for s in songs)
        flagged = sum(1 for s in songs if s.spike_oct2025_flag)
        target_total = sum(s.target_streams_per_day for s in songs)
        return by_tier, flagged, target_total

    by_tier, flagged, target_total = asyncio.run(_run())
    table = Table(title="Distribucion del catalogo")
    table.add_column("Tier")
    table.add_column("Cantidad", justify="right")
    for tier in SongTier:
        table.add_row(tier.value, str(by_tier.get(tier, 0)))
    console.print(table)
    console.print(f"[bold]Flagged total:[/bold] {flagged}")
    console.print(f"[bold]Target streams/dia (suma):[/bold] {target_total}")


# ── Artist commands ──────────────────────────────────────────────────────────


@artist_app.command("list")
def artist_list() -> None:
    """Lista todos los artistas registrados."""
    container = _CatalogContainer.build()

    async def _run() -> list[Artist]:
        return await container.artists.list_all()

    artists = asyncio.run(_run())
    table = Table(title=f"Artistas ({len(artists)})")
    table.add_column("ID", style="dim")
    table.add_column("Nombre", style="bold")
    table.add_column("Spotify URI")
    table.add_column("Status")
    table.add_column("Spike History")
    for artist in artists:
        table.add_row(
            artist.id[:8],
            artist.name,
            artist.spotify_uri or "-",
            artist.status.value,
            "X" if artist.has_spike_history else "",
        )
    console.print(table)


@artist_app.command("add")
def artist_add(
    name: Annotated[str, typer.Option("--name", help="Nombre del artista")],
    spotify_uri: Annotated[
        str | None, typer.Option("--spotify-uri", help="spotify:artist:XXXX")
    ] = None,
    label_id: Annotated[str | None, typer.Option("--label-id", help="Label asociado")] = None,
) -> None:
    """Crea un artista nuevo."""
    container = _CatalogContainer.build()

    async def _run() -> Artist:
        existing = await container.artists.get_by_name(name)
        if existing is not None:
            return existing
        artist = Artist.new(name=name, spotify_uri=spotify_uri, label_id=label_id)
        await container.artists.save(artist)
        return artist

    artist = asyncio.run(_run())
    console.print(
        f"[green]Artist OK[/green] id={artist.id} name={artist.name} "
        f"uri={artist.spotify_uri or '-'} label={artist.label_id or '-'}",
    )


@artist_app.command("pause")
def artist_pause(
    artist_id: Annotated[str, typer.Argument(help="Artist ID")],
    reason: Annotated[str, typer.Option("--reason", help="Razon del pause")] = "manual",
) -> None:
    """Pausa un artista (cooling-off por flag, etc.)."""
    container = _CatalogContainer.build()

    async def _run() -> Artist | None:
        artist = await container.artists.get(artist_id)
        if artist is None:
            return None
        artist.pause(reason)
        await container.artists.save(artist)
        return artist

    artist = asyncio.run(_run())
    if artist is None:
        console.print(f"[red]Artist {artist_id} no existe[/red]")
        raise typer.Exit(code=1)
    console.print(f"[yellow]Artist {artist.name} pausado[/yellow] reason={reason}")


@artist_app.command("archive")
def artist_archive(artist_id: Annotated[str, typer.Argument(help="Artist ID")]) -> None:
    """Archiva un artista (ya no se boostea)."""
    container = _CatalogContainer.build()

    async def _run() -> Artist | None:
        artist = await container.artists.get(artist_id)
        if artist is None:
            return None
        artist.archive()
        await container.artists.save(artist)
        return artist

    artist = asyncio.run(_run())
    if artist is None:
        console.print(f"[red]Artist {artist_id} no existe[/red]")
        raise typer.Exit(code=1)
    console.print(f"[dim]Artist {artist.name} archivado.[/dim]")


# ── Label commands ───────────────────────────────────────────────────────────


@label_app.command("list")
def label_list() -> None:
    """Lista todos los labels registrados."""
    container = _CatalogContainer.build()

    async def _run() -> list[Label]:
        return await container.labels.list_all()

    labels = asyncio.run(_run())
    table = Table(title=f"Labels ({len(labels)})")
    table.add_column("ID", style="dim")
    table.add_column("Nombre", style="bold")
    table.add_column("Distribuidor")
    table.add_column("Salud")
    for label in labels:
        table.add_row(
            label.id[:8],
            label.name,
            label.distributor.value,
            label.health.value,
        )
    console.print(table)


@label_app.command("add")
def label_add(
    name: Annotated[str, typer.Option("--name", help="Nombre del label")],
    distributor: Annotated[
        DistributorType,
        typer.Option("--distributor", help="Tipo de distribuidor"),
    ] = DistributorType.OTHER,
) -> None:
    """Crea un label/cuenta de distribuidor nuevo."""
    container = _CatalogContainer.build()

    async def _run() -> Label:
        existing = await container.labels.get_by_name(name)
        if existing is not None:
            return existing
        label = Label.new(name=name, distributor=distributor)
        await container.labels.save(label)
        return label

    label = asyncio.run(_run())
    console.print(
        f"[green]Label OK[/green] id={label.id} name={label.name} "
        f"distributor={label.distributor.value}",
    )


# ── Pilot ────────────────────────────────────────────────────────────────────


@pilot_app.command("status")
def pilot_status(
    max_songs: Annotated[int, typer.Option("--max-songs", help="Tope de canciones a listar")] = 60,
) -> None:
    """Lista las canciones eligibles para el piloto y su progreso de hoy."""
    container = _CatalogContainer.build()

    async def _run() -> list[Any]:
        return await container.songs.list_pilot_eligible(max_songs=max_songs)

    eligible = asyncio.run(_run())
    table = Table(title=f"Pilot eligible hoy ({len(eligible)})")
    table.add_column("Tier", style="cyan")
    table.add_column("Titulo")
    table.add_column("Artista")
    table.add_column("Streams hoy", justify="right")
    table.add_column("Cap diario", justify="right")
    table.add_column("Restante", justify="right")
    for song in eligible:
        table.add_row(
            song.tier.value,
            song.title,
            song.artist_name,
            str(song.current_streams_today),
            str(song.safe_ceiling_today()),
            str(song.remaining_capacity_today()),
        )
    console.print(table)


# ── Panic ────────────────────────────────────────────────────────────────────


@panic_app.command("stop")
def panic_stop(
    reason: Annotated[
        str,
        typer.Option("--reason", help="Razon del kill-switch"),
    ] = "manual_cli_panic",
) -> None:
    """Activa el kill-switch global. TODOS los workers deben pararse."""
    switch = FilesystemPanicKillSwitch(
        marker_path=DEFAULT_KILL_SWITCH_PATH,
        logger=get_logger("streaming_bot.panic_cli"),
    )

    async def _run() -> None:
        await switch.trigger(reason=reason)

    asyncio.run(_run())
    console.print(f"[bold red]KILL-SWITCH ACTIVADO[/bold red] reason={reason}")


@panic_app.command("clear")
def panic_clear(
    authorized_by: Annotated[
        str,
        typer.Option("--by", help="Quien autoriza el reset"),
    ] = "operator_cli",
    justification: Annotated[
        str,
        typer.Option("--justification", help="Por que se levanta el switch"),
    ] = "manual_resolution",
) -> None:
    """Desactiva el kill-switch global tras revision humana."""
    switch = FilesystemPanicKillSwitch(
        marker_path=DEFAULT_KILL_SWITCH_PATH,
        logger=get_logger("streaming_bot.panic_cli"),
    )

    async def _run() -> None:
        await switch.reset(authorized_by=authorized_by, justification=justification)

    asyncio.run(_run())
    console.print("[green]Kill-switch limpiado.[/green]")


# ── Spotify ──────────────────────────────────────────────────────────────────


@spotify_app.command("auth")
def spotify_auth() -> None:
    """Obtiene refresh_token de usuario via OAuth flow interactivo.

    Abre browser local para autenticacion. Copia el refresh_token al .env
    como SB_SPOTIFY__USER_REFRESH_TOKEN para operaciones que requieren
    permisos de usuario (crear playlists, agregar tracks).
    """
    from streaming_bot.infrastructure.spotify import (  # noqa: PLC0415
        SpotifyConfig,
        oauth_helper,
    )

    settings = load_settings()
    config = SpotifyConfig(
        client_id=settings.spotify.client_id,
        client_secret=settings.spotify.client_secret,
        redirect_uri=settings.spotify.redirect_uri,
    )

    scopes = [
        "playlist-modify-public",
        "playlist-modify-private",
        "playlist-read-private",
        "user-read-private",
    ]

    async def _run() -> str:
        return await oauth_helper.obtain_user_refresh_token(config, scopes=scopes)

    refresh_token = asyncio.run(_run())
    console.print("[bold green]Refresh token obtenido:[/bold green]")
    console.print(f"[yellow]{refresh_token}[/yellow]")
    console.print(
        f"\n[bold]Copialo al .env como:[/bold]\nSB_SPOTIFY__USER_REFRESH_TOKEN={refresh_token}\n"
    )


@spotify_app.command("search")
def spotify_search(
    query: Annotated[str, typer.Argument(help="Query de busqueda")],
    market: Annotated[Country, typer.Option("--market")] = Country.PE,
    limit: Annotated[int, typer.Option("--limit")] = 10,
) -> None:
    """Busca tracks en Spotify usando client_credentials."""
    from streaming_bot.container import ProductionContainer  # noqa: PLC0415

    settings = load_settings()
    container = ProductionContainer.build(settings)

    async def _run() -> Any:
        client = container.make_spotify_client()
        return await client.search_tracks(query=query, market=market, limit=limit)

    tracks = asyncio.run(_run())
    table = Table(title=f"Spotify Search: {query}")
    table.add_column("URI", style="dim")
    table.add_column("Titulo", style="bold")
    table.add_column("Artista")
    table.add_column("Popularidad", justify="right")
    table.add_column("ISRC")

    for t in tracks:
        table.add_row(
            t.get("uri", ""),
            t.get("name", ""),
            t.get("artist_name", ""),
            str(t.get("popularity", 0)),
            t.get("isrc", ""),
        )
    console.print(table)


@spotify_app.command("track")
def spotify_track(
    uri: Annotated[str, typer.Argument(help="Spotify track URI")],
) -> None:
    """Obtiene metadata detallada de un track."""
    from streaming_bot.container import ProductionContainer  # noqa: PLC0415

    settings = load_settings()
    container = ProductionContainer.build(settings)

    async def _run() -> Any:
        client = container.make_spotify_client()
        return await client.get_track(uri)

    track = asyncio.run(_run())
    console.print(json.dumps(track, indent=2, ensure_ascii=False))


# ── Camouflage ───────────────────────────────────────────────────────────────


@camouflage_app.command("refresh")
def camouflage_refresh(
    markets: Annotated[
        str,
        typer.Option("--markets", help="Mercados separados por coma (e.g. PE,MX,CL)"),
    ] = "PE,MX,CL,AR,CO,ES",
) -> None:
    """Refresca el pool de canciones de camuflaje desde Spotify."""
    from streaming_bot.container import ProductionContainer  # noqa: PLC0415

    settings = load_settings()
    container = ProductionContainer.build(settings)

    market_list = [Country(m.strip()) for m in markets.split(",")]

    async def _run() -> Any:
        spotify_client = container.make_spotify_client()
        camouflage_pool = container.make_camouflage_pool(spotify_client=spotify_client)
        ingest_service = container.make_camouflage_ingest_service(
            spotify_client=spotify_client,
            camouflage_pool=camouflage_pool,
        )
        return await ingest_service.refresh_for_markets(market_list)

    summary = asyncio.run(_run())
    table = Table(title="Camouflage Refresh Summary")
    table.add_column("Metrica", style="bold")
    table.add_column("Valor", justify="right")
    table.add_row("tracks_ingresadas", str(getattr(summary, "tracks_added", 0)))
    table.add_row("tracks_actualizadas", str(getattr(summary, "tracks_updated", 0)))
    table.add_row("tracks_total", str(getattr(summary, "total_tracks", 0)))
    console.print(table)


@camouflage_app.command("stats")
def camouflage_stats() -> None:
    """Estadisticas del pool de camuflaje (por genero/mercado)."""
    # TODO: Wired in OLA 3 final, depends on PostgresCamouflagePool methods
    console.print("[yellow]TODO: stats requiere implementacion de aggregation queries.[/yellow]")


@camouflage_app.command("sample")
def camouflage_sample(
    market: Annotated[Country, typer.Option("--market")] = Country.PE,
    size: Annotated[int, typer.Option("--size")] = 20,
    excluding_target_uri: Annotated[str | None, typer.Option("--excluding-target-uri")] = None,
) -> None:
    """Obtiene una muestra aleatoria del pool de camuflaje."""
    from streaming_bot.container import ProductionContainer  # noqa: PLC0415

    settings = load_settings()
    container = ProductionContainer.build(settings)

    async def _run() -> Any:
        spotify_client = container.make_spotify_client()
        camouflage_pool = container.make_camouflage_pool(spotify_client=spotify_client)
        excluding_set = {excluding_target_uri} if excluding_target_uri else None
        return await camouflage_pool.random_sample(
            market=market,
            size=size,
            excluding_uris=excluding_set,
        )

    sample = asyncio.run(_run())
    table = Table(title=f"Camouflage Sample ({market.value}, n={len(sample)})")
    table.add_column("Track URI", style="dim")
    table.add_column("Titulo")
    table.add_column("Artista")

    for t in sample:
        table.add_row(
            getattr(t, "track_uri", ""),
            getattr(t, "title", ""),
            getattr(t, "artist_uri", ""),
        )
    console.print(table)


# ── Playlist ─────────────────────────────────────────────────────────────────


@playlist_app.command("compose-personal")
def playlist_compose_personal(
    account_id: Annotated[str, typer.Option("--account-id", help="Account ID owner")],
    market: Annotated[Country, typer.Option("--market")] = Country.PE,
    target_uris: Annotated[str, typer.Option("--target-uris", help="URIs separados por coma")] = "",
    size: Annotated[int, typer.Option("--size")] = 30,
    target_ratio: Annotated[float, typer.Option("--target-ratio")] = 0.30,
    persist: Annotated[bool, typer.Option("--persist", help="Guardar en DB")] = False,
) -> None:
    """Compone una playlist personal privada para una cuenta."""
    from streaming_bot.container import ProductionContainer  # noqa: PLC0415

    settings = load_settings()
    container = ProductionContainer.build(settings)

    uri_list = [u.strip() for u in target_uris.split(",") if u.strip()]

    async def _run() -> Any:
        async with container.session_scope() as session:
            song_repo = container.make_song_repository(session)
            target_songs = []
            for uri in uri_list:
                song = await song_repo.get_by_spotify_uri(uri)  # type: ignore[attr-defined]
                if song:
                    target_songs.append(song)

            spotify_client = container.make_spotify_client()
            camouflage_pool = container.make_camouflage_pool(spotify_client=spotify_client)
            composer = container.make_playlist_composer(camouflage_pool=camouflage_pool)

            playlist = await composer.compose_personal_playlist(
                account_id=account_id,
                market=market,
                target_songs=target_songs,
                target_ratio=target_ratio,
                size=size,
            )

            if persist:
                from streaming_bot.infrastructure.persistence.postgres.repos import (  # noqa: PLC0415
                    PostgresPlaylistRepository,
                )

                playlist_repo = PostgresPlaylistRepository(session)
                await playlist_repo.add(playlist)

            return playlist

    playlist = asyncio.run(_run())
    console.print(
        f"[green]Playlist compuesta:[/green] {playlist.name} "
        f"({playlist.total_tracks} tracks, ratio={playlist.target_ratio:.2f})"
    )
    if persist:
        console.print(f"[green]Persistida con ID:[/green] {playlist.id}")


@playlist_app.command("compose-project")
def playlist_compose_project(
    market: Annotated[Country, typer.Option("--market")] = Country.PE,
    genre: Annotated[str, typer.Option("--genre")] = "reggaeton",
    target_uris: Annotated[str, typer.Option("--target-uris", help="URIs separados por coma")] = "",
    size: Annotated[int, typer.Option("--size")] = 50,
    target_ratio: Annotated[float, typer.Option("--target-ratio")] = 0.20,
    persist: Annotated[bool, typer.Option("--persist")] = False,
) -> None:
    """Compone una playlist publica de proyecto."""
    from streaming_bot.container import ProductionContainer  # noqa: PLC0415

    settings = load_settings()
    container = ProductionContainer.build(settings)

    uri_list = [u.strip() for u in target_uris.split(",") if u.strip()]

    async def _run() -> Any:
        async with container.session_scope() as session:
            song_repo = container.make_song_repository(session)
            target_songs = []
            for uri in uri_list:
                song = await song_repo.get_by_spotify_uri(uri)  # type: ignore[attr-defined]
                if song:
                    target_songs.append(song)

            spotify_client = container.make_spotify_client()
            camouflage_pool = container.make_camouflage_pool(spotify_client=spotify_client)
            composer = container.make_playlist_composer(camouflage_pool=camouflage_pool)

            playlist = await composer.compose_project_playlist(
                market=market,
                genre=genre,
                target_songs=target_songs,
                target_ratio=target_ratio,
                size=size,
            )

            if persist:
                from streaming_bot.infrastructure.persistence.postgres.repos import (  # noqa: PLC0415
                    PostgresPlaylistRepository,
                )

                playlist_repo = PostgresPlaylistRepository(session)
                await playlist_repo.add(playlist)

            return playlist

    playlist = asyncio.run(_run())
    console.print(
        f"[green]Playlist compuesta:[/green] {playlist.name} "
        f"({playlist.total_tracks} tracks, ratio={playlist.target_ratio:.2f})"
    )


@playlist_app.command("sync")
def playlist_sync(
    playlist_id: Annotated[str, typer.Argument(help="Playlist ID interno")],
) -> None:
    """Sincroniza una playlist local con Spotify (crea si no existe)."""
    from streaming_bot.container import ProductionContainer  # noqa: PLC0415

    settings = load_settings()
    container = ProductionContainer.build(settings)

    async def _run() -> str:
        async with container.session_scope() as session:
            from streaming_bot.infrastructure.persistence.postgres.repos import (  # noqa: PLC0415
                PostgresPlaylistRepository,
            )

            playlist_repo = PostgresPlaylistRepository(session)
            playlist = await playlist_repo.get(playlist_id)
            if not playlist:
                return "Playlist no encontrada."

            if playlist.spotify_id:
                return f"Playlist ya sincronizada: {playlist.spotify_id}"

            spotify_client = container.make_spotify_client()
            owner_user_id = settings.spotify.owner_user_id
            if not owner_user_id:
                return "SB_SPOTIFY__OWNER_USER_ID no configurado en .env"

            from streaming_bot.domain.playlist import PlaylistKind  # noqa: PLC0415

            is_public = playlist.kind == PlaylistKind.PROJECT_PUBLIC

            spotify_id = await spotify_client.create_playlist(
                owner_user_id=owner_user_id,
                name=playlist.name,
                description=playlist.description or "",
                public=is_public,
            )

            track_uris = [t.track_uri for t in playlist.tracks]
            await spotify_client.add_tracks_to_playlist(spotify_id, track_uris)

            playlist.link_to_spotify(spotify_id)
            await playlist_repo.update(playlist)

            return f"Sincronizada: {spotify_id}"

    result = asyncio.run(_run())
    console.print(f"[green]{result}[/green]")


@playlist_app.command("list")
def playlist_list(
    kind: Annotated[
        str | None, typer.Option("--kind", help="Filtrar por kind (project_public, etc)")
    ] = None,
) -> None:
    """Lista playlists del repositorio."""
    from streaming_bot.container import ProductionContainer  # noqa: PLC0415

    settings = load_settings()
    container = ProductionContainer.build(settings)

    async def _run() -> list[Any]:
        async with container.session_scope() as session:
            from streaming_bot.infrastructure.persistence.postgres.repos import (  # noqa: PLC0415
                PostgresPlaylistRepository,
            )

            repo = PostgresPlaylistRepository(session)
            if kind:
                from streaming_bot.domain.playlist import PlaylistKind  # noqa: PLC0415

                pk = PlaylistKind(kind)
                return await repo.list_by_kind(pk)
            # TODO: list_all method en IPlaylistRepository
            return []

    playlists = asyncio.run(_run())
    table = Table(title=f"Playlists ({len(playlists)})")
    table.add_column("ID", style="dim")
    table.add_column("Nombre", style="bold")
    table.add_column("Kind")
    table.add_column("Tracks", justify="right")
    table.add_column("Ratio", justify="right")
    table.add_column("Spotify ID", style="dim")

    for p in playlists:
        table.add_row(
            p.id[:8],
            p.name,
            p.kind.value,
            str(p.total_tracks),
            f"{p.target_ratio:.2f}",
            p.spotify_id or "-",
        )
    console.print(table)


# ── Account ──────────────────────────────────────────────────────────────────


@account_app.command("create")
def account_create(
    country: Annotated[Country, typer.Option("--country")] = Country.PE,
    use_stub_sms: Annotated[
        bool, typer.Option("--use-stub-sms", help="Usa stub SMS (sin Twilio)")
    ] = False,
) -> None:
    """Crea una cuenta nueva de Spotify via registro automatizado.

    ADVERTENCIA: Este proceso puede fallar si Spotify presenta captcha.
    En ese caso, requiere intervencion humana o uso de servicio externo
    de resolucion de captchas.
    """
    from streaming_bot.container import ProductionContainer  # noqa: PLC0415

    settings = load_settings()
    # Override use_stub_sms si CLI flag esta presente
    if use_stub_sms:
        settings = settings.model_copy(
            update={"accounts": settings.accounts.model_copy(update={"use_stub_sms": True})}
        )

    container = ProductionContainer.build(settings)

    async def _run() -> Any:
        creator = container.make_account_creator()
        request = AccountCreationRequest(country=country)
        return await creator.create_account(request)

    try:
        account = asyncio.run(_run())
        console.print(f"[green]Cuenta creada:[/green] {account.username} ({account.country.value})")
        console.print(f"[dim]ID:[/dim] {account.id}")
    except Exception as e:
        console.print(f"[red]Error al crear cuenta:[/red] {e!s}")
        if "captcha" in str(e).lower():
            console.print(
                "[yellow]Captcha detectado. Requiere intervencion manual o servicio "
                "de resolucion de captchas.[/yellow]"
            )
        raise typer.Exit(code=1) from None


@account_app.command("warming-status")
def account_warming_status() -> None:
    """Lista cuentas en estado warming y su progreso.

    TODO: Requiere persistencia formal del warming state en el repo.
    Actualmente el AccountCreator mantiene warming en memoria.
    """
    console.print(
        "[yellow]Warming state requiere persistencia formal (TODO EPIC).[/yellow]\n"
        "El warming actual se ejecuta en memoria dentro del AccountCreator.\n"
        "Para monitorear warming, revisar logs del orchestrator."
    )


# ── Pretty-printers ──────────────────────────────────────────────────────────


def _print_import_summary(summary: ImportSummary, source: Path) -> None:
    title = f"Import {'(dry-run) ' if summary.dry_run else ''}— {source.name}"
    table = Table(title=title)
    table.add_column("Metric", style="bold")
    table.add_column("Value", justify="right")
    table.add_row("rows_seen", str(summary.rows_seen))
    table.add_row("songs_created", str(summary.songs_created))
    table.add_row("songs_updated", str(summary.songs_updated))
    table.add_row("songs_skipped", str(summary.songs_skipped))
    table.add_row("artists_created", str(summary.artists_created))
    table.add_row("labels_created", str(summary.labels_created))
    table.add_row("flagged_count", str(summary.flagged_count))
    console.print(table)

    tier_table = Table(title="Distribucion por tier")
    tier_table.add_column("Tier")
    tier_table.add_column("Cantidad", justify="right")
    for tier in SongTier:
        tier_table.add_row(tier.value, str(summary.by_tier.get(tier, 0)))
    console.print(tier_table)

    if summary.errors:
        console.print(f"[red]Errores ({len(summary.errors)}):[/red]")
        for err in summary.errors[:10]:
            console.print(f"  - {err}")


# Re-exporta utils que pueden ser usados por scripts ad-hoc.
__all__ = [
    "_CatalogContainer",
    "_print_import_summary",
    "app",
    "artist_app",
    "catalog_app",
    "label_app",
    "panic_app",
    "pilot_app",
]


# Mantengo el helper json aqui por si la auto-deteccion lo necesita logs JSON.
_ = json


if __name__ == "__main__":
    app()
