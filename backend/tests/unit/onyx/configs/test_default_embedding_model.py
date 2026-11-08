"""Yahont keeps the previous default local embedding model in the images.

Upstream's default is granite (`shared_configs/embedding_models.py`, tested by
`tests/unit/model_server/test_dockerfile_bundled_model.py`). Indexes created on
`intfloat/multilingual-e5-small`, the Yahont default before it, must keep
working with no download, so both images keep its files.
"""

from pathlib import Path

from shared_configs.embedding_models import find_embedding_model_spec

_BACKEND_DIR = Path(__file__).resolve().parents[4]
_PREVIOUS_DEFAULT = "intfloat/multilingual-e5-small"


def test_previous_default_is_still_a_known_model() -> None:
    spec = find_embedding_model_spec(None, _PREVIOUS_DEFAULT)

    assert spec is not None
    assert spec.model_dim == 384
    assert (spec.query_prefix, spec.passage_prefix) == ("query: ", "passage: ")


def test_model_server_image_keeps_the_previous_default_weights() -> None:
    dockerfile = (_BACKEND_DIR / "Dockerfile.model_server").read_text()

    assert f"model_name_or_path='{_PREVIOUS_DEFAULT}'" in dockerfile


def test_backend_image_keeps_the_previous_default_tokenizer() -> None:
    dockerfile = (_BACKEND_DIR / "Dockerfile").read_text()

    assert f"Tokenizer.from_pretrained('{_PREVIOUS_DEFAULT}')" in dockerfile
