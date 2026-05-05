"""Router /v1 accounts: lectura de cuentas listening + salud + anomaly score.

- ``GET /v1/accounts``: lista paginada con filtro opcional de pais.
- ``GET /v1/accounts/{id}``: detalle.
- ``GET /v1/accounts/{id}/health``: snapshot operacional (state + uso).
- ``GET /v1/accounts/{id}/anomaly_score``: score actual del predictor ML
  (si esta cableado en el container; de lo contrario devuelve un score
  ``LOW`` con ``model_version=disabled``).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Query

from streaming_bot.domain.entities import Account
from streaming_bot.domain.exceptions import DomainError
from streaming_bot.domain.ports import (
    IAccountRepository,
    IStreamHistoryRepository,
)
from streaming_bot.domain.value_objects import Country
from streaming_bot.presentation.api.dependencies import (
    get_account_repository,
    get_container,
    get_stream_history_repository,
    require_role,
)
from streaming_bot.presentation.api.errors import NotFoundError
from streaming_bot.presentation.api.routers._pagination import MAX_LIMIT, paginate
from streaming_bot.presentation.api.schemas import (
    AccountDTO,
    AccountHealthDTO,
    AnomalyScoreDTO,
    FeatureContributionDTO,
    PaginatedResponse,
)

router = APIRouter(
    prefix="/v1/accounts",
    tags=["accounts"],
    dependencies=[Depends(require_role("viewer", "operator", "admin"))],
)


def _account_to_dto(account: Account) -> AccountDTO:
    return AccountDTO(
        id=account.id,
        username=account.username,
        country=account.country.value,
        state=account.status.state,
        state_reason=account.status.reason,
        last_used_at=account.last_used_at,
    )


@router.get(
    "",
    response_model=PaginatedResponse[AccountDTO],
    summary="Lista de cuentas listening",
    description=(
        "Devuelve las cuentas registradas en el pool. Filtros opcionales: "
        "country (ISO-3166 alpha-2), state (active|banned|rate_limited)."
    ),
)
async def list_accounts(
    accounts_repo: Annotated[IAccountRepository, Depends(get_account_repository)],
    country: Annotated[
        str | None,
        Query(description="Filtra por country code (PE, MX, US...)."),
    ] = None,
    state: Annotated[
        str | None,
        Query(description="Filtra por estado de la cuenta."),
    ] = None,
    cursor: Annotated[str | None, Query(description="Cursor opaco")] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = 50,
) -> PaginatedResponse[AccountDTO]:
    accounts = await accounts_repo.all()
    if country is not None:
        try:
            target_country = Country(country.upper())
        except ValueError as exc:
            raise NotFoundError("country", country) from exc
        accounts = [acc for acc in accounts if acc.country == target_country]
    if state is not None:
        normalized = state.lower()
        accounts = [acc for acc in accounts if acc.status.state == normalized]
    return paginate(accounts, limit=limit, cursor=cursor, map_item=_account_to_dto)


@router.get(
    "/{account_id}",
    response_model=AccountDTO,
    summary="Detalle de cuenta",
    description="Devuelve la cuenta por id. 404 si no existe.",
)
async def get_account(
    account_id: Annotated[str, Path(description="UUID de la cuenta")],
    accounts_repo: Annotated[IAccountRepository, Depends(get_account_repository)],
) -> AccountDTO:
    try:
        account = await accounts_repo.get(account_id)
    except DomainError as exc:
        raise NotFoundError("account", account_id) from exc
    return _account_to_dto(account)


@router.get(
    "/{account_id}/health",
    response_model=AccountHealthDTO,
    summary="Salud operacional de la cuenta",
    description=(
        "Snapshot ligero: estado activo/baneado, uso reciente y conteo "
        "de streams del dia. Util para quick-check del operator."
    ),
)
async def account_health(
    account_id: Annotated[str, Path(description="UUID de la cuenta")],
    accounts_repo: Annotated[IAccountRepository, Depends(get_account_repository)],
    history_repo: Annotated[
        IStreamHistoryRepository,
        Depends(get_stream_history_repository),
    ],
) -> AccountHealthDTO:
    try:
        account = await accounts_repo.get(account_id)
    except DomainError as exc:
        raise NotFoundError("account", account_id) from exc
    streams_today = await history_repo.count_for_account_today(account_id)
    return AccountHealthDTO(
        account_id=account.id,
        state=account.status.state,
        is_usable=account.status.is_usable,
        last_used_at=account.last_used_at,
        streams_today=streams_today,
        notes=account.status.reason,
    )


def _resolve_predictor(container: Any) -> Any | None:
    """Devuelve el ``IAnomalyPredictor`` si el container lo expone.

    Centralizado para que el endpoint funcione tanto cuando el ML stack
    esta cableado como cuando no (modo dev). Tests inyectan el predictor
    sobreescribiendo este modulo o dependiendo del container fake.
    """
    return getattr(container, "anomaly_predictor", None)


@router.get(
    "/{account_id}/anomaly_score",
    response_model=AnomalyScoreDTO,
    summary="Score de anomalia ML para la cuenta",
    description=(
        "Devuelve el score actual del predictor LightGBM (probabilidad "
        "calibrada de baneo en proximas 48h) junto al risk_level y top "
        "features SHAP. Cuando el predictor no esta configurado responde "
        "un score 0.0 con risk_level=low y model_version=disabled."
    ),
)
async def account_anomaly_score(
    account_id: Annotated[str, Path(description="UUID de la cuenta")],
    accounts_repo: Annotated[IAccountRepository, Depends(get_account_repository)],
    container: Annotated[Any, Depends(get_container)],
) -> AnomalyScoreDTO:
    try:
        await accounts_repo.get(account_id)
    except DomainError as exc:
        raise NotFoundError("account", account_id) from exc

    predictor = _resolve_predictor(container)
    if predictor is None:
        return AnomalyScoreDTO(
            account_id=account_id,
            score=0.0,
            risk_level="low",
            computed_at=datetime.now(UTC),
            top_features=[],
            model_version="disabled",
        )
    score = await predictor.predict_for_account(account_id)
    return AnomalyScoreDTO(
        account_id=score.account_id,
        score=score.score,
        risk_level=score.risk_level.value,
        computed_at=score.computed_at,
        top_features=[
            FeatureContributionDTO(
                feature_name=f.feature_name,
                contribution=f.contribution,
            )
            for f in score.top_features
        ],
        model_version=score.model_version,
    )
