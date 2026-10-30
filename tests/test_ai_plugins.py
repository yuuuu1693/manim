import ast
import json
import sys
import tempfile
import unittest
from pathlib import Path

from manimlib.ai import (
    OpenAICompatibleProvider,
    ProviderConfig,
    ProviderError,
    generate_code,
    generate_scene_source,
    parse_image,
    parse_prompt,
)
from manimlib.code_checker import apply_safe_fixes, check_code, detect_scene_names
from manimlib.gui.render_controller import (
    RenderRequest,
    build_render_args,
    get_preview_output_path,
)


class AIPluginTests(unittest.TestCase):
    def test_provider_parses_openai_compatible_response(self):
        captured = {}

        def transport(request, timeout):
            captured["url"] = request.full_url
            captured["authorization"] = request.headers["Authorization"]
            captured["payload"] = request.data.decode("utf-8")
            captured["timeout"] = timeout
            source = """from manimlib import *

class ModelScene(Scene):
    def construct(self):
        self.add(Circle())
        self.wait(1)
"""
            return json.dumps(
                {"choices": [{"message": {"content": f"```python\n{source}```"}}]}
            ).encode("utf-8")

        provider = OpenAICompatibleProvider(
            ProviderConfig("https://example.test/v1", "demo-model", "secret", 3),
            transport=transport,
        )
        result = generate_scene_source("画一个圆", mode="provider", provider=provider)
        self.assertEqual(result.backend, "provider")
        self.assertIn("class ModelScene(Scene)", result.source)
        self.assertEqual(captured["url"], "https://example.test/v1/chat/completions")
        self.assertEqual(captured["authorization"], "Bearer secret")
        self.assertEqual(captured["timeout"], 3)
        self.assertIn('"model": "demo-model"', captured["payload"])

    def test_invalid_provider_code_falls_back_to_local_rules(self):
        class UnsafeProvider:
            def generate(self, _prompt):
                return "from manimlib import *\nimport os\nos.system('whoami')"

        result = generate_scene_source(
            "画一个圆形",
            mode="auto",
            provider=UnsafeProvider(),
        )
        self.assertEqual(result.backend, "local")
        self.assertIn("circle_1 = Circle()", result.source)
        self.assertIn("回退到本地规则", result.warning)

    def test_provider_mode_requires_configuration(self):
        with self.assertRaisesRegex(ProviderError, "未配置大模型"):
            generate_scene_source(
                "画一个圆形",
                mode="provider",
                environ={},
            )

    def test_parse_multiple_objects_and_bind_action_to_latest(self):
        spec = parse_prompt("创建一个圆形和一个正方形，让正方形向右移动并旋转")
        self.assertEqual([obj.type for obj in spec.objects], ["circle", "square"])
        self.assertEqual(
            [action.type for action in spec.actions],
            ["create", "create", "move", "rotate"],
        )
        self.assertEqual(spec.actions[-1].target, "square_1")
        self.assertEqual(spec.actions[-2].parameters["direction"], "RIGHT")

    def test_generate_code_is_valid_and_uses_distinct_objects(self):
        source = generate_code(parse_prompt("画一个圆形和一个三角形，让三角形向上移动"))
        ast.parse(source)
        self.assertIn("circle_1 = Circle()", source)
        self.assertIn("triangle_1 = Triangle()", source)
        self.assertIn("triangle_1.animate.shift(UP)", source)

    def test_empty_and_unsupported_prompts_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "不能为空"):
            parse_prompt("   ")
        with self.assertRaisesRegex(ValueError, "暂未识别"):
            parse_prompt("绘制一条曲线")

    def test_checker_accepts_generated_scene(self):
        self.assertEqual(check_code(generate_code(parse_prompt("画一个圆形并旋转"))), [])

    def test_checker_reports_syntax_and_missing_construct(self):
        syntax = check_code("class Bad(Scene):\n  def construct(self)\n    pass")
        self.assertEqual(syntax[0].rule, "python-syntax")
        missing = check_code("class EmptyScene(Scene):\n    pass\n")
        self.assertEqual(missing[0].rule, "construct-method")

    def test_color_position_duration_and_explicit_target(self):
        spec = parse_prompt(
            "在左侧画一个红色圆形和右侧的蓝色正方形，让圆形向上移动持续2秒"
        )
        self.assertEqual(spec.objects[0].properties["color"], "RED")
        self.assertEqual(spec.objects[0].properties["position"], "LEFT")
        self.assertEqual(spec.objects[1].properties["color"], "BLUE")
        self.assertEqual(spec.objects[1].properties["position"], "RIGHT")
        self.assertEqual(spec.actions[-1].target, "circle_1")
        self.assertEqual(spec.actions[-1].parameters["duration"], 2.0)

        source = generate_code(spec)
        self.assertIn("Circle().set_color(RED).move_to(LEFT)", source)
        self.assertIn("Square().set_color(BLUE).move_to(RIGHT)", source)
        self.assertIn("circle_1.animate.shift(UP), run_time=2", source)

    def test_text_and_color_change(self):
        source = generate_code(
            parse_prompt('创建文字“你好 Manim”，让文字变为绿色持续1.5秒')
        )
        self.assertIn('Text("你好 Manim")', source)
        self.assertIn("text_1.animate.set_color(GREEN), run_time=1.5", source)

    def test_checker_reports_broad_except_and_unsafe_execution(self):
        source = """from manimlib import *

class UnsafeScene(Scene):
    def construct(self):
        try:
            eval("1 + 1")
        except Exception:
            self.play()
"""
        diagnostics = check_code(source)
        rules = {item.rule: item.severity for item in diagnostics}
        self.assertEqual(rules["unsafe-dynamic-execution"], "error")
        self.assertEqual(rules["empty-play"], "error")
        self.assertEqual(rules["broad-except"], "warning")
        self.assertTrue(all(item.suggestion for item in diagnostics))

    def test_checker_reports_invalid_transform_and_none_operation(self):
        source = """from manimlib import *

class InvalidScene(Scene):
    def construct(self):
        self.play(Transform(Circle()))
        value = None | "text"
"""
        diagnostics = check_code(source)
        rules = {item.rule for item in diagnostics}
        self.assertIn("transform-arguments", rules)
        self.assertIn("none-binary-operation", rules)

    def test_checker_reports_scope_errors_and_unused_parameters(self):
        source = """from manimlib import *

class ScopeScene(Scene):
    def helper(self, circle, duration):
        return circle

    def construct(self):
        self.play(ShowCreation(circel))
        count = count + 1
        ready = 0
        ready = ready + 1
"""
        diagnostics = check_code(source)
        by_rule = {item.rule: item for item in diagnostics}
        self.assertEqual(by_rule["undefined-variable"].message, "变量 circel 未定义")
        self.assertEqual(
            by_rule["used-before-assignment"].message,
            "变量 count 在赋值前被使用",
        )
        self.assertEqual(by_rule["unused-parameter"].severity, "warning")
        self.assertFalse(
            any(item.rule == "used-before-assignment" and "ready" in item.message
                for item in diagnostics)
        )

    def test_checker_accepts_generated_function_graph_scope(self):
        source = generate_code(parse_prompt("绘制函数 y=sin(x) 的图像"))
        self.assertEqual(check_code(source), [])

    def test_safe_fixes_correct_typo_and_empty_play(self):
        source = """from manimlib import *

class RepairScene(Scene):
    def construct(self):
        circle = Circle()
        self.play(ShowCreation(circel))
        self.play()
"""
        result = apply_safe_fixes(source)
        self.assertIn("ShowCreation(circle)", result.source)
        self.assertIn("        pass", result.source)
        self.assertEqual(
            {fix.rule for fix in result.applied},
            {"undefined-variable", "empty-play"},
        )
        self.assertEqual(result.remaining, ())

    def test_safe_fixes_leave_ambiguous_typo_for_manual_review(self):
        source = """from manimlib import *

class AmbiguousScene(Scene):
    def construct(self):
        circle_one = Circle()
        circle_two = Circle()
        self.add(circle_on)
"""
        result = apply_safe_fixes(source)
        self.assertEqual(result.source, source)
        self.assertFalse(result.applied)
        self.assertEqual(result.remaining[0].rule, "undefined-variable")

    def test_function_graph_generates_axes_and_safe_expression(self):
        source = generate_code(parse_prompt("绘制函数 y=x^2 的图像"))
        self.assertIn("axes_1 = Axes(", source)
        self.assertIn(
            "function_graph_1 = axes_1.get_graph(lambda x: x**2",
            source,
        )
        ast.parse(source)

    def test_common_math_function_is_namespaced(self):
        source = generate_code(parse_prompt("绘制函数 y=sin(x) 的图像"))
        self.assertIn("lambda x: np.sin(x)", source)

    def test_unsafe_function_expression_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unsupported"):
            generate_code(parse_prompt("绘制函数 y=__import__('os') 的图像"))

    def test_render_request_builds_argument_list_without_shell(self):
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory, "scene file.py")
            script.write_text("class DemoScene: pass", encoding="utf-8")
            request = RenderRequest(
                script=script,
                scene="DemoScene",
                python=Path(sys.executable),
                extra_args=("-p", "--no-video"),
            )
            self.assertEqual(
                request.command(),
                [
                    str(Path(sys.executable).resolve()),
                    "-m",
                    "manimlib",
                    str(script.resolve()),
                    "DemoScene",
                    "-p",
                    "--no-video",
                ],
            )

    def test_render_request_rejects_invalid_scene_name(self):
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory, "scene.py")
            script.write_text("", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "场景类名称无效"):
                RenderRequest(script, "bad scene", Path(sys.executable))

    def test_scene_detection_and_render_modes(self):
        source = """from manimlib import *

class FirstScene(Scene):
    def construct(self):
        pass

class Helper:
    pass

class SecondScene(InteractiveScene):
    def construct(self):
        pass
"""
        self.assertEqual(
            detect_scene_names(source),
            ["FirstScene", "SecondScene"],
        )
        self.assertEqual(build_render_args("实时预览", "低清 480p"), [])
        self.assertEqual(
            build_render_args("保存最终帧", "中清 720p"),
            ["-s", "-w", "-m"],
        )
        self.assertEqual(
            build_render_args("导出视频", "高清 1080p"),
            ["-w", "--hd"],
        )
        root = Path("preview-root")
        self.assertIsNone(get_preview_output_path(root, "demo", "实时预览"))
        self.assertEqual(
            get_preview_output_path(root, "demo", "保存最终帧").name,
            "demo.png",
        )
        self.assertEqual(
            get_preview_output_path(root, "demo", "导出视频").name,
            "demo.mp4",
        )

    def test_image_parser_recognizes_colored_circle_and_square(self):
        import cv2
        import numpy as np

        with tempfile.TemporaryDirectory() as directory:
            image = np.full((300, 500, 3), 255, dtype=np.uint8)
            cv2.circle(image, (110, 150), 55, (0, 0, 255), thickness=-1)
            cv2.rectangle(image, (330, 95), (440, 205), (255, 0, 0), thickness=-1)
            path = Path(directory, "shapes.png")
            cv2.imwrite(str(path), image)

            spec = parse_image(path)
            self.assertEqual([obj.type for obj in spec.objects], ["circle", "square"])
            self.assertEqual(spec.objects[0].properties["color"], "RED")
            self.assertEqual(spec.objects[0].properties["position"], "LEFT")
            self.assertEqual(spec.objects[1].properties["color"], "BLUE")
            self.assertEqual(spec.objects[1].properties["position"], "RIGHT")
            ast.parse(generate_code(spec))


if __name__ == "__main__":
    unittest.main()
