"""Subscriptions through their makers' own command-line tools.

ChatGPT, Claude and Google AI plans each come with an official terminal tool that signs in
with the plan and answers one prompt without a window: ``codex exec`` (OpenAI Codex CLI),
``claude -p`` (Claude Code) and ``agy -p`` (Google's Antigravity CLI, which replaced Gemini CLI
for Google One plans). This module runs the unmodified tool the user installed and signed in to
themselves, on their own computer, the way the tool's documentation shows for scripts. It never
sees, stores or forwards the sign-in: the tool keeps its own credentials.

Each tool is run read-only where it has the switch, with the prompt on standard input (long
prompts do not fit a Windows command line), and asked for its final answer only. The answer
is the same JSON text an API model returns, so the labs parse it the same way.

Limits are the plan's, and they are shared with the user's own chats and coding, so a key for
a CLI provider needs a daily cap like a paid one (see :meth:`KeyStore.add`).
"""

import asyncio
import json
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .text import estimate_tokens

#: A tool's whole run, thinking included. Agents are slower than a chat completion.
TIMEOUT_SECONDS = 300.0
#: What every tool is told on its command line; the task itself arrives on standard input.
INSTRUCTION = (
    "The task is on standard input. Do not run commands, edit files or browse: answer from "
    "the text alone. Reply with only the JSON the task asks for, no other words."
)


class CliError(RuntimeError):
    """The tool is missing, not signed in, out of its plan's limit, or answered nothing."""


@dataclass(frozen=True, slots=True)
class Tool:
    id: str
    #: The program on PATH.
    binary: str
    #: Shown when the program is missing.
    install: str


TOOLS: dict[str, Tool] = {
    "codex-cli": Tool(
        "codex-cli", "codex", "Install it with npm install -g @openai/codex, then run codex once"
    ),
    "claude-cli": Tool(
        "claude-cli",
        "claude",
        "Install Claude Code (see code.claude.com), then run claude once and sign in",
    ),
    "antigravity-cli": Tool(
        "antigravity-cli",
        "agy",
        "Install the Antigravity CLI (see antigravity.google), then run agy once and sign in",
    ),
}


def _schema_note(schema: dict[str, Any] | None) -> str:
    return f"\n\nThe JSON must match this schema:\n{json.dumps(schema)}" if schema else ""


#: A model id meaning "the tool's own default": the plans change which models they include.
DEFAULT_MODEL = "default"


def command(tool: str, model: str, out: Path, schema_file: Path | None) -> list[str]:
    """The tool's command line. ``out`` receives Codex's final message."""
    model = "" if model == DEFAULT_MODEL else model
    found = TOOLS.get(tool)
    if found is None:
        raise CliError(f"{tool} is not a command-line tool this application knows.")
    path = shutil.which(found.binary)
    if path is None:
        raise CliError(f"{found.binary} is not installed or not on PATH. {found.install}.")
    if tool == "codex-cli":
        args = [path, "exec", "--skip-git-repo-check", "--ephemeral", "--sandbox", "read-only"]
        args += ["--output-last-message", str(out)]
        if schema_file is not None:
            args += ["--output-schema", str(schema_file)]
        if model:
            args += ["--model", model]
        return [*args, INSTRUCTION]
    if tool == "claude-cli":
        args = [path, "-p", INSTRUCTION, "--output-format", "json"]
        return [*args, "--model", model] if model else args
    args = [path, "-p", INSTRUCTION, "--output-format", "json"]
    return [*args, "--model", model] if model else args


def answer_of(tool: str, stdout: str, out: Path) -> str:
    """The tool's final answer as text."""
    if tool == "codex-cli":
        if out.exists():
            text = out.read_text(encoding="utf-8").strip()
            if text:
                return text
        return stdout.strip()
    try:
        parsed = json.loads(stdout)
    except json.JSONDecodeError:
        return stdout.strip()
    if isinstance(parsed, dict):
        if parsed.get("is_error"):
            raise CliError(str(parsed.get("result") or parsed.get("error") or "The tool failed."))
        for key in ("result", "response", "text", "output"):
            value = parsed.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return stdout.strip()


class CliClient:
    """The same ``generate`` an API client offers, answered by a local tool."""

    def __init__(self, tool: str) -> None:
        self.tool = tool

    async def generate(
        self,
        *,
        model: str,
        system: str,
        user: str,
        temperature: float | None = None,  # noqa: ARG002 - the tools take none
        schema: dict[str, Any] | None = None,
        reasoning_effort: Any = None,  # noqa: ARG002 - the tools take none
    ) -> tuple[str, dict[str, Any]]:
        prompt = f"{system}\n\n---\n\n{user}{_schema_note(schema)}"
        with tempfile.TemporaryDirectory(prefix="alpha-harness-cli-") as folder:
            out = Path(folder) / "answer.txt"
            schema_file = None
            if schema is not None and self.tool == "codex-cli":
                schema_file = Path(folder) / "schema.json"
                schema_file.write_text(json.dumps(schema), encoding="utf-8")
            args = command(self.tool, model, out, schema_file)
            process = await asyncio.create_subprocess_exec(
                *args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=folder,
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(prompt.encode("utf-8")), timeout=TIMEOUT_SECONDS
                )
            except TimeoutError as exc:
                process.kill()
                raise CliError(
                    f"{TOOLS[self.tool].binary} did not answer within {TIMEOUT_SECONDS:.0f} s."
                ) from exc
            said = stdout.decode("utf-8", "replace")
            if process.returncode != 0:
                detail = (stderr.decode("utf-8", "replace") or said).strip()[-600:]
                raise CliError(
                    f"{TOOLS[self.tool].binary} stopped (exit {process.returncode}): {detail}"
                )
            text = answer_of(self.tool, said, out)
        if not text:
            raise CliError(f"{TOOLS[self.tool].binary} answered nothing.")
        used = estimate_tokens(prompt)
        made = estimate_tokens(text)
        return text, {"prompt_tokens": used, "completion_tokens": made, "total_tokens": used + made}

    async def models(self, **_query: object) -> list[str]:
        """The tools choose their own default; ``default`` uses it, any other id is passed on."""
        return [DEFAULT_MODEL]
