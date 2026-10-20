"""Plan CLIs: the right command line, the answer read back, and a run through a stand-in."""

import asyncio
import json
import os
import stat
from pathlib import Path
from typing import Any

import pytest

from alpha_harness.llm.cli import CliClient, CliError, answer_of, command


def test_missing_tool_says_how_to_install(monkeypatch: Any) -> None:
    monkeypatch.setenv("PATH", "")
    with pytest.raises(CliError, match="not installed"):
        command("codex-cli", "default", Path("out.txt"), None)


def test_answers_are_read_from_each_tool(tmp_path: Path) -> None:
    out = tmp_path / "answer.txt"
    out.write_text('{"alphas": []}', encoding="utf-8")
    assert answer_of("codex-cli", "progress", out) == '{"alphas": []}'
    said = json.dumps({"type": "result", "result": '{"alphas": [1]}', "is_error": False})
    assert answer_of("claude-cli", said, out) == '{"alphas": [1]}'
    with pytest.raises(CliError, match="limit"):
        answer_of("claude-cli", json.dumps({"is_error": True, "result": "usage limit"}), out)
    assert answer_of("antigravity-cli", json.dumps({"response": "{}"}), out) == "{}"


@pytest.mark.skipif(os.name == "nt", reason="a POSIX stand-in script")
def test_a_run_through_a_stand_in_codex(tmp_path: Path, monkeypatch: Any) -> None:
    script = tmp_path / "codex"
    # Writes stdin's length into the file named after --output-last-message.
    script.write_text(
        "#!/bin/sh\n"
        'while [ "$#" -gt 0 ]; do\n'
        '  if [ "$1" = "--output-last-message" ]; then out="$2"; fi\n'
        "  shift\n"
        "done\n"
        'n=$(wc -c)\necho "{\\"read\\": $n}" > "$out"\n',
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ.get('PATH', '')}")
    text, usage = asyncio.run(
        CliClient("codex-cli").generate(
            model="default", system="sys", user="hello", schema={"type": "object"}
        )
    )
    assert json.loads(text)["read"] > len("sys hello")
    assert usage["total_tokens"] > 0
