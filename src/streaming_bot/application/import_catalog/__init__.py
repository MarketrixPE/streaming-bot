"""Pipeline de import de catalogos multi-distribuidor.

Punto de entrada publico de la feature: parsers heterogeneos, clasificador
de tier, upserters cacheados y servicio orquestador.
"""

from streaming_bot.application.import_catalog.import_service import (
    ImportCatalogService,
    ImportSummary,
    summarize_by_tier,
)
from streaming_bot.application.import_catalog.parsers import (
    AiComParser,
    DistributorParserDetector,
    DistroKidParser,
    GenericCsvParser,
    IDistributorParser,
    OneRpmParser,
    ParsedCatalogRow,
)
from streaming_bot.application.import_catalog.tier_classifier import (
    TierClassifier,
    load_flagged_oct2025,
)
from streaming_bot.application.import_catalog.upsert import (
    ArtistUpserter,
    LabelUpserter,
    UpsertStats,
)

__all__ = [
    "AiComParser",
    "ArtistUpserter",
    "DistributorParserDetector",
    "DistroKidParser",
    "GenericCsvParser",
    "IDistributorParser",
    "ImportCatalogService",
    "ImportSummary",
    "LabelUpserter",
    "OneRpmParser",
    "ParsedCatalogRow",
    "TierClassifier",
    "UpsertStats",
    "load_flagged_oct2025",
    "summarize_by_tier",
]
