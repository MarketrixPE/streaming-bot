"""Tests del ``FfmpegReelBuilder`` con runner inyectado."""

from __future__ import annotations

from pathlib import Path

import pytest

from streaming_bot.infrastructure.meta.ffmpeg_reel_builder import (
    FfmpegReelBuilder,
    ReelBuildError,
)


def _runner_fail() -> object:
    async def runner(_argv: list[str]) -> tuple[int, bytes, bytes]:
        return 1, b"", b"ffmpeg crashed"

    return runner


class TestFfmpegReelBuilderHappyPath:
    async def test_builds_argv_with_metadata_and_scale(self, tmp_path: Path) -> None:
        captured: list[list[str]] = []

        async def runner(argv: list[str]) -> tuple[int, bytes, bytes]:
            captured.append(argv)
            (tmp_path / "out.mp4").write_bytes(b"\x00")
            return 0, b"", b""

        stock = tmp_path / "stock.mp4"
        stock.write_bytes(b"\x00")
        audio = tmp_path / "audio.mp3"
        audio.write_bytes(b"\x00")
        builder = FfmpegReelBuilder(ffmpeg_path=Path("/usr/bin/ffmpeg"), runner=runner)

        out = await builder.build(
            stock_video_path=stock,
            audio_track_path=audio,
            output_path=tmp_path / "out.mp4",
            artist_uri="catalog:artist:abc",
        )
        assert out == tmp_path / "out.mp4"
        assert len(captured) == 1
        argv = captured[0]
        assert "/usr/bin/ffmpeg" in argv
        assert str(stock) in argv
        assert str(audio) in argv
        idx_meta = argv.index("-metadata")
        assert argv[idx_meta + 1] == "comment=artist_uri=catalog:artist:abc"
        idx_vf = argv.index("-vf")
        assert "scale=1080:1920" in argv[idx_vf + 1]
        assert "crop=1080:1920" in argv[idx_vf + 1]

    async def test_respects_max_seconds(self, tmp_path: Path) -> None:
        captured: list[list[str]] = []

        async def runner(argv: list[str]) -> tuple[int, bytes, bytes]:
            captured.append(argv)
            (tmp_path / "out.mp4").write_bytes(b"\x00")
            return 0, b"", b""

        stock = tmp_path / "s.mp4"
        stock.write_bytes(b"\x00")
        audio = tmp_path / "a.mp3"
        audio.write_bytes(b"\x00")
        builder = FfmpegReelBuilder(
            ffmpeg_path=Path("ffmpeg"),
            runner=runner,
            max_duration_seconds=15,
        )
        await builder.build(
            stock_video_path=stock,
            audio_track_path=audio,
            output_path=tmp_path / "out.mp4",
            artist_uri="catalog:artist:x",
            max_seconds=60,
        )
        argv = captured[0]
        idx_t = argv.index("-t")
        assert argv[idx_t + 1] == "15"

    async def test_creates_output_dir(self, tmp_path: Path) -> None:
        nested = tmp_path / "nested" / "dir"
        out = nested / "out.mp4"

        async def runner(_argv: list[str]) -> tuple[int, bytes, bytes]:
            out.write_bytes(b"\x00")
            return 0, b"", b""

        stock = tmp_path / "s.mp4"
        stock.write_bytes(b"\x00")
        audio = tmp_path / "a.mp3"
        audio.write_bytes(b"\x00")
        builder = FfmpegReelBuilder(ffmpeg_path=Path("ffmpeg"), runner=runner)
        await builder.build(
            stock_video_path=stock,
            audio_track_path=audio,
            output_path=out,
            artist_uri="catalog:artist:x",
        )
        assert out.exists()


class TestFfmpegReelBuilderFailures:
    async def test_missing_stock_raises(self, tmp_path: Path) -> None:
        audio = tmp_path / "a.mp3"
        audio.write_bytes(b"\x00")
        builder = FfmpegReelBuilder(ffmpeg_path=Path("ffmpeg"))
        with pytest.raises(ReelBuildError, match="stock_video"):
            await builder.build(
                stock_video_path=tmp_path / "missing.mp4",
                audio_track_path=audio,
                output_path=tmp_path / "out.mp4",
                artist_uri="catalog:artist:x",
            )

    async def test_missing_audio_raises(self, tmp_path: Path) -> None:
        stock = tmp_path / "s.mp4"
        stock.write_bytes(b"\x00")
        builder = FfmpegReelBuilder(ffmpeg_path=Path("ffmpeg"))
        with pytest.raises(ReelBuildError, match="audio_track"):
            await builder.build(
                stock_video_path=stock,
                audio_track_path=tmp_path / "missing.mp3",
                output_path=tmp_path / "out.mp4",
                artist_uri="catalog:artist:x",
            )

    async def test_empty_artist_uri_raises(self, tmp_path: Path) -> None:
        stock = tmp_path / "s.mp4"
        stock.write_bytes(b"\x00")
        audio = tmp_path / "a.mp3"
        audio.write_bytes(b"\x00")
        builder = FfmpegReelBuilder(ffmpeg_path=Path("ffmpeg"))
        with pytest.raises(ReelBuildError, match="artist_uri"):
            await builder.build(
                stock_video_path=stock,
                audio_track_path=audio,
                output_path=tmp_path / "out.mp4",
                artist_uri="",
            )

    async def test_runner_failure_raises(self, tmp_path: Path) -> None:
        stock = tmp_path / "s.mp4"
        stock.write_bytes(b"\x00")
        audio = tmp_path / "a.mp3"
        audio.write_bytes(b"\x00")
        builder = FfmpegReelBuilder(ffmpeg_path=Path("ffmpeg"), runner=_runner_fail())
        with pytest.raises(ReelBuildError, match="codigo 1"):
            await builder.build(
                stock_video_path=stock,
                audio_track_path=audio,
                output_path=tmp_path / "out.mp4",
                artist_uri="catalog:artist:x",
            )

    async def test_runner_ok_but_no_output_raises(self, tmp_path: Path) -> None:
        async def runner(_argv: list[str]) -> tuple[int, bytes, bytes]:
            return 0, b"", b""

        stock = tmp_path / "s.mp4"
        stock.write_bytes(b"\x00")
        audio = tmp_path / "a.mp3"
        audio.write_bytes(b"\x00")
        builder = FfmpegReelBuilder(ffmpeg_path=Path("ffmpeg"), runner=runner)
        with pytest.raises(ReelBuildError, match="no creo el archivo"):
            await builder.build(
                stock_video_path=stock,
                audio_track_path=audio,
                output_path=tmp_path / "out.mp4",
                artist_uri="catalog:artist:x",
            )
