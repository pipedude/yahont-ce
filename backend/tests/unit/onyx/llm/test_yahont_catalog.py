"""Unit tests for the Yahont managed-model catalog.

The catalog is a JSON file on the server. It lists the only models the `yahont`
provider serves, the upstream each one is routed to, and its price in RUB per
1M tokens. These tests pin the validation rules, the RUB -> wallet-cents
conversion and the per-model upstream routing.
"""

import json
import os
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.llm import yahont_catalog
from onyx.llm.yahont_catalog import (
    YAHONT_PROVIDER_NAME,
    YahontCatalogError,
    get_yahont_catalog,
    load_yahont_catalog,
    resolve_yahont_route,
    yahont_cost_cents,
    yahont_models_with_credentials,
)


def _model(**overrides: Any) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "id": "google/gemini-3.8-flash",
        "display_name": "Gemini 3.8 Flash",
        "upstream": "routerai",
        "upstream_model": "google/gemini-3.8-flash",
        "input_price_rub_per_mtok": 10.0,
        "output_price_rub_per_mtok": 40.0,
        "cache_read_price_rub_per_mtok": None,
        "max_input_tokens": 1000000,
        "vision": True,
        "reasoning": True,
        "default": True,
    }
    entry.update(overrides)
    return entry


def _catalog_dict(
    models: list[dict[str, Any]] | None = None, **overrides: Any
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "_comment": "ignored by the loader",
        "version": "1",
        "updated_at": "2026-10-01",
        "rub_per_usd": 100.0,
        "models": models
        if models is not None
        else [
            _model(),
            _model(
                id="openai/gpt-oss-120b",
                display_name="GPT-OSS 120B",
                upstream="cloudru",
                upstream_model="openai/gpt-oss-120b",
                max_input_tokens=131072,
                vision=False,
                default=False,
            ),
        ],
    }
    data.update(overrides)
    return data


def _write(tmp_path: Path, data: Any) -> Path:
    path = tmp_path / "yahont-llm-catalog.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_provider_name_is_yahont() -> None:
    assert YAHONT_PROVIDER_NAME == "yahont"


def test_loads_valid_catalog_and_ignores_underscore_fields(tmp_path: Path) -> None:
    catalog = load_yahont_catalog(_write(tmp_path, _catalog_dict()))

    assert [m.id for m in catalog.models] == [
        "google/gemini-3.8-flash",
        "openai/gpt-oss-120b",
    ]
    assert catalog.rub_per_usd == 100.0
    assert catalog.default_model.id == "google/gemini-3.8-flash"
    assert catalog.models[0].cache_read_price_rub_per_mtok is None


@pytest.mark.parametrize(
    "field",
    [
        "id",
        "display_name",
        "upstream",
        "upstream_model",
        "input_price_rub_per_mtok",
        "output_price_rub_per_mtok",
        "max_input_tokens",
        "vision",
        "reasoning",
        "default",
    ],
)
def test_unfilled_required_field_rejects_the_file(tmp_path: Path, field: str) -> None:
    data = _catalog_dict(models=[_model(**{field: None})])

    with pytest.raises(YahontCatalogError):
        load_yahont_catalog(_write(tmp_path, data))


def test_unfilled_rate_rejects_the_file(tmp_path: Path) -> None:
    with pytest.raises(YahontCatalogError):
        load_yahont_catalog(_write(tmp_path, _catalog_dict(rub_per_usd=None)))


@pytest.mark.parametrize("rate", [0, -1, -88.3])
def test_non_positive_rate_rejects_the_file(tmp_path: Path, rate: float) -> None:
    with pytest.raises(YahontCatalogError):
        load_yahont_catalog(_write(tmp_path, _catalog_dict(rub_per_usd=rate)))


@pytest.mark.parametrize(
    "field", ["input_price_rub_per_mtok", "output_price_rub_per_mtok"]
)
@pytest.mark.parametrize("value", [0, -1.5])
def test_non_positive_price_rejects_the_file(
    tmp_path: Path, field: str, value: float
) -> None:
    data = _catalog_dict(models=[_model(**{field: value})])

    with pytest.raises(YahontCatalogError):
        load_yahont_catalog(_write(tmp_path, data))


def test_non_positive_context_rejects_the_file(tmp_path: Path) -> None:
    data = _catalog_dict(models=[_model(max_input_tokens=0)])

    with pytest.raises(YahontCatalogError):
        load_yahont_catalog(_write(tmp_path, data))


def test_non_positive_cache_price_rejects_the_file(tmp_path: Path) -> None:
    data = _catalog_dict(models=[_model(cache_read_price_rub_per_mtok=0)])

    with pytest.raises(YahontCatalogError):
        load_yahont_catalog(_write(tmp_path, data))


def test_duplicate_ids_reject_the_file(tmp_path: Path) -> None:
    data = _catalog_dict(models=[_model(), _model(default=False)])

    with pytest.raises(YahontCatalogError, match="duplicate"):
        load_yahont_catalog(_write(tmp_path, data))


