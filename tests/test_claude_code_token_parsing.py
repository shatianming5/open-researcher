import json
from open_researcher.agents.claude_code import ClaudeCodeAdapter


def test_claude_code_parse_result_line():
    adapter = ClaudeCodeAdapter()
    line = json.dumps({
        "type": "result",
        "result": "experiment complete",
        "usage": {"input_tokens": 5000, "output_tokens": 2000},
    })
    metrics = adapter._try_parse_token_line(line)
    assert metrics is not None
    assert metrics.tokens_input == 5000
    assert metrics.tokens_output == 2000


def test_claude_code_parse_non_result_line():
    adapter = ClaudeCodeAdapter()
    line = json.dumps({"type": "assistant", "content": [{"type": "text", "text": "hello"}]})
    metrics = adapter._try_parse_token_line(line)
    assert metrics is None


def test_claude_code_parse_non_json_line():
    adapter = ClaudeCodeAdapter()
    metrics = adapter._try_parse_token_line("plain text output")
    assert metrics is None


def test_claude_code_build_flags_includes_output_format():
    adapter = ClaudeCodeAdapter(config={"model": "claude-sonnet-4-5-20250514"})
    flags = adapter._build_flags()
    assert "--output-format" in flags
    idx = flags.index("--output-format")
    assert flags[idx + 1] == "stream-json"
