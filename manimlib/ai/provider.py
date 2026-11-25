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
from manimlib.ai.models import SceneSpec
from manimlib.ai.prompt_parser import parse_prompt
from manimlib.code_checker import check_code, detect_scene_names


SYSTEM_PROMPT = """你是 ManimGL 场景代码生成器。根据用户的中文需求，只返回完整 Python 代码。
要求：
1. 使用 `from manimlib import *`，定义至少一个 Scene 子类和 construct 方法。
2. 代码必须能够直接运行，不要返回 Markdown、解释或省略号。
3. 禁止文件、网络、系统命令、动态执行和用户输入操作。
4. 动画结束时调用 self.wait，并优先使用 ManimGL 现有公开 API。
"""

SCENE_SPEC_SYSTEM_PROMPT = """你是 ManimGL 动画需求解析器。只返回一个 JSON 对象，不要返回 Markdown 或解释。
JSON 顶层必须包含 objects 和 actions 两个数组。对象格式为 {"name":"circle_1","type":"circle",...属性}，
动作格式为 {"type":"create","target":"circle_1",...参数}。
对象 type 只能使用：annulus、arrow、axes、circle、dot、ellipse、function_graph、line、rectangle、square、text、triangle、group、irregular_triangle、pyramid。
动作 type 只能使用：create、fade_in、fade_out、move、rotate、scale、set_color、wait。
名称必须是合法且唯一的 Python 标识符；除 wait 外的动作必须引用已定义对象。不能输出 Python 代码。
"""

FORBIDDEN_IMPORT_ROOTS = {
    "http", "os", "pathlib", "requests", "shutil", "socket",
    "subprocess", "sys", "urllib",
}
FORBIDDEN_CALL_ROOTS = FORBIDDEN_IMPORT_ROOTS | {
    "__import__", "compile", "delattr", "eval", "exec", "getattr",
    "globals", "input", "locals", "open", "setattr", "vars",
}
ALLOWED_IMPORT_ROOTS = {"manimlib", "math", "numpy"}
MAX_REPAIR_SOURCE_LENGTH = 20_000


class SceneCodeProvider(Protocol):
    def generate(self, prompt: str) -> str:
        ...


class ProviderError(RuntimeError):
    def __init__(self, message: str, code: str = "provider_error") -> None:
        super().__init__(message)
        self.code = code


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
        return self._request(prompt, SYSTEM_PROMPT)

    def generate_spec(self, prompt: str) -> SceneSpec:
        raw = self._request(prompt, SCENE_SPEC_SYSTEM_PROMPT)
        try:
            data = json.loads(_strip_json_fence(raw))
            spec = SceneSpec.from_dict(data)
        except (json.JSONDecodeError, ValueError, TypeError) as exc:
            raise ProviderError(f"模型返回的 SceneSpec 无效：{exc}", "invalid_response") from exc
        if not spec.objects:
            raise ProviderError("模型返回的 SceneSpec 没有场景对象", "invalid_response")
        return spec

    def _request(self, prompt: str, system_prompt: str) -> str:
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
                    {"role": "system", "content": system_prompt},
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
            if exc.code in {401, 403}:
                raise ProviderError("API 密钥无效、无权限或套餐未开通", "authentication") from exc
            if exc.code == 429:
                raise ProviderError("模型请求过于频繁或套餐额度不足", "rate_limit") from exc
            if exc.code == 400:
                raise ProviderError("接口地址、模型名称或请求参数不正确", "configuration") from exc
            if exc.code >= 500:
                raise ProviderError("模型服务暂时不可用，请稍后重试", "service_unavailable") from exc
            raise ProviderError(f"大模型接口返回 HTTP {exc.code}", "http_error") from exc
        except TimeoutError as exc:
            raise ProviderError("大模型请求超时", "timeout") from exc
        except (URLError, OSError) as exc:
            raise ProviderError("无法连接大模型服务，请检查网络和 API 地址", "network") from exc
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
            raise ProviderError("大模型接口返回格式无效", "invalid_response") from exc
        if not isinstance(content, str) or not content.strip():
            raise ProviderError("大模型接口没有返回有效内容", "invalid_response")
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
        generate_spec = getattr(active_provider, "generate_spec", None)
        if callable(generate_spec):
            source = generate_code(generate_spec(prompt))
            source = validate_generated_source(source)
        else:
            source = _generate_validated_with_repair(active_provider, prompt)
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


def _generate_validated_with_repair(
    provider: SceneCodeProvider,
    prompt: str,
) -> str:
    """Ask once for a correction when otherwise usable model code is invalid."""
    raw_source = provider.generate(prompt)
    try:
        return validate_generated_source(raw_source)
    except ProviderError as first_error:
        repair_prompt = _build_repair_prompt(prompt, raw_source, first_error)
        repaired_source = provider.generate(repair_prompt)
        try:
            return validate_generated_source(repaired_source)
        except ProviderError as second_error:
            raise ProviderError(
                f"大模型自动修复后仍未通过检查：{second_error}"
            ) from second_error


def _build_repair_prompt(
    original_prompt: str,
    raw_source: str,
    error: ProviderError,
) -> str:
    source = raw_source[:MAX_REPAIR_SOURCE_LENGTH]
    return f"""你上一次生成的 ManimGL 代码未通过检查。请修复代码并只返回完整 Python 代码。
原始动画需求：
{original_prompt}

检查错误：
{error}

待修复代码：
{source}
"""


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
        elif isinstance(node, ast.Attribute) and node.attr.startswith("__"):
            raise ProviderError(f"禁止访问特殊属性：{node.attr}")
        elif isinstance(node, ast.Name) and node.id.startswith("__"):
            raise ProviderError(f"禁止访问特殊名称：{node.id}")


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


def _strip_json_fence(source: str) -> str:
    match = re.fullmatch(
        r"\s*```(?:json)?\s*\n(?P<data>.*?)\n```\s*",
        source,
        re.DOTALL | re.IGNORECASE,
    )
    return match.group("data") if match else source.strip()


def _default_transport(request: Request, timeout: float) -> bytes:
    with urlopen(request, timeout=timeout) as response:
        return response.read()
