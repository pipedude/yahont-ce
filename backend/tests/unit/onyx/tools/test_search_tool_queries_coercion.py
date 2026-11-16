from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from onyx.tools.models import ToolCallException
from onyx.tools.tool_implementations.search.search_tool import (
    SearchTool,
    _coerce_llm_queries,
)

SESSION = (
    "onyx.tools.tool_implementations.search.search_tool.get_session_with_current_tenant"
)


def _make_tool() -> SearchTool:
    """A SearchTool with only the state that run() reads before the database."""
    tool = SearchTool.__new__(SearchTool)
    tool.user_selected_filters = None
    tool.project_id_filter = None
    tool.persona_id_filter = None
    return tool


def test_bare_string_becomes_one_query() -> None:
    assert _coerce_llm_queries("договор поставки") == ["договор поставки"]


def test_list_of_strings_is_returned_unchanged() -> None:
    queries = ["договор", "поставка"]

    assert _coerce_llm_queries(queries) is queries


def test_empty_list_keeps_its_behavior() -> None:
    assert _coerce_llm_queries([]) == []


@pytest.mark.parametrize(
    "raw",
    [
        {"query": "договор"},
        42,
        True,
        None,
        ["договор", 1],
        [["договор"]],
        [None],
        "",
        "   ",
    ],
)
def test_other_shapes_raise_with_a_format_hint(raw: Any) -> None:
    with pytest.raises(ToolCallException) as exc_info:
        _coerce_llm_queries(raw)

    hint = exc_info.value.llm_facing_message
    assert '"queries"' in hint
    assert "array" in hint


def test_run_rejects_a_malformed_value_before_the_database() -> None:
    tool = _make_tool()

    with patch(SESSION, side_effect=AssertionError("database was opened")):
        with pytest.raises(ToolCallException):
            tool.run(placement=MagicMock(), override_kwargs=MagicMock(), queries=42)


def test_run_lets_a_bare_string_reach_the_search_body() -> None:
    tool = _make_tool()

    sentinel = RuntimeError("reached the search body")
    with patch(SESSION, side_effect=sentinel):
        with pytest.raises(RuntimeError, match="reached the search body"):
            tool.run(
                placement=MagicMock(),
                override_kwargs=MagicMock(),
                queries="договор поставки",
            )