@pytest.mark.parametrize("defaults", [(False, False), (True, True)])
def test_exactly_one_default_is_required(
    tmp_path: Path, defaults: tuple[bool, bool]
) -> None:
    data = _catalog_dict(
        models=[
            _model(default=defaults[0]),
            _model(id="other/model", default=defaults[1]),
        ]
    )

    with pytest.raises(YahontCatalogError, match="default"):
        load_yahont_catalog(_write(tmp_path, data))


def test_unknown_upstream_rejects_the_file(tmp_path: Path) -> None:
    data = _catalog_dict(models=[_model(upstream="openai")])

    with pytest.raises(YahontCatalogError):
        load_yahont_catalog(_write(tmp_path, data))


def test_unknown_model_field_rejects_the_file(tmp_path: Path) -> None:
    data = _catalog_dict(models=[_model(input_price_rub_per_mtok_typo=1.0)])

    with pytest.raises(YahontCatalogError):
        load_yahont_catalog(_write(tmp_path, data))


def test_empty_model_list_rejects_the_file(tmp_path: Path) -> None:
    with pytest.raises(YahontCatalogError):
        load_yahont_catalog(_write(tmp_path, _catalog_dict(models=[])))


def test_missing_file_rejects(tmp_path: Path) -> None:
    with pytest.raises(YahontCatalogError):
        load_yahont_catalog(tmp_path / "absent.json")


def test_invalid_json_rejects(tmp_path: Path) -> None:
    path = tmp_path / "yahont-llm-catalog.json"
    path.write_text("{not json", encoding="utf-8")

    with pytest.raises(YahontCatalogError):
        load_yahont_catalog(path)


def test_get_catalog_is_none_when_path_is_not_configured() -> None:
    with patch.object(yahont_catalog, "YAHONT_LLM_CATALOG_PATH", None):
        assert get_yahont_catalog() is None


def test_get_catalog_reloads_when_the_file_changes(tmp_path: Path) -> None:
    path = _write(tmp_path, _catalog_dict())
    with patch.object(yahont_catalog, "YAHONT_LLM_CATALOG_PATH", str(path)):
        first = get_yahont_catalog()
        assert first is not None
        assert first.rub_per_usd == 100.0

        data = _catalog_dict(rub_per_usd=90.0)
        path.write_text(json.dumps(data), encoding="utf-8")
        stat = path.stat()
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 5_000_000_000))

        second = get_yahont_catalog()
        assert second is not None
        assert second.rub_per_usd == 90.0


def test_get_catalog_raises_on_a_broken_file(tmp_path: Path) -> None:
    path = _write(tmp_path, _catalog_dict(rub_per_usd=None))
    with patch.object(yahont_catalog, "YAHONT_LLM_CATALOG_PATH", str(path)):
        with pytest.raises(YahontCatalogError):
            get_yahont_catalog()


def _loaded(tmp_path: Path, data: dict[str, Any] | None = None):  # noqa: ANN202
    return load_yahont_catalog(_write(tmp_path, data or _catalog_dict()))


def test_cost_converts_rub_per_mtok_to_wallet_cents(tmp_path: Path) -> None:
    # 100 RUB per USD. Input 200 RUB/Mtok = 2 USD/Mtok, output 400 RUB/Mtok.
    catalog = _loaded(
        tmp_path,
        _catalog_dict(
            models=[
                _model(
                    input_price_rub_per_mtok=200.0,
                    output_price_rub_per_mtok=400.0,
                )
            ]
        ),
    )
    with patch.object(yahont_catalog, "get_yahont_catalog", return_value=catalog):
        input_cents, output_cents = yahont_cost_cents(
            "google/gemini-3.8-flash",
            prompt_tokens=1_000_000,
            completion_tokens=500_000,
        )

    assert input_cents == pytest.approx(200.0)
    assert output_cents == pytest.approx(200.0)


def test_cost_prices_cache_reads_at_the_cache_price(tmp_path: Path) -> None:
    catalog = _loaded(
        tmp_path,
        _catalog_dict(
            models=[
                _model(
                    input_price_rub_per_mtok=200.0,
                    cache_read_price_rub_per_mtok=20.0,
                )
            ]
        ),
    )
    with patch.object(yahont_catalog, "get_yahont_catalog", return_value=catalog):
        input_cents, _ = yahont_cost_cents(
            "google/gemini-3.8-flash",
            prompt_tokens=1_000_000,
            completion_tokens=0,
            cache_read_tokens=400_000,
        )

    # 600k at 2 USD/Mtok + 400k at 0.2 USD/Mtok = 1.28 USD.
    assert input_cents == pytest.approx(128.0)


