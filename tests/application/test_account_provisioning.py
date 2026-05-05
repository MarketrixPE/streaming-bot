"""Tests del ``InstagramAccountProvisioningService``."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from streaming_bot.application.meta.account_provisioning import (
    IInstagramAccountRepository,
    InstagramAccountProvisioningService,
)
from streaming_bot.domain.artist import Artist
from streaming_bot.domain.meta.instagram_account import (
    InstagramAccount,
    InstagramAccountStatus,
)

if TYPE_CHECKING:
    pass


class FakeAccountRepo(IInstagramAccountRepository):
    def __init__(self) -> None:
        self.by_artist: dict[str, InstagramAccount] = {}
        self.by_username: dict[str, InstagramAccount] = {}
        self.added: list[InstagramAccount] = []
        self.updated: list[InstagramAccount] = []

    async def get_by_artist_uri(self, artist_uri: str) -> InstagramAccount | None:
        return self.by_artist.get(artist_uri)

    async def get_by_username(self, username: str) -> InstagramAccount | None:
        return self.by_username.get(username)

    async def add(self, account: InstagramAccount) -> None:
        self.by_artist[account.artist_uri] = account
        self.by_username[account.username] = account
        self.added.append(account)

    async def update(self, account: InstagramAccount) -> None:
        self.by_artist[account.artist_uri] = account
        self.by_username[account.username] = account
        self.updated.append(account)

    async def list_active(self) -> list[InstagramAccount]:
        return list(self.by_artist.values())


def _artist(*, name: str = "Lumen Drift", spotify_uri: str | None = None) -> Artist:
    return Artist.new(name=name, spotify_uri=spotify_uri)


class TestProvisionForArtist:
    async def test_creates_when_absent(self) -> None:
        repo = FakeAccountRepo()
        artist = _artist(spotify_uri="spotify:artist:xyz")

        async def factory(a: Artist) -> InstagramAccount:
            return InstagramAccount.new(
                username=f"ig_{a.id[:6]}",
                persona_id=a.id,
                artist_uri=a.spotify_uri or f"catalog:artist:{a.id}",
            )

        service = InstagramAccountProvisioningService(
            accounts=repo, account_factory=factory,
        )
        result = await service.provision_for_artist(artist)
        assert result.created is True
        assert result.account.artist_uri == "spotify:artist:xyz"
        assert len(repo.added) == 1

    async def test_idempotent_when_present(self) -> None:
        repo = FakeAccountRepo()
        existing = InstagramAccount.new(
            username="ig_existing",
            persona_id="p1",
            artist_uri="spotify:artist:xyz",
        )
        repo.by_artist["spotify:artist:xyz"] = existing
        repo.by_username["ig_existing"] = existing
        artist = _artist(spotify_uri="spotify:artist:xyz")

        async def factory(_a: Artist) -> InstagramAccount:
            raise AssertionError("factory no debe invocarse cuando ya existe")

        service = InstagramAccountProvisioningService(
            accounts=repo, account_factory=factory,
        )
        result = await service.provision_for_artist(artist)
        assert result.created is False
        assert result.account is existing
        assert len(repo.added) == 0

    async def test_uses_catalog_uri_when_no_spotify_uri(self) -> None:
        repo = FakeAccountRepo()
        artist = _artist(spotify_uri=None)
        captured: list[str] = []

        async def factory(a: Artist) -> InstagramAccount:
            captured.append(a.id)
            return InstagramAccount.new(
                username="catalog_user",
                persona_id=a.id,
                artist_uri=f"catalog:artist:{a.id}",
            )

        service = InstagramAccountProvisioningService(
            accounts=repo, account_factory=factory,
        )
        result = await service.provision_for_artist(artist)
        assert result.account.artist_uri == f"catalog:artist:{artist.id}"
        assert captured == [artist.id]

    async def test_factory_inconsistent_artist_uri_raises(self) -> None:
        repo = FakeAccountRepo()
        artist = _artist(spotify_uri="spotify:artist:xyz")

        async def factory(_a: Artist) -> InstagramAccount:
            return InstagramAccount.new(
                username="ig_x",
                persona_id="p",
                artist_uri="spotify:artist:WRONG",
            )

        service = InstagramAccountProvisioningService(
            accounts=repo, account_factory=factory,
        )
        with pytest.raises(ValueError, match="artist_uri inconsistente"):
            await service.provision_for_artist(artist)

    async def test_username_already_taken_raises(self) -> None:
        repo = FakeAccountRepo()
        existing_other = InstagramAccount.new(
            username="ig_dup",
            persona_id="p2",
            artist_uri="spotify:artist:OTHER",
        )
        repo.by_username["ig_dup"] = existing_other
        artist = _artist(spotify_uri="spotify:artist:NEW")

        async def factory(a: Artist) -> InstagramAccount:
            return InstagramAccount.new(
                username="ig_dup",
                persona_id=a.id,
                artist_uri="spotify:artist:NEW",
            )

        service = InstagramAccountProvisioningService(
            accounts=repo, account_factory=factory,
        )
        with pytest.raises(ValueError, match="ya esta asignado"):
            await service.provision_for_artist(artist)


class TestProvisionForCatalog:
    async def test_provisions_each_artist_once(self) -> None:
        repo = FakeAccountRepo()
        artists = [
            _artist(name="A", spotify_uri="spotify:artist:1"),
            _artist(name="B", spotify_uri="spotify:artist:2"),
            _artist(name="C", spotify_uri="spotify:artist:3"),
        ]

        async def factory(a: Artist) -> InstagramAccount:
            return InstagramAccount.new(
                username=f"ig_{a.name.lower()}",
                persona_id=a.id,
                artist_uri=a.spotify_uri or f"catalog:artist:{a.id}",
            )

        service = InstagramAccountProvisioningService(
            accounts=repo, account_factory=factory,
        )
        results = await service.provision_for_catalog(artists)
        assert all(r.created for r in results)
        assert len(repo.added) == 3

        results_again = await service.provision_for_catalog(artists)
        assert all(not r.created for r in results_again)
        assert len(repo.added) == 3


class TestListPostable:
    async def test_filters_only_active(self) -> None:
        repo = FakeAccountRepo()
        a1 = InstagramAccount.new(
            username="u1", persona_id="p1", artist_uri="spotify:artist:1",
        )
        a1.mark_active()
        a2 = InstagramAccount.new(
            username="u2", persona_id="p2", artist_uri="spotify:artist:2",
        )
        a3 = InstagramAccount.new(
            username="u3", persona_id="p3", artist_uri="spotify:artist:3",
        )
        a3.mark_challenge("recap")
        for a in (a1, a2, a3):
            repo.by_artist[a.artist_uri] = a

        async def factory(_a: Artist) -> InstagramAccount:
            raise AssertionError("not used")

        service = InstagramAccountProvisioningService(
            accounts=repo, account_factory=factory,
        )
        postable = await service.list_postable_accounts()
        assert {a.username for a in postable} == {"u1"}
        assert all(a.status is InstagramAccountStatus.ACTIVE for a in postable)
