"""Casos de uso de distribucion multi-distribuidor.

Orquestacion del envio de cada track a >=2 distribuidores con artist-name
distinto para resistir takedowns concentrados.
"""

from streaming_bot.application.distribution.alias_resolver import (
    AliasNamingTemplate,
    AliasResolver,
    ResolvedAlias,
)
from streaming_bot.application.distribution.dispatch_use_case import (
    ConcentrationCapExceededError,
    DispatchOutcome,
    DispatchResult,
    DispatchTrackRequest,
    InsufficientDistributorsError,
    MultiDistributorDispatchUseCase,
)
from streaming_bot.application.distribution.policy import DispatchPolicy

__all__ = [
    "AliasNamingTemplate",
    "AliasResolver",
    "ConcentrationCapExceededError",
    "DispatchOutcome",
    "DispatchPolicy",
    "DispatchResult",
    "DispatchTrackRequest",
    "InsufficientDistributorsError",
    "MultiDistributorDispatchUseCase",
    "ResolvedAlias",
]
