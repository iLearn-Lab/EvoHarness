from __future__ import annotations

import json
import os
import random
import time
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from evo_harness.harness.api_errors import (
    AuthenticationFailure,
    ClientRequestFailure,
    HarnessApiError,
    RateLimitFailure,
    RequestFailure,
)
from evo_harness.harness.messages import ChatMessage, ProviderTurn, ToolCall


@dataclass(slots=True)
class ProviderProfile:
    name: str
    api_format: str
    auth_scheme: str
    default_api_key_env: str
    default_base_url: str
    description: str
    supports_native_auth: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "api_format": self.api_format,
            "auth_scheme": self.auth_scheme,
            "default_api_key_env": self.default_api_key_env,
            "default_base_url": self.default_base_url,
            "description": self.description,
            "supports_native_auth": self.supports_native_auth,
        }


PROVIDER_PROFILES: dict[str, ProviderProfile] = {
    "anthropic": ProviderProfile(
        name="anthropic",
        api_format="anthropic",
        auth_scheme="x-api-key",
        default_api_key_env="ANTHROPIC_API_KEY",
        default_base_url="https://api.anthropic.com/v1/messages",
        description="Native Anthropic Messages API.",
    ),
    "anthropic-compatible": ProviderProfile(
        name="anthropic-compatible",
        api_format="anthropic",
        auth_scheme="x-api-key",
        default_api_key_env="ANTHROPIC_API_KEY",
        default_base_url="https://api.anthropic.com/v1/messages",
        description="Anthropic-compatible gateways and proxies.",
    ),
    "vertex-anthropic": ProviderProfile(
        name="vertex-anthropic",
        api_format="anthropic",
        auth_scheme="x-api-key",
        default_api_key_env="ANTHROPIC_API_KEY",
        default_base_url="https://api.anthropic.com/v1/messages",
        description="Anthropic-style gateways fronted by Vertex-compatible endpoints.",
    ),
    "bedrock-compatible": ProviderProfile(
        name="bedrock-compatible",
        api_format="anthropic",
        auth_scheme="x-api-key",
        default_api_key_env="ANTHROPIC_API_KEY",
        default_base_url="https://api.anthropic.com/v1/messages",
        description="Bedrock-style Anthropic-compatible proxies. Native AWS auth is not built in.",
        supports_native_auth=False,
    ),
    "openai-compatible": ProviderProfile(
        name="openai-compatible",
        api_format="openai-chat",
        auth_scheme="bearer",
        default_api_key_env="OPENAI_API_KEY",
        default_base_url="https://api.openai.com/v1/chat/completions",
        description="OpenAI Chat Completions compatible endpoints.",
    ),
    "openai": ProviderProfile(
        name="openai",
        api_format="openai-chat",
        auth_scheme="bearer",
        default_api_key_env="OPENAI_API_KEY",
        default_base_url="https://api.openai.com/v1/chat/completions",
        description="Native OpenAI Chat Completions API.",
    ),
    "moonshot": ProviderProfile(
        name="moonshot",
        api_format="openai-chat",
        auth_scheme="bearer",
        default_api_key_env="MOONSHOT_API_KEY",
        default_base_url="https://api.moonshot.cn/v1/chat/completions",
        description="Moonshot / Kimi OpenAI-compatible profile.",
    ),
}


class BaseProvider(ABC):
    name: str

    @abstractmethod
    def next_turn(
        self,
        *,
        system_prompt: str,
        messages: list[ChatMessage],
        tool_schema: list[dict[str, Any]],
    ) -> ProviderTurn:
        raise NotImplementedError

    def clone(self) -> "BaseProvider":
        raise NotImplementedError(f"{self.__class__.__name__} does not support cloning")


@dataclass
class ScriptedProvider(BaseProvider):
    turns: list[ProviderTurn]
    name: str = "scripted"
    _index: int = 0

    def next_turn(
        self,
        *,
        system_prompt: str,
        messages: list[ChatMessage],
        tool_schema: list[dict[str, Any]],
    ) -> ProviderTurn:
        del system_prompt, messages, tool_schema
        if self._index >= len(self.turns):
            return ProviderTurn(stop=True)
        turn = self.turns[self._index]
        self._index += 1
        return turn

    def clone(self) -> "BaseProvider":
        remaining = [
            ProviderTurn(
                assistant_text=turn.assistant_text,
                tool_calls=[ToolCall(name=call.name, arguments=dict(call.arguments), id=call.id) for call in turn.tool_calls],
                stop=turn.stop,
                metadata=dict(turn.metadata),
            )
            for turn in self.turns[self._index :]
        ]
        return ScriptedProvider(turns=remaining, name=self.name)

    @classmethod
    def from_file(cls, path: str | Path) -> "ScriptedProvider":
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        turns = [
            ProviderTurn(
                assistant_text=str(item.get("assistant", "")),
                tool_calls=[
                    ToolCall(
                        name=str(call["name"]),
                        arguments=dict(call.get("arguments", {})),
                        id=call.get("id"),
                    )
                    for call in item.get("tool_calls", [])
                ],
                stop=bool(item.get("stop", False)),
                metadata=dict(item.get("metadata", {})),
            )
            for item in raw.get("turns", [])
        ]
        return cls(turns=turns)


