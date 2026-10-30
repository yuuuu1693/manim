from __future__ import annotations

import ast
import json
import os
import re
from dataclasses import dataclass, field
from typing import Callable, Mapping, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from manimlib.ai.code_generator import generate_code
from manimlib.ai.prompt_parser import parse_prompt
from manimlib.code_checker import check_code, detect_scene_names


SYSTEM_PROMPT = """你是 ManimGL 场景代码生成器。根据用户的中文需求，只返回完整 Python 代码。
要求：
1. 使用 `from manimlib import *`，定义至少一个 Scene 子类和 construct 方法。
2. 代码必须能够直接运行，不要返回 Markdown、解释或省略号。
3. 禁止文件、网络、系统命令、动态执行和用户输入操作。
4. 动画结束时调用 self.wait，并优先使用 ManimGL 现有公开 API。
"""

FORBIDDEN_IMPORT_ROOTS = {
    "http", "os", "pathlib", "requests", "shutil", "socket",
    "subprocess", "sys", "urllib",
}
FORBIDDEN_CALL_ROOTS = FORBIDDEN_IMPORT_ROOTS | {"eval", "exec", "open", "input"}
ALLOWED_IMPORT_ROOTS = {"manimlib", "math", "numpy"}


class SceneCodeProvider(Protocol):
    def generate(self, prompt: str) -> str:
        ...


class ProviderError(RuntimeError):
    pass


@dataclass(frozen=True)
class ProviderConfig:
    base_url: str
    model: str
    api_key: str = field(repr=False)
    timeout: float = 20.0

    @classmethod
    def from_env(
        cls,
        environ: Mapping[str, str] | None = None,
    ) -> ProviderConfig | None:
        values = os.environ if environ is None else environ
        api_key = values.get("MANIM_AI_API_KEY", "").strip()
        model = values.get("MANIM_AI_MODEL", "").strip()
        if not api_key or not model:
            return None
        base_url = values.get(
            "MANIM_AI_BASE_URL", "https://api.openai.com/v1"
        ).strip()
        try:
            timeout = float(values.get("MANIM_AI_TIMEOUT", "20"))
        except ValueError as exc:
            raise ProviderError("MANIM_AI_TIMEOUT 必须是数字") from exc
        if not base_url.startswith(("https://", "http://")):
            raise ProviderError("MANIM_AI_BASE_URL 必须是 HTTP 或 HTTPS 地址")
        if not 1 <= timeout <= 120:
            raise ProviderError("MANIM_AI_TIMEOUT 必须在 1 到 120 秒之间")
        return cls(base_url.rstrip("/"), model, api_key, timeout)


Transport = Callable[[Request, float], bytes]


class OpenAICompatibleProvider:
    def __init__(
        self,
        config: ProviderConfig,
        transport: Transport | None = None,
    ) -> None:
        self.config = config
        self.transport = transport or _default_transport

    def generate(self, prompt: str) -> str:
        prompt = prompt.strip()
        if not prompt:
            raise ProviderError("动画描述不能为空")
        endpoint = self.config.base_url
        if not endpoint.endswith("/chat/completions"):
            endpoint += "/chat/completions"
        payload = json.dumps(
            {
                "model": self.config.model,
                "temperature": 0.2,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
            },
            ensure_ascii=False,
        ).encode("utf-8")
        request = Request(
            endpoint,
            data=payload,
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            raw = self.transport(request, self.config.timeout)
            response = json.loads(raw.decode("utf-8"))
            content = response["choices"][0]["message"]["content"]
        except HTTPError as exc:
            raise ProviderError(f"大模型接口返回 HTTP {exc.code}") from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise ProviderError("大模型接口连接失败或超时") from exc
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
            raise ProviderError("大模型接口返回格式无效") from exc
        if not isinstance(content, str) or not content.strip():
            raise ProviderError("大模型接口没有返回代码")
        return content


@dataclass(frozen=True)
class GenerationResult:
    source: str
    backend: str
    warning: str | None = None


def generate_scene_source(
    prompt: str,
    mode: str = "auto",
    provider: SceneCodeProvider | None = None,
    environ: Mapping[str, str] | None = None,
) -> GenerationResult:
    """Generate validated scene source with an optional provider and local fallback."""
    if mode not in {"auto", "local", "provider"}:
        raise ValueError(f"未知生成模式：{mode}")
    if mode == "local":
        return GenerationResult(_generate_locally(prompt), "local")

    active_provider = provider
    if active_provider is None:
        config = ProviderConfig.from_env(environ)
        if config is not None:
            active_provider = OpenAICompatibleProvider(config)
    if active_provider is None:
        if mode == "provider":
            raise ProviderError(
                "未配置大模型：请设置 MANIM_AI_API_KEY 和 MANIM_AI_MODEL"
            )
        return GenerationResult(_generate_locally(prompt), "local")

    try:
        source = validate_generated_source(active_provider.generate(prompt))
        return GenerationResult(source, "provider")
    except (ProviderError, ValueError) as provider_error:
        if mode == "provider":
            raise ProviderError(str(provider_error)) from provider_error
        try:
            local_source = _generate_locally(prompt)
        except ValueError as local_error:
            raise ProviderError(
                f"大模型生成失败：{provider_error}；本地规则也无法处理：{local_error}"
            ) from provider_error
        return GenerationResult(
            local_source,
            "local",
            f"大模型生成失败，已回退到本地规则：{provider_error}",
        )


def validate_generated_source(raw_source: str) -> str:
    source = _strip_code_fence(raw_source).strip() + "\n"
    if len(source) > 200_000:
        raise ProviderError("大模型返回的代码过长")
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise ProviderError(f"大模型返回的代码存在语法错误：{exc.msg}") from exc
    if not detect_scene_names(source):
        raise ProviderError("大模型返回的代码中没有 Scene 子类")
    _validate_imports_and_calls(tree)
    errors = [item for item in check_code(source) if item.severity == "error"]
    if errors:
        summary = "；".join(item.message for item in errors[:3])
        raise ProviderError(f"大模型代码未通过静态检查：{summary}")
    return source


def _generate_locally(prompt: str) -> str:
    return generate_code(parse_prompt(prompt))


def _validate_imports_and_calls(tree: ast.Module) -> None:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots = {alias.name.split(".")[0] for alias in node.names}
            blocked = roots - ALLOWED_IMPORT_ROOTS
            if blocked:
                raise ProviderError(f"禁止导入模块：{sorted(blocked)[0]}")
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            if root not in ALLOWED_IMPORT_ROOTS:
                raise ProviderError(f"禁止导入模块：{root or '相对导入'}")
        elif isinstance(node, ast.Call):
            root = _call_root(node.func)
            if root in FORBIDDEN_CALL_ROOTS:
                raise ProviderError(f"禁止调用：{root}")


def _call_root(node: ast.expr) -> str:
    while isinstance(node, ast.Attribute):
        node = node.value
    return node.id if isinstance(node, ast.Name) else ""


def _strip_code_fence(source: str) -> str:
    match = re.fullmatch(
        r"\s*```(?:python|py)?\s*\n(?P<code>.*?)\n```\s*",
        source,
        re.DOTALL | re.IGNORECASE,
    )
    return match.group("code") if match else source


def _default_transport(request: Request, timeout: float) -> bytes:
    with urlopen(request, timeout=timeout) as response:
        return response.read()
