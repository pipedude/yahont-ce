"""Yahont managed-model catalog.

The `yahont` provider serves a closed list of models through two OpenAI-compatible
upstreams (routerai.ru and cloud.ru). The list lives in a JSON file on the server
(`YAHONT_LLM_CATALOG_PATH`). Upstream keys and base URLs live in env, never in the
tenant database.

Prices in the file are RUB per 1M tokens. The credit wallet counts USD cents, so
`rub_per_usd` in the file header converts them.
"""

import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from onyx.configs.app_configs import (
    CLOUDRU_DEFAULT_API_BASE,
    CLOUDRU_DEFAULT_API_KEY,
    ROUTERAI_DEFAULT_API_BASE,
    ROUTERAI_DEFAULT_API_KEY,
    YAHONT_LLM_CATALOG_PATH,
)
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.llm.constants import LlmProviderNames
from onyx.utils.logger import setup_logger

logger = setup_logger()

YAHONT_PROVIDER_NAME = LlmProviderNames.YAHONT.value
YAHONT_PROVIDER_DISPLAY_NAME = "Yahont"

# Stored in the provider row instead of an upstream key. It is not a secret: it
# marks the row as managed for every check that compares the key with the
# managed-key set (admission and the gateway read the row key).
YAHONT_MANAGED_KEY_SENTINEL = "yahont-managed-provider"


class YahontUpstream(str, Enum):
    ROUTERAI = "routerai"
    CLOUDRU = "cloudru"


class YahontCatalogError(ValueError):
    """The catalog file is missing or invalid."""


class YahontCatalogModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # What users and billing see. Unique in the file.
    id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    upstream: YahontUpstream
    # The exact model name at the upstream.
    upstream_model: str = Field(min_length=1)
    input_price_rub_per_mtok: float = Field(gt=0)
    output_price_rub_per_mtok: float = Field(gt=0)
    cache_read_price_rub_per_mtok: float | None = Field(default=None, gt=0)
    max_input_tokens: int = Field(gt=0)
    vision: bool
    reasoning: bool
    default: bool


class YahontCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str
    updated_at: str
    rub_per_usd: float = Field(gt=0)
    models: list[YahontCatalogModel] = Field(min_length=1)

    @model_validator(mode="after")
    def _check_models(self) -> "YahontCatalog":
        ids = [model.id for model in self.models]
        duplicates = sorted({model_id for model_id in ids if ids.count(model_id) > 1})
        if duplicates:
            raise ValueError(f"duplicate model ids: {', '.join(duplicates)}")
        default_count = sum(model.default for model in self.models)
        if default_count != 1:
            raise ValueError(
                f"exactly one model must have default=true, found {default_count}"
            )
        return self

    @property
    def default_model(self) -> YahontCatalogModel:
        return next(model for model in self.models if model.default)

    def find(self, model_id: str) -> YahontCatalogModel | None:
        return next((model for model in self.models if model.id == model_id), None)


@dataclass(frozen=True)
class YahontRoute:
    """Where one catalog model is sent: the upstream name, key and base URL."""

    upstream_model: str
    api_key: str
    api_base: str


def load_yahont_catalog(path: str | Path) -> YahontCatalog:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise YahontCatalogError(f"Cannot read Yahont catalog {path}: {e}") from e
    if not isinstance(raw, dict):
        raise YahontCatalogError(f"Yahont catalog {path} must be a JSON object")

    data = {key: value for key, value in raw.items() if not key.startswith("_")}
    try:
        return YahontCatalog.model_validate(data)
    except ValidationError as e:
        raise YahontCatalogError(f"Invalid Yahont catalog {path}: {e}") from e


# path -> (file mtime in ns, parsed catalog). A changed file is read again.
_CACHE: dict[str, tuple[int, YahontCatalog]] = {}


def get_yahont_catalog() -> YahontCatalog | None:
    """The catalog from `YAHONT_LLM_CATALOG_PATH`, or None when it is not set.

    Raises YahontCatalogError when the file is missing or invalid.
    """
    path = YAHONT_LLM_CATALOG_PATH
    if not path:
        return None
    try:
        mtime_ns = Path(path).stat().st_mtime_ns
    except OSError as e:
        raise YahontCatalogError(f"Cannot read Yahont catalog {path}: {e}") from e

    cached = _CACHE.get(path)
    if cached is not None and cached[0] == mtime_ns:
        return cached[1]
    catalog = load_yahont_catalog(path)
    _CACHE[path] = (mtime_ns, catalog)
    return catalog


def _upstream_credentials(upstream: YahontUpstream) -> tuple[str | None, str]:
    if upstream is YahontUpstream.ROUTERAI:
        return ROUTERAI_DEFAULT_API_KEY, ROUTERAI_DEFAULT_API_BASE
    return CLOUDRU_DEFAULT_API_KEY, CLOUDRU_DEFAULT_API_BASE


def _require_catalog() -> YahontCatalog:
    try:
        catalog = get_yahont_catalog()
    except YahontCatalogError as e:
        logger.error("Yahont catalog is unusable: %s", e)
        raise OnyxError(
            OnyxErrorCode.SERVICE_UNAVAILABLE, "Yahont model catalog is invalid"
        ) from e
    if catalog is None:
        raise OnyxError(
            OnyxErrorCode.SERVICE_UNAVAILABLE, "Yahont model catalog is not configured"
        )
    return catalog


def _require_model(catalog: YahontCatalog, model_id: str) -> YahontCatalogModel:
    model = catalog.find(model_id)
    if model is None:
        raise OnyxError(
            OnyxErrorCode.NOT_FOUND, f"Model {model_id!r} is not in the Yahont catalog"
        )
    return model


def yahont_models_with_credentials() -> list[YahontCatalogModel]:
    """Catalog models whose upstream has an API key. Empty without a catalog."""
    catalog = get_yahont_catalog()
    if catalog is None:
        return []
    return [
        model
        for model in catalog.models
        if _upstream_credentials(model.upstream)[0] is not None
    ]


def resolve_yahont_route(model_id: str) -> YahontRoute:
    """Upstream model name, key and base URL for a catalog model.

    A model outside the catalog is refused: the list is closed.
    """
    model = _require_model(_require_catalog(), model_id)
    api_key, api_base = _upstream_credentials(model.upstream)
    if api_key is None:
        raise OnyxError(
            OnyxErrorCode.SERVICE_UNAVAILABLE,
            f"Upstream {model.upstream.value} has no API key configured",
        )
    return YahontRoute(
        upstream_model=model.upstream_model, api_key=api_key, api_base=api_base
    )


def yahont_cost_cents(
    model_id: str,
    prompt_tokens: int,
    completion_tokens: int,
    cache_read_tokens: int = 0,
) -> tuple[float, float]:
    """(input, output) cost in wallet cents (USD cents) for one call.

    `prompt_tokens` is the cache-inclusive total; `cache_read_tokens` is a subset
    of it and is billed at the cache price (the input price when none is set).
    """
    catalog = _require_catalog()
    model = _require_model(catalog, model_id)

    def cents(rub_per_mtok: float, tokens: int) -> float:
        return tokens / 1_000_000 * rub_per_mtok / catalog.rub_per_usd * 100

    cache_tokens = min(cache_read_tokens, prompt_tokens)
    cache_price = model.cache_read_price_rub_per_mtok or model.input_price_rub_per_mtok
    input_cents = cents(
        model.input_price_rub_per_mtok, prompt_tokens - cache_tokens
    ) + cents(cache_price, cache_tokens)
    output_cents = cents(model.output_price_rub_per_mtok, completion_tokens)
    return input_cents, output_cents