class AnthropicProvider(BaseProvider):
    name = "anthropic-http"

    def __init__(
        self,
        *,
        model: str,
        api_key: str | None = None,
        api_key_env: str = "ANTHROPIC_API_KEY",
        base_url: str = "https://api.anthropic.com/v1/messages",
        anthropic_version: str = "2023-06-01",
        max_tokens: int = 4096,
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 30.0,
        headers: dict[str, str] | None = None,
        http_post: Any | None = None,
    ) -> None:
        self.model = model
        self.api_key = api_key or os.environ.get(api_key_env, "")
        self.api_key_env = api_key_env
        self.base_url = normalize_base_url(base_url, api_format="anthropic")
        self.anthropic_version = anthropic_version
        self.max_tokens = max_tokens
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.headers = dict(headers or {})
        self._http_post = http_post or _http_post_json
        if not self.api_key:
            raise ValueError(f"No API key found. Set {api_key_env} or pass api_key explicitly.")

    def next_turn(
        self,
        *,
        system_prompt: str,
        messages: list[ChatMessage],
        tool_schema: list[dict[str, Any]],
    ) -> ProviderTurn:
        payload = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": system_prompt,
            "messages": _messages_to_anthropic(messages),
            "tools": [_tool_schema_to_anthropic(item) for item in tool_schema],
        }
        raw = self._post_with_retry(payload)
        return _provider_turn_from_anthropic(raw)

    def clone(self) -> "BaseProvider":
        return AnthropicProvider(
            model=self.model,
            api_key=self.api_key,
            api_key_env=self.api_key_env,
            base_url=self.base_url,
            anthropic_version=self.anthropic_version,
            max_tokens=self.max_tokens,
            max_retries=self.max_retries,
            base_delay=self.base_delay,
            max_delay=self.max_delay,
            headers=self.headers,
            http_post=self._http_post,
        )

    def _post_with_retry(self, payload: dict[str, Any]) -> dict[str, Any]:
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": self.anthropic_version,
            **self.headers,
        }
        return _post_with_retry(
            self._http_post,
            self.base_url,
            payload,
            headers=headers,
            max_retries=self.max_retries,
            base_delay=self.base_delay,
            max_delay=self.max_delay,
        )


class OpenAIChatProvider(BaseProvider):
    name = "openai-chat-http"

    def __init__(
        self,
        *,
        model: str,
        api_key: str | None = None,
        api_key_env: str = "OPENAI_API_KEY",
        base_url: str = "https://api.openai.com/v1/chat/completions",
        max_tokens: int = 4096,
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 30.0,
        include_reasoning_content: bool = True,
        headers: dict[str, str] | None = None,
        http_post: Any | None = None,
    ) -> None:
        self.model = model
        self.api_key = api_key or os.environ.get(api_key_env, "")
        self.api_key_env = api_key_env
        self.base_url = normalize_base_url(base_url, api_format="openai-chat")
        self.max_tokens = max_tokens
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.include_reasoning_content = include_reasoning_content
        self.headers = dict(headers or {})
        self._http_post = http_post or _http_post_json
        if not self.api_key:
            raise ValueError(f"No API key found. Set {api_key_env} or pass api_key explicitly.")

    def next_turn(
        self,
        *,
        system_prompt: str,
        messages: list[ChatMessage],
        tool_schema: list[dict[str, Any]],
    ) -> ProviderTurn:
        payload = {
            "model": self.model,
            "messages": _messages_to_openai(
                messages,
                system_prompt=system_prompt,
                include_reasoning_content=self.include_reasoning_content,
            ),
            "tools": [_tool_schema_to_openai(item) for item in tool_schema],
            "tool_choice": "auto",
            "max_tokens": self.max_tokens,
        }
        raw = self._post_with_retry(payload)
        return _provider_turn_from_openai(raw)

    def clone(self) -> "BaseProvider":
        return OpenAIChatProvider(
            model=self.model,
            api_key=self.api_key,
            api_key_env=self.api_key_env,
            base_url=self.base_url,
            max_tokens=self.max_tokens,
            max_retries=self.max_retries,
            base_delay=self.base_delay,
            max_delay=self.max_delay,
            include_reasoning_content=self.include_reasoning_content,
            headers=self.headers,
            http_post=self._http_post,
        )

    def _post_with_retry(self, payload: dict[str, Any]) -> dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            **self.headers,
        }
        return _post_with_retry(
            self._http_post,
            self.base_url,
            payload,
            headers=headers,
            max_retries=self.max_retries,
            base_delay=self.base_delay,
            max_delay=self.max_delay,
        )


