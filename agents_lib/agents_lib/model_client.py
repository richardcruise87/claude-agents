"""
Provider-agnostic model client for Claude Agents.

Wraps claude-agent-sdk (Anthropic), OpenAI, Google Gemini, and LiteLLM proxy
behind a single interface so agents can switch providers via config without code
changes.

Usage:
    client = create_model_client(CONFIG)
    result = await client.query(
        prompt=prompt,
        tools=["Bash", "Read", "Write"],
        on_progress=lambda text: print(f"  {text}"),
    )
    print(result.text)

Config keys:
    model         — model name string, e.g. "claude-sonnet-4-6" / "gpt-4o" /
                    "gemini-1.5-pro" / "litellm/gpt-4o"
    model_provider — "anthropic" | "openai" | "google" | "litellm"
                    (inferred from model name if absent; "litellm/" prefix also
                    triggers auto-detection and the prefix is stripped before
                    the model name is sent to the proxy)

LiteLLM environment variables (no config.json keys needed):
    LITELLM_BASE_URL — proxy endpoint (default: http://localhost:4000/v1)
    LITELLM_API_KEY  — API key sent to the proxy (default: "no-key" for
                       unauthenticated local proxies)

Optional dependencies (imported lazily, not in install_requires):
    openai              — pip install openai   (for model_provider=openai or litellm)
    google-generativeai — pip install google-generativeai  (for model_provider=google)
"""

import asyncio
import json
import os
import subprocess
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable
try:
    from langfuse.decorators import observe as _langfuse_observe  # v2
    _LANGFUSE_AVAILABLE = True
except ImportError:
    try:
        from langfuse import observe as _langfuse_observe  # v3+
        _LANGFUSE_AVAILABLE = True
    except ImportError:
        _LANGFUSE_AVAILABLE = False


def _noop_observe(*args, **kwargs):
    def decorator(fn):
        return fn
    if len(args) == 1 and callable(args[0]) and not kwargs:
        return args[0]
    return decorator


observe = _langfuse_observe if _LANGFUSE_AVAILABLE else _noop_observe


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------

@dataclass
class ModelResult:
    """Normalised result returned by ModelClient.query()."""
    text: str
    usage: dict = field(default_factory=dict)
    cost_usd: float | None = None
    model: str | None = None
    duration_ms: int | None = None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

class ModelClient:
    """Provider-agnostic AI client with tool-use support."""

    def __init__(self, provider: str, model: str):
        self.provider = provider
        self.model = model

    async def query(
        self,
        prompt: str,
        tools: list[str] | None = None,
        on_progress: Callable[[str], None] | None = None,
    ) -> ModelResult:
        """Run a prompt with optional tool access.

        Args:
            prompt:      Task description for the model.
            tools:       Tool names to allow: Bash, Read, Write, Grep, Glob, WebFetch.
            on_progress: Called with streaming text as it arrives (Anthropic only for now).
        """
        if self.provider == "anthropic":
            return await _query_anthropic(self.model, prompt, tools, on_progress)
        if self.provider == "openai":
            return await _query_openai(self.model, prompt, tools, on_progress)
        if self.provider == "google":
            return await _query_google(self.model, prompt, tools, on_progress)
        if self.provider == "litellm":
            return await _query_litellm(self.model, prompt, tools, on_progress)
        raise ValueError(
            f"Unknown model provider: {self.provider!r}. "
            "Expected 'anthropic', 'openai', 'google', or 'litellm'."
        )


def create_model_client(config: dict) -> ModelClient:
    """Create a ModelClient from an agent config dict.

    Reads 'model' and optional 'model_provider' from config.
    Provider is inferred from the model name if 'model_provider' is absent.
    """
    provider, model = _parse_model_config(config)
    return ModelClient(provider=provider, model=model)


# ---------------------------------------------------------------------------
# Config parsing
# ---------------------------------------------------------------------------

def _parse_model_config(config: dict) -> tuple[str, str]:
    model = config.get("model", "claude-sonnet-4-6")
    provider = config.get("model_provider")

    if isinstance(model, dict):
        # Future-proof: allow {"model": {"provider": "...", "name": "..."}}
        provider = provider or model.get("provider", "anthropic")
        model = model.get("name", "claude-sonnet-4-6")

    model = str(model)
    if provider is None:
        if model.startswith("claude"):
            provider = "anthropic"
        elif model.startswith(("gpt-", "o1", "o3", "o4")):
            provider = "openai"
        elif model.startswith("gemini"):
            provider = "google"
        elif model.startswith("litellm/"):
            provider = "litellm"
        else:
            provider = "anthropic"

    # Strip the "litellm/" routing prefix — the proxy receives the bare model name.
    if provider == "litellm" and model.startswith("litellm/"):
        model = model[len("litellm/"):]

    return provider, model


