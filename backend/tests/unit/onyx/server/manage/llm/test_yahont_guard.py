"""Tenant admins cannot change the platform-managed `yahont` provider.

The admin form is only a client: any admin can call the API directly, so the
server enforces the rules. An admin may rename the provider, choose which of
its models are visible, tune per-model reasoning and temperature, and set who
has access. Everything else stays as provisioned from the catalog.
"""

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from onyx.db.enums import LLMModelFlowType
from onyx.db.llm import sync_model_configurations
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.llm.models import ReasoningEffort
from onyx.llm.yahont_catalog import YAHONT_MANAGED_KEY_SENTINEL, YAHONT_PROVIDER_NAME
from onyx.server.manage.llm import api as llm_api
from onyx.server.manage.llm.models import (
    LLMProviderUpsertRequest,
    ModelConfigurationUpsertRequest,
    TestLLMRequest,
)
from onyx.server.manage.llm.yahont_guard import guard_yahont_upsert


def _stored_model(name: str, **overrides: Any) -> MagicMock:
    model = MagicMock()
    model.name = name
    model.is_visible = True
    model.max_input_tokens = 131072
    model.supports_image_input = False
    model.llm_model_flow_types = [LLMModelFlowType.CHAT, LLMModelFlowType.REASONING]
    model.display_name = f"{name} display"
    model.custom_display_name = None
    model.reasoning_effort_max = None
    model.reasoning_effort_default = None
    model.temperature_default = None
    for key, value in overrides.items():
        setattr(model, key, value)
    return model


def _yahont_row() -> MagicMock:
    row = MagicMock()
    row.id = 7
    row.name = "Yahont"
    row.provider = YAHONT_PROVIDER_NAME
    row.api_base = None
    row.api_version = None
    row.deployment_name = None
    row.custom_config = None
    row.is_auto_mode = False
    row.model_configurations = [_stored_model("a/model-a"), _stored_model("b/model-b")]
    return row


def _admin_request(**overrides: Any) -> LLMProviderUpsertRequest:
    fields: dict[str, Any] = {
        "id": 7,
        "name": "Yahont",
        "provider": YAHONT_PROVIDER_NAME,
        "api_key": YAHONT_MANAGED_KEY_SENTINEL,
        "model_configurations": [
            ModelConfigurationUpsertRequest(name="a/model-a", is_visible=True),
            ModelConfigurationUpsertRequest(name="b/model-b", is_visible=True),
        ],
    }
    fields.update(overrides)
    return LLMProviderUpsertRequest(**fields)


def _assert_forbidden(excinfo: pytest.ExceptionInfo[OnyxError]) -> None:
    assert excinfo.value.error_code is OnyxErrorCode.INSUFFICIENT_PERMISSIONS


def test_admin_cannot_create_an_yahont_provider() -> None:
    with pytest.raises(OnyxError) as excinfo:
        guard_yahont_upsert(_admin_request(id=None), existing_provider=None)

    _assert_forbidden(excinfo)


def test_admin_cannot_turn_another_provider_into_yahont() -> None:
    other = _yahont_row()
    other.provider = "openai"

    with pytest.raises(OnyxError) as excinfo:
        guard_yahont_upsert(_admin_request(), existing_provider=other)

    _assert_forbidden(excinfo)


def test_admin_cannot_turn_yahont_into_another_provider() -> None:
    with pytest.raises(OnyxError) as excinfo:
        guard_yahont_upsert(
            _admin_request(provider="openai"), existing_provider=_yahont_row()
        )

    _assert_forbidden(excinfo)


def test_other_providers_are_not_restricted() -> None:
    request = _admin_request(
        provider="openai",
        api_base="https://tenant.example/v1",
        api_key="tenant-key",
        api_key_changed=True,
    )
    existing = _yahont_row()
    existing.provider = "openai"

    guard_yahont_upsert(request, existing_provider=existing)

    assert request.api_base == "https://tenant.example/v1"
    assert request.api_key_changed is True


def test_connection_fields_are_reset_to_the_stored_values() -> None:
    request = _admin_request(
        api_base="https://evil.example/v1",
        api_version="2099-01-01",
        api_key="stolen-or-forged",
        api_key_changed=True,
        custom_config={"x": "y"},
        custom_config_changed=True,
        deployment_name="evil-deployment",
        is_auto_mode=True,
    )

    guard_yahont_upsert(request, existing_provider=_yahont_row())

    assert request.api_base is None
    assert request.api_version is None
    assert request.api_key_changed is False
    assert request.custom_config is None
    assert request.custom_config_changed is False
    assert request.deployment_name is None
    assert request.is_auto_mode is False


def test_the_model_list_cannot_gain_or_lose_models() -> None:
    request = _admin_request(
        model_configurations=[
            ModelConfigurationUpsertRequest(name="a/model-a", is_visible=True),
            ModelConfigurationUpsertRequest(name="evil/model", is_visible=True),
        ],
        keep_existing_models=False,
    )

    guard_yahont_upsert(request, existing_provider=_yahont_row())

    assert [m.name for m in request.model_configurations] == [
        "a/model-a",
        "b/model-b",
    ]


