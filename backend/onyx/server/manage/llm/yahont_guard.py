"""Server-side rules for the platform-managed `yahont` provider.

The provider is created by tenant provisioning from the Yahont catalog. A tenant
admin may rename it, choose which of its models are visible, tune per-model
reasoning and temperature, and set who has access. Everything else (type,
connection, the model list and the catalog properties of each model) stays as
provisioned. The admin form hides the other fields, but the form is only a
client, so the API enforces the rules.
"""

from onyx.db.models import LLMProvider as LLMProviderModel
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.llm.yahont_catalog import YAHONT_PROVIDER_NAME
from onyx.server.manage.llm.models import (
    LLMProviderUpsertRequest,
    ModelConfigurationUpsertRequest,
)

_MANAGED_MESSAGE = (
    "The Yahont provider is managed by the platform and cannot be changed this way"
)


def forbid_yahont_provider(provider_type: str | None) -> None:
    if provider_type == YAHONT_PROVIDER_NAME:
        raise OnyxError(OnyxErrorCode.INSUFFICIENT_PERMISSIONS, _MANAGED_MESSAGE)


def guard_yahont_upsert(
    request: LLMProviderUpsertRequest, existing_provider: LLMProviderModel | None
) -> None:
    """Refuse to create or retype an `yahont` provider and restrict edits to it.

    Mutates `request` so only the allowed changes reach the database.
    """
    if existing_provider is None or existing_provider.provider != YAHONT_PROVIDER_NAME:
        forbid_yahont_provider(request.provider)
        return
    if request.provider != YAHONT_PROVIDER_NAME:
        raise OnyxError(OnyxErrorCode.INSUFFICIENT_PERMISSIONS, _MANAGED_MESSAGE)

    request.api_base = existing_provider.api_base
    request.api_version = existing_provider.api_version
    request.api_key_changed = False
    request.custom_config = existing_provider.custom_config
    request.custom_config_changed = False
    request.deployment_name = existing_provider.deployment_name
    request.is_auto_mode = existing_provider.is_auto_mode
    request.keep_existing_models = False

    sent_by_name = {mc.name: mc for mc in request.model_configurations}
    restricted: list[ModelConfigurationUpsertRequest] = []
    for stored in existing_provider.model_configurations:
        model = ModelConfigurationUpsertRequest.from_model(stored)
        sent = sent_by_name.get(stored.name)
        if sent is not None:
            # The tunable fields apply only when the request sends them, so an
            # older client that omits one cannot clear an admin's value.
            model.is_visible = sent.is_visible
            sent_fields = sent.model_fields_set
            if "custom_display_name" in sent_fields:
                model.custom_display_name = sent.custom_display_name
            if "reasoning_effort_max" in sent_fields:
                model.reasoning_effort_max = sent.reasoning_effort_max
            if "reasoning_effort_default" in sent_fields:
                model.reasoning_effort_default = sent.reasoning_effort_default
            if "temperature_default" in sent_fields:
                model.temperature_default = sent.temperature_default
        restricted.append(model)
    request.model_configurations = restricted