# ---------------------------------------------------------------------------
# Anthropic backend (delegates to claude-agent-sdk)
# ---------------------------------------------------------------------------

async def _query_anthropic(
    model: str,
    prompt: str,
    tools: list[str] | None,
    on_progress: Callable | None,
) -> ModelResult:
    from claude_agent_sdk import query, ClaudeAgentOptions  # noqa: PLC0415

    start = time.time()
    result_text = None
    usage: dict = {}
    cost_usd = None
    actual_model = model

    async for msg in query(
        prompt=prompt,
        options=ClaudeAgentOptions(
            allowed_tools=tools or [],
            model=model,
        ),
    ):
        if hasattr(msg, "text"):
            if on_progress:
                on_progress(msg.text)
        elif hasattr(msg, "result"):
            result_text = msg.result or ""
            usage = getattr(msg, "usage", {}) or {}
            cost_usd = getattr(msg, "total_cost_usd", None)
            actual_model = getattr(msg, "model", model) or model

    duration_ms = int((time.time() - start) * 1000)
    return ModelResult(
        text=result_text or "",
        usage=usage,
        cost_usd=cost_usd,
        model=actual_model,
        duration_ms=duration_ms,
    )


# ---------------------------------------------------------------------------
# Tool execution (shared by OpenAI and Gemini backends)
# ---------------------------------------------------------------------------

# Maps the tool names agents already use → function names used in schemas
_TOOL_FUNC_MAP = {
    "Bash":     "bash",
    "Read":     "read_file",
    "Write":    "write_file",
    "Grep":     "grep",
    "Glob":     "glob",
    "WebFetch": "web_fetch",
}

_FUNC_TOOL_MAP = {v: k for k, v in _TOOL_FUNC_MAP.items()}


def _execute_tool(func_name: str, args: dict) -> str:
    """Execute a tool call and return its output as a string."""
    try:
        if func_name == "bash":
            result = subprocess.run(
                args.get("command", ""),
                shell=True,  # nosec B602 — executes AI-generated bash commands; shell=True is required by design
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            output = result.stdout
            if result.returncode != 0 and result.stderr:
                output += f"\n[stderr]: {result.stderr}"
            return output or "(no output)"

        if func_name == "read_file":
            return Path(args["path"]).read_text(errors="replace", encoding="utf-8")

        if func_name == "write_file":
            path = Path(args["path"])
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(args["content"], encoding="utf-8")
            return f"Written {len(args['content'])} chars to {args['path']}"

        if func_name == "grep":
            cmd = ["grep", "-r", "--include=*.py", args.get("pattern", "")]
            if "path" in args:
                cmd.append(args["path"])
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30, check=False)
            return result.stdout or "(no matches)"

        if func_name == "glob":
            root = args.get("root", ".")
            pattern = args.get("pattern", "*")
            matches = [str(p) for p in Path(root).glob(pattern)]
            return "\n".join(matches) or "(no matches)"

        if func_name == "web_fetch":
            url = args["url"]
            # nosec B310 — fetching AI-requested URLs is the intended purpose of web_fetch
            with urllib.request.urlopen(url, timeout=15) as resp:  # nosec B310
                return resp.read().decode(errors="replace")[:8000]

        else:
            return f"Unknown tool: {func_name}"

    except Exception as e:
        return f"Tool error ({func_name}): {e}"


# ---------------------------------------------------------------------------
# OpenAI tool schemas
# ---------------------------------------------------------------------------

_OPENAI_TOOL_SCHEMAS = {
    "Bash": {
        "type": "function",
        "function": {
            "name": "bash",
            "description": "Run a bash command and return stdout/stderr.",
            "parameters": {
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
            },
        },
    },
    "Read": {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a file from the filesystem.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "Absolute or relative file path"}},
                "required": ["path"],
            },
        },
    },
    "Write": {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write content to a file, creating parent directories as needed.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
        },
    },
    "Grep": {
        "type": "function",
        "function": {
            "name": "grep",
            "description": "Search for a pattern in files.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string"},
                    "path": {"type": "string", "description": "Directory or file to search"},
                },
                "required": ["pattern"],
            },
        },
    },
    "Glob": {
        "type": "function",
        "function": {
            "name": "glob",
            "description": "List files matching a glob pattern.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string"},
                    "root": {"type": "string", "description": "Root directory (default: .)"},
                },
                "required": ["pattern"],
            },
        },
    },
    "WebFetch": {
        "type": "function",
        "function": {
            "name": "web_fetch",
            "description": "Fetch content from a URL.",
            "parameters": {
                "type": "object",
                "properties": {"url": {"type": "string"}},
                "required": ["url"],
            },
        },
    },
}


