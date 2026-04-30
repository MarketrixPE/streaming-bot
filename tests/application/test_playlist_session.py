"""Tests del PlaylistSessionUseCase con todos los puertos mockeados."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest
import structlog

from streaming_bot.application.behavior_engine import HumanBehaviorEngine
from streaming_bot.application.playlist_session import (
    PlaylistSessionRequest,
    PlaylistSessionUseCase,
)
from streaming_bot.domain.exceptions import (
    AuthenticationError,
    TargetSiteError,
)
from streaming_bot.domain.history import StreamHistory, StreamOutcome
from tests.application.fakes import (
    build_account,
    build_persona,
    build_playlist,
    build_use_case_mocks,
)


@pytest.fixture(autouse=True)
def _patch_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """Asyncio.sleep -> no-op para tests rapidos."""

    async def _fake_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr("asyncio.sleep", _fake_sleep)


def _make_use_case(mocks: dict[str, Any], *, seed: int = 42) -> PlaylistSessionUseCase:
    log = structlog.get_logger("test")

    def _engine_factory(persona: Any, session_id: str) -> HumanBehaviorEngine:
        return HumanBehaviorEngine(
            persona=persona,
            session_id=session_id,
            rng_seed=seed,
            logger=log,
        )

    return PlaylistSessionUseCase(
        browser=mocks["browser"],
        accounts=mocks["accounts"],
        proxies=mocks["proxies"],
        fingerprints=mocks["fingerprints"],
        sessions=mocks["sessions"],
        personas=mocks["personas"],
        songs=mocks["songs"],
        playlists=mocks["playlists"],
        history=mocks["history"],
        session_records=mocks["session_records"],
        strategy=mocks["strategy"],
        engine_factory=_engine_factory,
        logger=log,
        rng_seed=seed,
    )


class TestPlaylistSessionUseCase:
    async def test_login_flow_invoked_when_not_logged_in(self) -> None:
        persona = build_persona()
        playlist = build_playlist()
        mocks = build_use_case_mocks(persona, playlist)
        mocks["strategy"].is_logged_in.return_value = False

        use_case = _make_use_case(mocks)
        request = PlaylistSessionRequest(
            account_id="acc-1",
            playlist_id=playlist.id,
            target_song_uris=frozenset({"spotify:track:t1"}),
            min_streams=2,
            max_streams=3,
        )

        result = await use_case.execute(request)

        mocks["strategy"].login.assert_awaited_once()
        mocks["sessions"].save.assert_awaited()
        assert result.outcome in {"success", "partial"}

    async def test_skip_login_when_already_logged_in(self) -> None:
        persona = build_persona()
        playlist = build_playlist()
        mocks = build_use_case_mocks(persona, playlist)
        mocks["strategy"].is_logged_in.return_value = True

        use_case = _make_use_case(mocks)
        request = PlaylistSessionRequest(
            account_id="acc-1",
            playlist_id=playlist.id,
            target_song_uris=frozenset({"spotify:track:t1"}),
            min_streams=2,
            max_streams=3,
        )

        await use_case.execute(request)
        mocks["strategy"].login.assert_not_awaited()

    async def test_stream_history_persisted_per_track(self) -> None:
        persona = build_persona()
        playlist = build_playlist(track_count=4)
        mocks = build_use_case_mocks(persona, playlist)

        use_case = _make_use_case(mocks)
        request = PlaylistSessionRequest(
            account_id="acc-1",
            playlist_id=playlist.id,
            target_song_uris=frozenset({"spotify:track:t1"}),
            min_streams=2,
            max_streams=4,
        )

        await use_case.execute(request)

        assert mocks["history"].add.await_count >= 2
        # Verificamos que cada llamada paso un StreamHistory.
        for call in mocks["history"].add.await_args_list:
            assert isinstance(call.args[0], StreamHistory)

    async def test_session_record_persisted_with_metrics(self) -> None:
        persona = build_persona()
        playlist = build_playlist(track_count=4)
        mocks = build_use_case_mocks(persona, playlist)

        use_case = _make_use_case(mocks)
        request = PlaylistSessionRequest(
            account_id="acc-1",
            playlist_id=playlist.id,
            target_song_uris=frozenset({"spotify:track:t1"}),
            min_streams=2,
            max_streams=4,
        )

        await use_case.execute(request)

        mocks["session_records"].add.assert_awaited_once()
        record = mocks["session_records"].add.await_args.args[0]
        assert record.account_id == "acc-1"
        assert record.streams_counted >= 0
        assert record.ended_at is not None

    async def test_persona_memory_updated_after_session(self) -> None:
        persona = build_persona()
        playlist = build_playlist(track_count=3)
        mocks = build_use_case_mocks(persona, playlist)

        use_case = _make_use_case(mocks)
        request = PlaylistSessionRequest(
            account_id="acc-1",
            playlist_id=playlist.id,
            target_song_uris=frozenset({"spotify:track:t1"}),
            min_streams=2,
            max_streams=3,
        )

        await use_case.execute(request)

        mocks["personas"].update_memory.assert_awaited_once()
        # El minimo es que streams totales reflejen lo escuchado.
        updated = mocks["personas"].update_memory.await_args.args[0]
        assert updated.account_id == "acc-1"

    async def test_authentication_error_deactivates_account(self) -> None:
        persona = build_persona()
        playlist = build_playlist()
        mocks = build_use_case_mocks(persona, playlist)
        mocks["strategy"].is_logged_in.return_value = False
        mocks["strategy"].login.side_effect = AuthenticationError("captcha")

        use_case = _make_use_case(mocks)
        request = PlaylistSessionRequest(
            account_id="acc-1",
            playlist_id=playlist.id,
            target_song_uris=frozenset(),
            min_streams=1,
            max_streams=1,
        )

        result = await use_case.execute(request)
        assert result.outcome == "auth_failed"
        # update se llamo para desactivar la cuenta.
        assert mocks["accounts"].update.await_count >= 1
        last_account = mocks["accounts"].update.await_args.args[0]
        assert last_account.status.state == "banned"
        mocks["sessions"].delete.assert_awaited()

    async def test_transient_error_retries(self) -> None:
        persona = build_persona()
        playlist = build_playlist()
        mocks = build_use_case_mocks(persona, playlist)

        # Hacemos que la primera vez falle wait_for_player_ready y la segunda funcione.
        call_state = {"calls": 0}

        async def _flaky_ready(_page: Any) -> None:
            call_state["calls"] += 1
            if call_state["calls"] == 1:
                raise TargetSiteError("layout cambio")

        mocks["strategy"].wait_for_player_ready = AsyncMock(side_effect=_flaky_ready)

        use_case = _make_use_case(mocks)
        request = PlaylistSessionRequest(
            account_id="acc-1",
            playlist_id=playlist.id,
            target_song_uris=frozenset({"spotify:track:t1"}),
            min_streams=1,
            max_streams=2,
        )

        result = await use_case.execute(request)
        # Se reintento al menos una vez.
        assert call_state["calls"] >= 2
        assert result.outcome != "auth_failed"

    async def test_banned_account_returns_failed(self) -> None:
        persona = build_persona()
        playlist = build_playlist()
        mocks = build_use_case_mocks(persona, playlist)
        mocks["accounts"].get.return_value = build_account(banned=True)

        use_case = _make_use_case(mocks)
        request = PlaylistSessionRequest(
            account_id="acc-1",
            playlist_id=playlist.id,
            target_song_uris=frozenset(),
            min_streams=1,
            max_streams=1,
        )

        result = await use_case.execute(request)
        assert result.outcome == "failed"
        # No se intento login.
        mocks["strategy"].login.assert_not_awaited()


class TestStreamOutcomes:
    async def test_target_tracks_count_as_completed_streams(self) -> None:
        persona = build_persona()
        playlist = build_playlist(
            target_uris=("spotify:track:t1", "spotify:track:t2"),
            track_count=4,
        )
        mocks = build_use_case_mocks(persona, playlist)

        use_case = _make_use_case(mocks, seed=7)
        request = PlaylistSessionRequest(
            account_id="acc-1",
            playlist_id=playlist.id,
            target_song_uris=frozenset({"spotify:track:t1", "spotify:track:t2"}),
            min_streams=2,
            max_streams=4,
        )

        result = await use_case.execute(request)
        # Los targets nunca se saltan.
        history_calls = mocks["history"].add.await_args_list
        assert any(
            call.args[0].outcome == StreamOutcome.COUNTED
            and call.args[0].song_uri.startswith("spotify:track:t")
            for call in history_calls
        )
        assert result.target_streams >= 0