def test_cost_without_cache_price_bills_cache_reads_as_input(tmp_path: Path) -> None:
    catalog = _loaded(
        tmp_path,
        _catalog_dict(models=[_model(input_price_rub_per_mtok=200.0)]),
    )
    with patch.object(yahont_catalog, "get_yahont_catalog", return_value=catalog):
        input_cents, _ = yahont_cost_cents(
            "google/gemini-3.8-flash",
            prompt_tokens=1_000_000,
            completion_tokens=0,
            cache_read_tokens=400_000,
        )

    assert input_cents == pytest.approx(200.0)


def test_cost_for_a_model_outside_the_catalog_raises(tmp_path: Path) -> None:
    catalog = _loaded(tmp_path)
    with patch.object(yahont_catalog, "get_yahont_catalog", return_value=catalog):
        with pytest.raises(OnyxError) as excinfo:
            yahont_cost_cents("no/such-model", prompt_tokens=1, completion_tokens=1)

    assert excinfo.value.error_code is OnyxErrorCode.NOT_FOUND


def _credentials() -> Any:
    return patch.multiple(
        yahont_catalog,
        ROUTERAI_DEFAULT_API_KEY="router-key",
        ROUTERAI_DEFAULT_API_BASE="https://routerai.example/api/v1",
        CLOUDRU_DEFAULT_API_KEY="cloud-key",
        CLOUDRU_DEFAULT_API_BASE="https://cloud.example/v1",
    )


def test_route_sends_each_model_to_its_own_upstream(tmp_path: Path) -> None:
    catalog = _loaded(tmp_path)
    with (
        _credentials(),
        patch.object(yahont_catalog, "get_yahont_catalog", return_value=catalog),
    ):
        router_route = resolve_yahont_route("google/gemini-3.8-flash")
        cloud_route = resolve_yahont_route("openai/gpt-oss-120b")

    assert router_route.upstream_model == "google/gemini-3.8-flash"
    assert router_route.api_key == "router-key"
    assert router_route.api_base == "https://routerai.example/api/v1"
    assert cloud_route.upstream_model == "openai/gpt-oss-120b"
    assert cloud_route.api_key == "cloud-key"
    assert cloud_route.api_base == "https://cloud.example/v1"


def test_route_uses_the_upstream_name_not_the_catalog_id(tmp_path: Path) -> None:
    data = _catalog_dict(
        models=[_model(id="yahont/fast", upstream_model="google/gemini-3.8-flash")]
    )
    catalog = _loaded(tmp_path, data)
    with (
        _credentials(),
        patch.object(yahont_catalog, "get_yahont_catalog", return_value=catalog),
    ):
        route = resolve_yahont_route("yahont/fast")

    assert route.upstream_model == "google/gemini-3.8-flash"


def test_route_refuses_a_model_outside_the_catalog(tmp_path: Path) -> None:
    catalog = _loaded(tmp_path)
    with (
        _credentials(),
        patch.object(yahont_catalog, "get_yahont_catalog", return_value=catalog),
    ):
        with pytest.raises(OnyxError) as excinfo:
            resolve_yahont_route("anthropic/claude-opus-5")

    assert excinfo.value.error_code is OnyxErrorCode.NOT_FOUND


def test_route_refuses_when_the_upstream_has_no_key(tmp_path: Path) -> None:
    catalog = _loaded(tmp_path)
    with (
        patch.multiple(
            yahont_catalog,
            ROUTERAI_DEFAULT_API_KEY=None,
            ROUTERAI_DEFAULT_API_BASE="https://routerai.example/api/v1",
        ),
        patch.object(yahont_catalog, "get_yahont_catalog", return_value=catalog),
    ):
        with pytest.raises(OnyxError) as excinfo:
            resolve_yahont_route("google/gemini-3.8-flash")

    assert excinfo.value.error_code is OnyxErrorCode.SERVICE_UNAVAILABLE


def test_route_refuses_when_no_catalog_is_configured() -> None:
    with patch.object(yahont_catalog, "get_yahont_catalog", return_value=None):
        with pytest.raises(OnyxError) as excinfo:
            resolve_yahont_route("google/gemini-3.8-flash")

    assert excinfo.value.error_code is OnyxErrorCode.SERVICE_UNAVAILABLE


def test_models_with_credentials_skips_upstreams_without_a_key(
    tmp_path: Path,
) -> None:
    catalog = _loaded(tmp_path)
    with (
        patch.multiple(
            yahont_catalog,
            ROUTERAI_DEFAULT_API_KEY="router-key",
            CLOUDRU_DEFAULT_API_KEY=None,
        ),
        patch.object(yahont_catalog, "get_yahont_catalog", return_value=catalog),
    ):
        models = yahont_models_with_credentials()

    assert [m.id for m in models] == ["google/gemini-3.8-flash"]


def test_models_with_credentials_is_empty_without_a_catalog() -> None:
    with patch.object(yahont_catalog, "get_yahont_catalog", return_value=None):
        assert yahont_models_with_credentials() == []