# ---------------------------------------------------------------------------
# OpenAI backend
# ---------------------------------------------------------------------------

@observe()
async def _query_openai(
    model: str,
    prompt: str,
    tools: list[str] | None,
    on_progress: Callable | None,
) -> ModelResult:
    try:
        from openai import AsyncOpenAI  # noqa: PLC0415
    except ImportError as exc:
        raise ImportError(
            "openai package is required for model_provider=openai.\n"
            "Install it with: pip install openai"
        ) from exc

    client = AsyncOpenAI()  # reads OPENAI_API_KEY from environment
    messages = [{"role": "user", "content": prompt}]
    tool_defs = [_OPENAI_TOOL_SCHEMAS[t] for t in (tools or []) if t in _OPENAI_TOOL_SCHEMAS]

    start = time.time()
    total_input = 0
    total_output = 0
    actual_model = model

    while True:
        kwargs: dict = {"model": model, "messages": messages}
        if tool_defs:
            kwargs["tools"] = tool_defs

        response = await client.chat.completions.create(**kwargs)
        choice = response.choices[0]
        actual_model = response.model
        total_input += response.usage.prompt_tokens
        total_output += response.usage.completion_tokens

        if choice.finish_reason == "tool_calls" and choice.message.tool_calls:
            messages.append(choice.message)
            for tc in choice.message.tool_calls:
                args = json.loads(tc.function.arguments)
                tool_result = _execute_tool(tc.function.name, args)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": tool_result,
                })
        else:
            text = choice.message.content or ""
            usage = {"input_tokens": total_input, "output_tokens": total_output}
            duration_ms = int((time.time() - start) * 1000)
            return ModelResult(text=text, usage=usage, model=actual_model, duration_ms=duration_ms)


# ---------------------------------------------------------------------------
# LiteLLM backend (OpenAI-compatible proxy)
# ---------------------------------------------------------------------------

@observe()
async def _query_litellm(
    model: str,
    prompt: str,
    tools: list[str] | None,
    on_progress: Callable | None,
) -> ModelResult:
    """Query a LiteLLM proxy using the OpenAI-compatible /chat/completions API.

    Configuration via environment variables:
        LITELLM_BASE_URL — proxy base URL (default: http://localhost:4000/v1)
        LITELLM_API_KEY  — API key (default: "no-key" for unauthenticated proxies)
    """
    if _LANGFUSE_AVAILABLE:
        try:
            from langfuse.openai import AsyncOpenAI  # noqa: PLC0415
        except ImportError:
            from openai import AsyncOpenAI  # noqa: PLC0415
    else:
        try:
            from openai import AsyncOpenAI  # noqa: PLC0415
        except ImportError as exc:
            raise ImportError(
                "openai package is required for model_provider=litellm.\n"
                "Install it with: pip install openai"
            ) from exc

    base_url = os.environ.get("LITELLM_BASE_URL", "http://localhost:4000/v1")
    api_key = os.environ.get("LITELLM_API_KEY", "no-key")
    timeout = float(os.environ.get("LITELLM_TIMEOUT", "600"))

    client = AsyncOpenAI(base_url=base_url, api_key=api_key, timeout=timeout)
    messages = [{"role": "user", "content": prompt}]
    tool_defs = [_OPENAI_TOOL_SCHEMAS[t] for t in (tools or []) if t in _OPENAI_TOOL_SCHEMAS]

    start = time.time()
    total_input = 0
    total_output = 0
    actual_model = model

    while True:
        kwargs: dict = {"model": model, "messages": messages}
        if tool_defs:
            kwargs["tools"] = tool_defs

        response = await client.chat.completions.create(**kwargs)
        choice = response.choices[0]
        actual_model = response.model
        total_input += response.usage.prompt_tokens
        total_output += response.usage.completion_tokens

        if choice.finish_reason == "tool_calls" and choice.message.tool_calls:
            messages.append(choice.message)
            for tc in choice.message.tool_calls:
                args = json.loads(tc.function.arguments)
                tool_result = _execute_tool(tc.function.name, args)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": tool_result,
                })
        else:
            text = choice.message.content or ""
            usage = {"input_tokens": total_input, "output_tokens": total_output}
            duration_ms = int((time.time() - start) * 1000)
            return ModelResult(text=text, usage=usage, model=actual_model, duration_ms=duration_ms)


