"""Tests del ``InstagrapiAdapter`` con un cliente fake.

No instalamos ``instagrapi`` en CI: el adapter recibe un ``client_factory``
que devuelve un fake con la superficie necesaria. Validamos:
- Mapeo de excepciones (ChallengeRequired, LoginRequired, otras).
- Roundtrip de settings (login -> token -> restore).
- Conversion de objetos a InstagramAccountInfo / InstagramMediaResult.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from streaming_bot.domain.ports.instagram_client import (
    InstagramAuthError,
    InstagramChallengeRequired,
    InstagramClientError,
    InstagramSessionToken,
)
from streaming_bot.infrastructure.meta.instagrapi_adapter import (
    InstagrapiAdapter,
    _classify_instagrapi_exception,
)

if TYPE_CHECKING:
    pass


# El clasificador del adapter mapea por nombre de clase exacto. Los nombres
# deben coincidir con los de instagrapi (sin sufijo "Error").
class ChallengeRequired(Exception):  # noqa: N818
    pass


class LoginRequired(Exception):  # noqa: N818
    pass


class BadPassword(Exception):  # noqa: N818
    pass


class _FakeMedia:
    def __init__(self, *, pk: int = 1, code: str = "abc") -> None:
        self.pk = pk
        self.code = code


class _FakeAccountInfo:
    def __init__(self) -> None:
        self.username = "fake"
        self.pk = 12345
        self.follower_count = 100
        self.following_count = 50
        self.media_count = 10
        self.is_private = False
        self.is_verified = False


class _FakeMediaInfo:
    def __init__(self) -> None:
        self.play_count = 250
        self.like_count = 30
        self.comment_count = 5
        self.share_count = 8
        self.save_count = 12


class FakeInstagrapiClient:
    """Stub con los metodos sync que el adapter consume."""

    def __init__(
        self,
        *,
        login_exc: Exception | None = None,
        post_exc: Exception | None = None,
    ) -> None:
        self.set_settings_calls: list[dict[str, Any]] = []
        self.set_device_calls: list[dict[str, str]] = []
        self.login_calls: list[tuple[str, str]] = []
        self.clip_upload_calls: list[tuple[Path, str]] = []
        self.story_calls: list[tuple[Path, str, list[dict[str, str]] | None]] = []
        self.like_calls: list[str] = []
        self.comment_calls: list[tuple[str, str]] = []
        self.follow_calls: list[int] = []
        self._settings: dict[str, Any] = {"uuids": {"phone_id": "abc"}}
        self._login_exc = login_exc
        self._post_exc = post_exc

    def set_settings(self, settings: dict[str, Any]) -> None:
        self.set_settings_calls.append(settings)
        self._settings = dict(settings)

    def set_device(self, device: dict[str, str]) -> None:
        self.set_device_calls.append(device)

    def get_settings(self) -> dict[str, Any]:
        return self._settings

    def login(self, username: str, password: str) -> None:
        self.login_calls.append((username, password))
        if self._login_exc is not None:
            raise self._login_exc

    def clip_upload(self, video_path: Path, caption: str) -> _FakeMedia:
        self.clip_upload_calls.append((video_path, caption))
        if self._post_exc is not None:
            raise self._post_exc
        return _FakeMedia()

    def video_upload_to_story(
        self,
        media_path: Path,
        caption: str,
        link: list[dict[str, str]] | None = None,
    ) -> _FakeMedia:
        self.story_calls.append((media_path, caption, link))
        return _FakeMedia(pk=2, code="story")

    def media_like(self, media_id: str) -> None:
        self.like_calls.append(media_id)

    def media_comment(self, media_id: str, text: str) -> None:
        self.comment_calls.append((media_id, text))

    def user_follow(self, target_user_id: int) -> None:
        self.follow_calls.append(target_user_id)

    def account_info(self) -> _FakeAccountInfo:
        return _FakeAccountInfo()

    def media_info(self, media_id: str) -> _FakeMediaInfo:
        del media_id
        return _FakeMediaInfo()


class TestExceptionClassifier:
    def test_challenge_required_maps_to_challenge(self) -> None:
        exc = _classify_instagrapi_exception(ChallengeRequired("rec"))
        assert isinstance(exc, InstagramChallengeRequired)

    def test_login_required_maps_to_auth(self) -> None:
        exc = _classify_instagrapi_exception(LoginRequired("expired"))
        assert isinstance(exc, InstagramAuthError)

    def test_bad_password_maps_to_auth(self) -> None:
        exc = _classify_instagrapi_exception(BadPassword("nope"))
        assert isinstance(exc, InstagramAuthError)

    def test_unknown_maps_to_client_error(self) -> None:
        exc = _classify_instagrapi_exception(RuntimeError("???"))
        assert isinstance(exc, InstagramClientError)


class TestLogin:
    async def test_login_returns_token_with_settings(self) -> None:
        fake_client = FakeInstagrapiClient()
        adapter = InstagrapiAdapter(client_factory=lambda: fake_client)

        token = await adapter.login(
            username="user1",
            password="secret",
            device_fingerprint={"device_id": "abc"},
        )
        assert token.username == "user1"
        assert json.loads(token.settings_json) == {"uuids": {"phone_id": "abc"}}
        assert fake_client.login_calls == [("user1", "secret")]
        assert fake_client.set_device_calls == [{"device_id": "abc"}]

    async def test_login_with_previous_session_restores(self) -> None:
        fake_client = FakeInstagrapiClient()
        adapter = InstagrapiAdapter(client_factory=lambda: fake_client)
        prev = InstagramSessionToken(
            username="user1",
            settings_json=json.dumps({"uuids": {"phone_id": "PREV"}}),
        )
        token = await adapter.login(
            username="user1",
            password="secret",
            device_fingerprint={"device_id": "abc"},
            previous_session=prev,
        )
        assert fake_client.set_settings_calls == [{"uuids": {"phone_id": "PREV"}}]
        assert fake_client.set_device_calls == []
        assert token.username == "user1"

    async def test_login_challenge_raises_typed(self) -> None:
        fake_client = FakeInstagrapiClient(login_exc=ChallengeRequired("challenge"))
        adapter = InstagrapiAdapter(client_factory=lambda: fake_client)
        with pytest.raises(InstagramChallengeRequired):
            await adapter.login(
                username="user1",
                password="secret",
                device_fingerprint={},
            )

    async def test_login_bad_password_raises_auth(self) -> None:
        fake_client = FakeInstagrapiClient(login_exc=BadPassword("wrong"))
        adapter = InstagrapiAdapter(client_factory=lambda: fake_client)
        with pytest.raises(InstagramAuthError):
            await adapter.login(
                username="user1",
                password="x",
                device_fingerprint={},
            )

    async def test_login_invalid_settings_raises(self) -> None:
        fake_client = FakeInstagrapiClient()
        adapter = InstagrapiAdapter(client_factory=lambda: fake_client)
        prev = InstagramSessionToken(username="u", settings_json="{not json")
        with pytest.raises(InstagramAuthError):
            await adapter.login(
                username="u",
                password="p",
                device_fingerprint={},
                previous_session=prev,
            )


class TestPostReel:
    async def test_post_reel_returns_media_result(self, tmp_path: Path) -> None:
        fake_client = FakeInstagrapiClient()
        adapter = InstagrapiAdapter(client_factory=lambda: fake_client)
        video = tmp_path / "v.mp4"
        video.write_bytes(b"\x00")

        token = InstagramSessionToken(username="u", settings_json="{}")
        result = await adapter.post_reel(
            session=token,
            video_path=video,
            caption="cap",
        )
        assert result.media_id == "1"
        assert result.code == "abc"
        assert fake_client.clip_upload_calls == [(video, "cap")]

    async def test_post_reel_missing_file_raises(self, tmp_path: Path) -> None:
        fake_client = FakeInstagrapiClient()
        adapter = InstagrapiAdapter(client_factory=lambda: fake_client)
        token = InstagramSessionToken(username="u", settings_json="{}")
        with pytest.raises(InstagramClientError):
            await adapter.post_reel(
                session=token,
                video_path=tmp_path / "missing.mp4",
                caption="c",
            )

    async def test_post_reel_challenge_raises_typed(self, tmp_path: Path) -> None:
        fake_client = FakeInstagrapiClient(post_exc=ChallengeRequired("recap"))
        adapter = InstagrapiAdapter(client_factory=lambda: fake_client)
        video = tmp_path / "v.mp4"
        video.write_bytes(b"\x00")
        token = InstagramSessionToken(username="u", settings_json="{}")
        with pytest.raises(InstagramChallengeRequired):
            await adapter.post_reel(session=token, video_path=video, caption="c")


class TestAccountInfo:
    async def test_get_account_info_maps_fields(self) -> None:
        fake_client = FakeInstagrapiClient()
        adapter = InstagrapiAdapter(client_factory=lambda: fake_client)
        token = InstagramSessionToken(username="u", settings_json="{}")
        info = await adapter.get_account_info(session=token)
        assert info.username == "fake"
        assert info.user_id == 12345
        assert info.follower_count == 100

    async def test_get_media_metrics_dict(self) -> None:
        fake_client = FakeInstagrapiClient()
        adapter = InstagrapiAdapter(client_factory=lambda: fake_client)
        token = InstagramSessionToken(username="u", settings_json="{}")
        metrics = await adapter.get_media_metrics(session=token, media_id="m-1")
        assert metrics == {
            "plays": 250, "likes": 30, "comments": 5, "shares": 8, "saves": 12,
        }


class TestSimpleActions:
    async def test_like_calls_client(self) -> None:
        fake_client = FakeInstagrapiClient()
        adapter = InstagrapiAdapter(client_factory=lambda: fake_client)
        token = InstagramSessionToken(username="u", settings_json="{}")
        await adapter.like(session=token, media_id="m-1")
        assert fake_client.like_calls == ["m-1"]

    async def test_follow_calls_client(self) -> None:
        fake_client = FakeInstagrapiClient()
        adapter = InstagrapiAdapter(client_factory=lambda: fake_client)
        token = InstagramSessionToken(username="u", settings_json="{}")
        await adapter.follow(session=token, target_user_id=42)
        assert fake_client.follow_calls == [42]

    async def test_comment_calls_client(self) -> None:
        fake_client = FakeInstagrapiClient()
        adapter = InstagrapiAdapter(client_factory=lambda: fake_client)
        token = InstagramSessionToken(username="u", settings_json="{}")
        await adapter.comment(session=token, media_id="m-1", text="cool")
        assert fake_client.comment_calls == [("m-1", "cool")]
