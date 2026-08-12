import os

import pytest

from pyrepair.deepseek import DeepSeekClient


@pytest.mark.live
def test_deepseek_v4_flash_can_request_a_tool_in_thinking_mode():
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        pytest.skip("set DEEPSEEK_API_KEY to run the paid live test")

    client = DeepSeekClient(
        api_key=api_key,
        model="deepseek-v4-flash",
        base_url="https://api.deepseek.com",
        timeout=90,
    )
    turn = client.complete(
        [
            {
                "role": "system",
                "content": "You must call show_diff exactly once before answering.",
            },
            {
                "role": "user",
                "content": "Inspect the current candidate patch with the provided tool.",
            },
        ],
        [
            {
                "type": "function",
                "function": {
                    "name": "show_diff",
                    "description": "Show the current candidate unified diff.",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                        "additionalProperties": False,
                    },
                },
            }
        ],
    )

    assert turn.tool_calls
    assert turn.tool_calls[0].name == "show_diff"
    assert turn.reasoning_content is not None