def test_admin_may_choose_which_models_are_visible() -> None:
    request = _admin_request(
        model_configurations=[
            ModelConfigurationUpsertRequest(name="a/model-a", is_visible=False),
            ModelConfigurationUpsertRequest(name="b/model-b", is_visible=True),
        ]
    )

    guard_yahont_upsert(request, existing_provider=_yahont_row())

    visibility = {m.name: m.is_visible for m in request.model_configurations}
    assert visibility == {"a/model-a": False, "b/model-b": True}


def test_admin_may_tune_reasoning_temperature_and_display_name() -> None:
    request = _admin_request(
        model_configurations=[
            ModelConfigurationUpsertRequest(
                name="a/model-a",
                is_visible=True,
                reasoning_effort_max=ReasoningEffort.HIGH,
                reasoning_effort_default=ReasoningEffort.MEDIUM,
                temperature_default=0.3,
                custom_display_name="Fast model",
            ),
        ]
    )

    guard_yahont_upsert(request, existing_provider=_yahont_row())

    tuned = next(m for m in request.model_configurations if m.name == "a/model-a")
    assert tuned.reasoning_effort_max is ReasoningEffort.HIGH
    assert tuned.reasoning_effort_default is ReasoningEffort.MEDIUM
    assert tuned.temperature_default == 0.3
    assert tuned.custom_display_name == "Fast model"


def test_catalog_model_properties_cannot_be_changed() -> None:
    request = _admin_request(
        model_configurations=[
            ModelConfigurationUpsertRequest(
                name="a/model-a",
                is_visible=True,
                max_input_tokens=9_999_999,
                supports_image_input=True,
                supports_reasoning=False,
                display_name="Renamed by admin",
            ),
        ]
    )

    guard_yahont_upsert(request, existing_provider=_yahont_row())

    kept = next(m for m in request.model_configurations if m.name == "a/model-a")
    assert kept.max_input_tokens == 131072
    assert kept.supports_image_input is False
    assert kept.supports_reasoning is True
    assert kept.display_name == "a/model-a display"


def test_admin_may_rename_the_provider_and_set_access() -> None:
    request = _admin_request(
        name="Team models", is_public=False, groups=[3], personas=[5]
    )

    guard_yahont_upsert(request, existing_provider=_yahont_row())

    assert request.name == "Team models"
    assert request.is_public is False
    assert request.groups == [3]
    assert request.personas == [5]


def test_put_refuses_to_create_an_yahont_provider() -> None:
    with (
        patch("onyx.server.manage.llm.api.fetch_existing_llm_provider_by_id"),
        pytest.raises(OnyxError) as excinfo,
    ):
        llm_api.put_llm_provider(
            llm_provider_upsert_request=_admin_request(id=None),
            is_creation=True,
            user=MagicMock(),
            db_session=MagicMock(),
        )

    _assert_forbidden(excinfo)


def test_delete_refuses_to_remove_the_yahont_provider() -> None:
    with (
        patch(
            "onyx.server.manage.llm.api.fetch_existing_llm_provider_by_id",
            return_value=_yahont_row(),
        ),
        patch("onyx.server.manage.llm.api.remove_llm_provider") as remove,
        pytest.raises(OnyxError) as excinfo,
    ):
        llm_api.delete_llm_provider(
            provider_id=7, force=True, user=MagicMock(), db_session=MagicMock()
        )

    _assert_forbidden(excinfo)
    remove.assert_not_called()


def test_test_endpoint_refuses_the_yahont_provider() -> None:
    request = TestLLMRequest(
        provider=YAHONT_PROVIDER_NAME,
        model="a/model-a",
        api_key_changed=False,
        custom_config_changed=False,
    )
    with (
        patch("onyx.server.manage.llm.api.get_llm") as get_llm,
        pytest.raises(OnyxError) as excinfo,
    ):
        llm_api.test_llm_configuration(
            test_llm_request=request, _=MagicMock(), db_session=MagicMock()
        )

    _assert_forbidden(excinfo)
    get_llm.assert_not_called()


def test_fetched_models_are_never_synced_into_the_yahont_provider() -> None:
    with patch(
        "onyx.db.llm.fetch_existing_llm_provider_by_id", return_value=_yahont_row()
    ):
        with pytest.raises(ValueError, match="managed"):
            sync_model_configurations(
                db_session=MagicMock(), provider_id=7, models=[MagicMock()]
            )


def test_contextual_cost_skips_the_yahont_provider() -> None:
    with (
        patch(
            "onyx.server.manage.llm.api.fetch_existing_llm_providers",
            return_value=[_yahont_row()],
        ),
        patch("onyx.server.manage.llm.api.get_llm") as get_llm,
    ):
        costs = llm_api.get_provider_contextual_cost(
            _=MagicMock(), db_session=MagicMock()
        )

    assert costs == []
    get_llm.assert_not_called()