def list_provider_profiles() -> list[dict[str, Any]]:
    return [profile.to_dict() for profile in PROVIDER_PROFILES.values()]


def detect_provider_profile(
    *,
    provider: str | None = None,
    profile: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
) -> ProviderProfile:
    explicit_profile: ProviderProfile | None = None
    if profile and profile in PROVIDER_PROFILES:
        explicit_profile = PROVIDER_PROFILES[profile]
    elif provider and provider in PROVIDER_PROFILES:
        explicit_profile = PROVIDER_PROFILES[provider]
    base = (base_url or "").lower()
    model_name = (model or "").lower()
    inferred_profile: ProviderProfile
    if "moonshot" in base or model_name.startswith("kimi"):
        inferred_profile = PROVIDER_PROFILES["moonshot"]
    elif "openai" in base or "chat/completions" in base or model_name.startswith(("gpt", "qwen", "deepseek", "glm")):
        inferred_profile = PROVIDER_PROFILES["openai-compatible"]
    elif "vertex" in base or "aiplatform" in base:
        inferred_profile = PROVIDER_PROFILES["vertex-anthropic"]
    elif "bedrock" in base:
        inferred_profile = PROVIDER_PROFILES["bedrock-compatible"]
    elif "messages" in base:
        inferred_profile = PROVIDER_PROFILES["anthropic-compatible"]
    else:
        inferred_profile = PROVIDER_PROFILES["anthropic"]

    if explicit_profile is None:
        return inferred_profile
    if (base_url or model) and explicit_profile.api_format != inferred_profile.api_format:
        return inferred_profile
    return explicit_profile


def normalize_base_url(base_url: str, *, api_format: str) -> str:
    text = base_url.strip().rstrip("/")
    if api_format == "anthropic":
        if text.endswith("/v1/messages"):
            return text
        if text.endswith("/v1"):
            return text + "/messages"
        if "/messages" not in text:
            return text + "/v1/messages"
        return text
    if api_format == "openai-chat":
        if text.endswith("/v1/chat/completions"):
            return text
        if text.endswith("/v1"):
            return text + "/chat/completions"
        if "/chat/completions" not in text:
            if text.endswith("/chat"):
                return text + "/completions"
            return text + "/v1/chat/completions"
        return text
    return text


def build_live_provider(
    *,
    settings,
    model_override: str | None = None,
    provider_override: str | None = None,
    base_url_override: str | None = None,
    api_key_env_override: str | None = None,
) -> BaseProvider:
    resolved_model = model_override or settings.model
    resolved_provider_name = provider_override or settings.provider.provider
    resolved_profile_name = settings.provider.profile
    if provider_override is not None:
        resolved_profile_name = provider_override
    if resolved_profile_name == "auto":
        resolved_profile_name = None
    explicit_profile = detect_provider_profile(
        provider=resolved_provider_name,
        profile=resolved_profile_name,
        base_url=base_url_override or settings.provider.base_url,
        model=resolved_model,
    )
    inferred_profile = detect_provider_profile(
        base_url=base_url_override or settings.provider.base_url,
        model=resolved_model,
    )
    resolved_profile = _prefer_compatible_profile(
        explicit_profile,
        inferred_profile,
        base_url=base_url_override or settings.provider.base_url,
        model=resolved_model,
    )
    default_anthropic_base = "https://api.anthropic.com/v1/messages"
    default_anthropic_key_env = "ANTHROPIC_API_KEY"
    configured_base_url = base_url_override or settings.provider.base_url or resolved_profile.default_base_url
    configured_key_env = api_key_env_override or settings.provider.api_key_env or resolved_profile.default_api_key_env
    if (
        base_url_override is None
        and configured_base_url == default_anthropic_base
        and resolved_profile.default_base_url != default_anthropic_base
    ):
        configured_base_url = resolved_profile.default_base_url
    if (
        api_key_env_override is None
        and configured_key_env == default_anthropic_key_env
        and resolved_profile.default_api_key_env != default_anthropic_key_env
    ):
        configured_key_env = resolved_profile.default_api_key_env
    api_key_env = configured_key_env
    base_url = configured_base_url
    headers = dict(getattr(settings.provider, "headers", {}) or {})
    auth_scheme = getattr(settings.provider, "auth_scheme", resolved_profile.auth_scheme) or resolved_profile.auth_scheme
    api_key = None if api_key_env_override else getattr(settings.provider, "api_key", None)

    if resolved_profile.api_format == "openai-chat":
        return OpenAIChatProvider(
            model=resolved_model,
            api_key=api_key,
            api_key_env=api_key_env,
            base_url=base_url,
            max_tokens=settings.max_tokens,
            include_reasoning_content=resolved_profile.name in {"openai", "moonshot"},
            headers=headers,
        )
    return AnthropicProvider(
        model=resolved_model,
        api_key=api_key,
        api_key_env=api_key_env,
        base_url=base_url,
        anthropic_version=settings.provider.anthropic_version,
        max_tokens=settings.max_tokens,
        headers=headers if auth_scheme == "x-api-key" else headers,
    )