# ---------------------------------------------------------------------------
# Gemini backend
# ---------------------------------------------------------------------------

def _build_gemini_tools(tool_names: list[str]) -> list:
    """Build Gemini FunctionDeclaration list from tool names."""
    import google.generativeai.protos as protos  # noqa: PLC0415

    schemas = {
        "Bash": protos.FunctionDeclaration(
            name="bash",
            description="Run a bash command and return its output.",
            parameters=protos.Schema(
                type=protos.Type.OBJECT,
                properties={"command": protos.Schema(type=protos.Type.STRING)},
                required=["command"],
            ),
        ),
        "Read": protos.FunctionDeclaration(
            name="read_file",
            description="Read a file from the filesystem.",
            parameters=protos.Schema(
                type=protos.Type.OBJECT,
                properties={"path": protos.Schema(type=protos.Type.STRING)},
                required=["path"],
            ),
        ),
        "Write": protos.FunctionDeclaration(
            name="write_file",
            description="Write content to a file.",
            parameters=protos.Schema(
                type=protos.Type.OBJECT,
                properties={
                    "path": protos.Schema(type=protos.Type.STRING),
                    "content": protos.Schema(type=protos.Type.STRING),
                },
                required=["path", "content"],
            ),
        ),
        "Grep": protos.FunctionDeclaration(
            name="grep",
            description="Search for a pattern in files.",
            parameters=protos.Schema(
                type=protos.Type.OBJECT,
                properties={
                    "pattern": protos.Schema(type=protos.Type.STRING),
                    "path": protos.Schema(type=protos.Type.STRING),
                },
                required=["pattern"],
            ),
        ),
        "Glob": protos.FunctionDeclaration(
            name="glob",
            description="List files matching a glob pattern.",
            parameters=protos.Schema(
                type=protos.Type.OBJECT,
                properties={
                    "pattern": protos.Schema(type=protos.Type.STRING),
                    "root": protos.Schema(type=protos.Type.STRING),
                },
                required=["pattern"],
            ),
        ),
        "WebFetch": protos.FunctionDeclaration(
            name="web_fetch",
            description="Fetch content from a URL.",
            parameters=protos.Schema(
                type=protos.Type.OBJECT,
                properties={"url": protos.Schema(type=protos.Type.STRING)},
                required=["url"],
            ),
        ),
    }
    return [schemas[t] for t in tool_names if t in schemas]


@observe()
async def _query_google(
    model: str,
    prompt: str,
    tools: list[str] | None,
    on_progress: Callable | None,
) -> ModelResult:
    try:
        import google.generativeai as genai  # noqa: PLC0415
        import google.generativeai.protos as protos  # noqa: PLC0415
    except ImportError as exc:
        raise ImportError(
            "google-generativeai package is required for model_provider=google.\n"
            "Install it with: pip install google-generativeai"
        ) from exc

    # genai.configure() reads GOOGLE_API_KEY from environment automatically
    func_decls = _build_gemini_tools(tools or [])
    genai_tools = [protos.Tool(function_declarations=func_decls)] if func_decls else None
    gmodel = genai.GenerativeModel(model, tools=genai_tools)
    chat = gmodel.start_chat()

    start = time.time()

    # Gemini SDK is sync; run in thread executor to avoid blocking the event loop
    response = await asyncio.to_thread(chat.send_message, prompt)

    # Agentic loop: keep executing function calls until the model is done
    while True:
        # Check if the response contains a function call
        fc = None
        for part in response.candidates[0].content.parts:
            if part.function_call.name:
                fc = part.function_call
                break

        if fc is None:
            break

        tool_result = _execute_tool(fc.name, dict(fc.args))
        fn_response = protos.Part(
            function_response=protos.FunctionResponse(
                name=fc.name,
                response={"result": tool_result},
            )
        )
        response = await asyncio.to_thread(chat.send_message, fn_response)

    text = response.text or ""
    duration_ms = int((time.time() - start) * 1000)
    return ModelResult(text=text, usage={}, model=model, duration_ms=duration_ms)
