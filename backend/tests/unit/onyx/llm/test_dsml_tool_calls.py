"""DeepSeek DSML tool calls written as text (Yahont fork).

Seen on the stand: after a failed tool call, DeepSeek V4.1 Flash through
RouterAI wrote its next tool call as DSML text (``finish_reason=stop``) instead
of a native ``tool_calls`` delta. The user saw the raw markup. The XML text-call
recovery (``onyx.llm.tool_parsing``) must treat DSML like ``<function_calls>``:
strip it from the visible answer and turn it into a real tool call.
"""

from onyx.chat.llm_step import extract_tool_calls_from_response_text
from onyx.llm.tool_parsing import (
    XmlToolCallContentFilter,
    looks_like_xml_tool_call_payload,
)
from onyx.server.query_and_chat.placement import Placement

# DeepSeek V4 wraps calls in `tool_calls`; V3.2 in `function_calls`. The bar is
# the fullwidth vertical line U+FF5C.
V4_CALL = (
    "<｜DSML｜tool_calls>\n"
    '<｜DSML｜invoke name="generate_image">\n'
    '<｜DSML｜parameter name="prompt" string="true">Кот держит лимонад</｜DSML｜parameter>\n'
    '<｜DSML｜parameter name="reference_image_file_ids" string="false">'
    '["d3bea36e-97c9-45e5-bda9-8f85c9c03487"]</｜DSML｜parameter>\n'
    '<｜DSML｜parameter name="shape" string="true">portrait</｜DSML｜parameter>\n'
    "</｜DSML｜invoke>\n"
    "</｜DSML｜tool_calls>"
)
V32_CALL = V4_CALL.replace("tool_calls>", "function_calls>")


def _tool_defs() -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": "generate_image",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "prompt": {"type": "string"},
                        "shape": {"type": "string"},
                        "reference_image_file_ids": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                    },
                    "required": ["prompt"],
                },
            },
        }
    ]


def _extract(text: str) -> list:
    return extract_tool_calls_from_response_text(
        response_text=text,
        tool_definitions=_tool_defs(),
        placement=Placement(turn_index=0, tab_index=0, sub_turn_index=None),
    )


def test_dsml_payloads_are_detected() -> None:
    assert looks_like_xml_tool_call_payload(V4_CALL)
    assert looks_like_xml_tool_call_payload(V32_CALL)
    assert not looks_like_xml_tool_call_payload("Обычный ответ без вызовов ｜ DSML")


def test_extracts_deepseek_v4_tool_call() -> None:
    calls = _extract("Попробую ещё раз.\n" + V4_CALL)

    assert len(calls) == 1
    assert calls[0].tool_name == "generate_image"
    assert calls[0].tool_args == {
        "prompt": "Кот держит лимонад",
        "reference_image_file_ids": ["d3bea36e-97c9-45e5-bda9-8f85c9c03487"],
        "shape": "portrait",
    }


def test_extracts_deepseek_v32_tool_call() -> None:
    calls = _extract(V32_CALL)

    assert [c.tool_name for c in calls] == ["generate_image"]
    assert calls[0].tool_args["shape"] == "portrait"


def test_filter_strips_dsml_block_and_keeps_answer_text() -> None:
    f = XmlToolCallContentFilter()
    output = f.process("Попробую ещё раз.\n" + V4_CALL + "\nГотово.") + f.flush()

    assert output == "Попробую ещё раз.\n\nГотово."


def test_filter_strips_dsml_block_split_inside_the_marker() -> None:
    f = XmlToolCallContentFilter()
    chunks = [
        "Сейчас ",
        "<｜DS",
        "ML｜tool_",
        "calls>",
        V4_CALL[len("<｜DSML｜tool_calls>") :],
    ]

    output = "".join(f.process(chunk) for chunk in chunks) + f.flush()

    assert output == "Сейчас "


def test_filter_keeps_text_that_only_mentions_the_bar() -> None:
    f = XmlToolCallContentFilter()
    text = "Значение a ｜ b и тег <｜DSML｜other> остаются"

    assert f.process(text) + f.flush() == text
