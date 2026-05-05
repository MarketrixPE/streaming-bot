"""Resolutor de aliases artist-name por (track, distribuidor).

Reglas:
1. Si existe un alias persistido para (track_id, distributor) -> reutilizarlo.
2. Si no, generar uno nuevo deterministico a partir de un seed para que dos
   ejecuciones distintas con la misma policy produzcan el mismo nombre (util
   en pipelines reproducibles y en tests).
3. Persistir el nuevo alias para futuras llamadas.

Naming template default: "<Adjetivo> <Sustantivo>" (ej. "Cosmic Beats").
Se evita usar el nombre real del catalogo para no correlacionar releases
entre distribuidores en buscadores publicos / DSPs.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from streaming_bot.application.distribution.policy import DispatchPolicy
from streaming_bot.domain.distribution.distributor_id import DistributorId
from streaming_bot.domain.distribution.release import ArtistAlias
from streaming_bot.domain.ports.distributor_dispatcher import IArtistAliasRepository


@dataclass(frozen=True, slots=True)
class ResolvedAlias:
    """Alias devuelto al caller, con flag de si fue creado o reutilizado."""

    alias: ArtistAlias
    created: bool


class AliasNamingTemplate:
    """Genera nombres "<Adjetivo> <Sustantivo>" de forma deterministica.

    El determinismo viene de hashear (track_id, distributor, optional_seed),
    de modo que la misma tupla siempre produce el mismo alias incluso entre
    procesos distintos (no depende del orden de imports ni del estado de un
    RNG global).
    """

    def __init__(
        self,
        *,
        adjectives: tuple[str, ...],
        nouns: tuple[str, ...],
        seed: int | None = None,
    ) -> None:
        if not adjectives or not nouns:
            raise ValueError("adjectives y nouns no pueden estar vacios")
        self._adjectives = adjectives
        self._nouns = nouns
        self._seed = seed or 0

    def build_name(self, *, track_id: str, distributor: DistributorId) -> str:
        """Construye el nombre a partir de hash(track_id|distributor|seed)."""
        digest = hashlib.sha256(
            f"{self._seed}|{distributor.value}|{track_id}".encode(),
        ).digest()
        adj_index = int.from_bytes(digest[:8], "big") % len(self._adjectives)
        noun_index = int.from_bytes(digest[8:16], "big") % len(self._nouns)
        adj = self._adjectives[adj_index]
        noun = self._nouns[noun_index]
        # Sufijo de 2 hex chars del hash: reduce probabilidad de colision a ~1/256
        # cuando dos tracks comparten (adj, noun) en el mismo distribuidor.
        suffix = digest[16:17].hex().upper()
        return f"{adj} {noun} {suffix}"


class AliasResolver:
    """Resuelve y persiste el alias artist-name por (track, distributor).

    Dependencias:
    - alias_repo: persiste/lee aliases.
    - policy: provee pools de adjetivos/sustantivos y label_name por defecto.

    Uso tipico:
        resolver = AliasResolver(alias_repo=repo, policy=policy)
        resolved = await resolver.resolve(track_id="t1", distributor=DistroKid)
        release.artist_name = resolved.alias.alias_name
    """

    def __init__(
        self,
        *,
        alias_repo: IArtistAliasRepository,
        policy: DispatchPolicy,
    ) -> None:
        self._repo = alias_repo
        self._policy = policy

    async def resolve(
        self,
        *,
        track_id: str,
        distributor: DistributorId,
    ) -> ResolvedAlias:
        existing = await self._repo.get(track_id=track_id, distributor=distributor)
        if existing is not None:
            return ResolvedAlias(alias=existing, created=False)

        alias_name = self._build_name(track_id=track_id, distributor=distributor)
        new_alias = ArtistAlias(
            track_id=track_id,
            distributor=distributor,
            alias_name=alias_name,
            label_name=self._policy.label_name,
        )
        await self._repo.save(new_alias)
        return ResolvedAlias(alias=new_alias, created=True)

    def _build_name(self, *, track_id: str, distributor: DistributorId) -> str:
        # Pool dedicado al distribuidor si la policy lo declara, para reforzar
        # decorrelacion (cada distro habla de un "vocabulario" distinto).
        dedicated = self._policy.alias_pool_for(distributor)
        if dedicated:
            template = AliasNamingTemplate(
                adjectives=dedicated,
                nouns=self._policy.alias_noun_pool,
                seed=self._policy.rng_seed,
            )
        else:
            template = AliasNamingTemplate(
                adjectives=self._policy.alias_adjective_pool,
                nouns=self._policy.alias_noun_pool,
                seed=self._policy.rng_seed,
            )
        return template.build_name(track_id=track_id, distributor=distributor)
