"""The default local embedding model and the settings that depend on it.

The model name, the vector size, the query and passage prefixes, and the files
baked into the images change together. A mismatch gives a wrong index size, a
model that scores badly without its prefixes, or a model server that cannot
load the weights (`local_files_only` for the default model).
"""

import importlib
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

import pytest

from onyx.configs import model_configs
from onyx.configs.embedding_configs import SUPPORTED_EMBEDDING_MODELS
from shared_configs.configs import DEFAULT_DOCUMENT_ENCODER_MODEL

_BACKEND_DIR = Path(__file__).resolve().parents[4]
_OVERRIDE_VARS = (
    "DOCUMENT_ENCODER_MODEL",
    "DOC_EMBEDDING_DIM",
    "ASYM_QUERY_PREFIX",
    "ASYM_PASSAGE_PREFIX",
)


@pytest.fixture
def defaults(monkeypatch: pytest.MonkeyPatch) -> Iterator[ModuleType]:
    """`model_configs` as loaded with none of the override variables set."""
    with monkeypatch.context() as clean_env:
        for name in _OVERRIDE_VARS:
            clean_env.delenv(name, raising=False)
        yield importlib.reload(model_configs)
    importlib.reload(model_configs)


def test_default_is_multilingual_e5_small() -> None:
    assert DEFAULT_DOCUMENT_ENCODER_MODEL == "intfloat/multilingual-e5-small"


def test_default_vector_size_matches_the_supported_model(defaults: ModuleType) -> None:
    supported_dims = {
        model.dim
        for model in SUPPORTED_EMBEDDING_MODELS
        if model.name == DEFAULT_DOCUMENT_ENCODER_MODEL
    }

    assert supported_dims == {defaults.DOC_EMBEDDING_DIM}


def test_default_prefixes_are_the_e5_prefixes(defaults: ModuleType) -> None:
    assert defaults.ASYM_QUERY_PREFIX == "query: "
    assert defaults.ASYM_PASSAGE_PREFIX == "passage: "


def test_model_server_image_bakes_in_the_default_weights() -> None:
    dockerfile = (_BACKEND_DIR / "Dockerfile.model_server").read_text()

    assert f"model_name_or_path='{DEFAULT_DOCUMENT_ENCODER_MODEL}'" in dockerfile


def test_backend_image_bakes_in_the_default_tokenizer() -> None:
    dockerfile = (_BACKEND_DIR / "Dockerfile").read_text()

    assert (
        f"Tokenizer.from_pretrained('{DEFAULT_DOCUMENT_ENCODER_MODEL}')" in dockerfile
    )