def _messages_to_anthropic(messages: list[ChatMessage]) -> list[dict[str, Any]]:
    converted: list[dict[str, Any]] = []
    for message in messages:
        if message.role == "assistant":
            content_blocks: list[dict[str, Any] | str] = []
            if message.text:
                content_blocks.append({"type": "text", "text": message.text})
            for tool_call in message.tool_calls:
                content_blocks.append(
                    {
                        "type": "tool_use",
                        "id": tool_call.get("id") or "",
                        "name": tool_call["name"],
                        "input": dict(tool_call.get("arguments", {})),
                    }
                )
            converted.append({"role": "assistant", "content": content_blocks or message.text})
            continue
        if message.role == "tool":
            tool_call_id = message.metadata.get("tool_call_id") if message.metadata else None
            if tool_call_id:
                converted.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": tool_call_id,
                                "content": message.text,
                                "is_error": message.is_error,
                            }
                        ],
                    }
                )
            else:
                converted.append({"role": "user", "content": message.text})
            continue
        converted.append({"role": "user", "content": message.text})
    return converted


def _messages_to_openai(
    messages: list[ChatMessage],
    *,
    system_prompt: str,
    include_reasoning_content: bool,
) -> list[dict[str, Any]]:
    converted: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
    for message in messages:
        if message.role == "assistant":
            payload: dict[str, Any] = {
                "role": "assistant",
                "content": message.text or "",
            }
            reasoning_content = str(dict(message.metadata or {}).get("reasoning_content", "") or "").strip()
            if include_reasoning_content and reasoning_content:
                payload["reasoning_content"] = reasoning_content
            if message.tool_calls:
                payload["tool_calls"] = [
                    {
                        "id": tool_call.get("id") or "",
                        "type": "function",
                        "function": {
                            "name": tool_call["name"],
                            "arguments": json.dumps(dict(tool_call.get("arguments", {})), ensure_ascii=False),
                        },
                    }
                    for tool_call in message.tool_calls
                ]
            converted.append(payload)
            continue
        if message.role == "tool":
            tool_call_id = message.metadata.get("tool_call_id") if message.metadata else None
            if tool_call_id:
                converted.append(
                    {
                        "role": "tool",
                        "content": message.text,
                        "tool_call_id": tool_call_id,
                    }
                )
            else:
                tool_name = message.tool_name or "tool"
                converted.append({"role": "user", "content": f"[tool context] {tool_name}: {message.text}"})
            continue
        converted.append({"role": "user", "content": message.text})
    return converted


def _tool_schema_to_anthropic(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": item["name"],
        "description": item.get("description", ""),
        "input_schema": item.get("input_schema", {"type": "object", "additionalProperties": True}),
    }


def _tool_schema_to_openai(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": item["name"],
            "description": item.get("description", ""),
            "parameters": item.get("input_schema", {"type": "object", "additionalProperties": True}),
        },
    }


def _provider_turn_from_anthropic(payload: dict[str, Any]) -> ProviderTurn:
    content = payload.get("content", [])
    assistant_chunks: list[str] = []
    tool_calls: list[ToolCall] = []
    for block in content:
        block_type = block.get("type")
        if block_type == "text":
            assistant_chunks.append(str(block.get("text", "")))
        if block_type == "tool_use":
            tool_calls.append(
                ToolCall(
                    name=str(block["name"]),
                    arguments=dict(block.get("input", {})),
                    id=str(block.get("id", "")) or None,
                )
            )
    stop_reason = payload.get("stop_reason")
    usage = payload.get("usage", {})
    return ProviderTurn(
        assistant_text="".join(assistant_chunks).strip(),
        tool_calls=tool_calls,
        stop=stop_reason == "end_turn" and not tool_calls,
        metadata={
            "stop_reason": stop_reason,
            "usage": {
                "input_tokens": int(usage.get("input_tokens", 0) or 0),
                "output_tokens": int(usage.get("output_tokens", 0) or 0),
            },
        },
    )


def _provider_turn_from_openai(payload: dict[str, Any]) -> ProviderTurn:
    choices = list(payload.get("choices", []))
    if not choices:
        raise RequestFailure("OpenAI-compatible provider returned no choices")
    choice = dict(choices[0])
    message = dict(choice.get("message", {}))
    tool_calls: list[ToolCall] = []
    for item in message.get("tool_calls", []):
        function = dict(item.get("function", {}))
        try:
            arguments = json.loads(function.get("arguments", "{}"))
        except json.JSONDecodeError:
            arguments = {}
        tool_calls.append(
            ToolCall(
                name=str(function.get("name", "")),
                arguments=dict(arguments),
                id=str(item.get("id", "")) or None,
            )
        )
    usage = dict(payload.get("usage", {}))
    finish_reason = choice.get("finish_reason")
    reasoning_content = str(message.get("reasoning_content", "") or "").strip()
    return ProviderTurn(
        assistant_text=str(message.get("content", "") or "").strip(),
        tool_calls=tool_calls,
        stop=finish_reason == "stop" and not tool_calls,
        metadata={
            "stop_reason": finish_reason,
            **({"reasoning_content": reasoning_content} if reasoning_content else {}),
            "usage": {
                "input_tokens": int(usage.get("prompt_tokens", usage.get("input_tokens", 0)) or 0),
                "output_tokens": int(usage.get("completion_tokens", usage.get("output_tokens", 0)) or 0),
            },
        },
    )


def _http_post_json(url: str, payload: dict[str, Any], *, headers: dict[str, str]) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={
            "content-type": "application/json",
            **headers,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        if exc.code in {401, 403}:
            raise AuthenticationFailure(body or f"HTTP {exc.code}") from exc
        if exc.code == 429:
            raise RateLimitFailure(body or f"HTTP {exc.code}") from exc
        if exc.code in {500, 502, 503, 529}:
            raise RequestFailure(body or f"HTTP {exc.code}") from exc
        raise ClientRequestFailure(body or f"HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise RequestFailure(str(exc)) from exc


def _post_with_retry(
    http_post: Any,
    url: str,
    payload: dict[str, Any],
    *,
    headers: dict[str, str],
    max_retries: int,
    base_delay: float,
    max_delay: float,
) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            return http_post(url, payload, headers=headers)
        except HarnessApiError as exc:
            last_error = exc
            if isinstance(exc, (AuthenticationFailure, ClientRequestFailure)):
                raise
            if attempt >= max_retries:
                raise
            time.sleep(_get_retry_delay(attempt, base_delay, max_delay))
        except Exception as exc:  # pragma: no cover
            last_error = exc
            if attempt >= max_retries:
                raise RequestFailure(str(exc)) from exc
            time.sleep(_get_retry_delay(attempt, base_delay, max_delay))
    if last_error is not None:
        raise RequestFailure(str(last_error)) from last_error
    raise RequestFailure("Unknown provider error")


def _get_retry_delay(attempt: int, base_delay: float, max_delay: float) -> float:
    delay = min(base_delay * (2**attempt), max_delay)
    jitter = random.uniform(0, delay * 0.25)
    return delay + jitter


def _prefer_compatible_profile(
    explicit_profile: ProviderProfile,
    inferred_profile: ProviderProfile,
    *,
    base_url: str | None,
    model: str | None,
) -> ProviderProfile:
    del model
    if not base_url:
        return explicit_profile
    if explicit_profile.api_format == inferred_profile.api_format:
        return explicit_profile
    # If the URL shape strongly indicates a different API format than the stored provider,
    # trust the URL/model inference so OpenAI-compatible endpoints don't get called as Anthropic.
    return inferred_profile
