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
    classify_render_failure,
    parse_render_progress,
)


class AIPluginTests(unittest.TestCase):
    def test_provider_parses_openai_compatible_response(self):
        captured = {}

        def transport(request, timeout):
            captured["url"] = request.full_url
            captured["authorization"] = request.headers["Authorization"]
            captured["payload"] = request.data.decode("utf-8")
            captured["timeout"] = timeout
            return json.dumps(
                {"choices": [{"message": {"content": json.dumps({
                    "objects": [{"name": "circle_1", "type": "circle"}],
                    "actions": [{"type": "create", "target": "circle_1"}],
                })}}]}
            ).encode("utf-8")

        provider = OpenAICompatibleProvider(
            ProviderConfig("https://example.test/v1", "demo-model", "secret", 3),
            transport=transport,
        )
        result = generate_scene_source("画一个圆", mode="provider", provider=provider)
        self.assertEqual(result.backend, "provider")
        self.assertIn("circle_1 = Circle()", result.source)
        self.assertEqual(captured["url"], "https://example.test/v1/chat/completions")
        self.assertEqual(captured["authorization"], "Bearer secret")
        self.assertEqual(captured["timeout"], 3)
        self.assertIn('"model": "demo-model"', captured["payload"])
        self.assertIn("objects", captured["payload"])
        self.assertIn("actions", captured["payload"])

    def test_scene_spec_rejects_unknown_references(self):
        from manimlib.ai.models import SceneSpec

        with self.assertRaisesRegex(ValueError, "Unknown action target"):
            SceneSpec.from_dict({
                "objects": [{"name": "circle_1", "type": "circle"}],
                "actions": [{"type": "move", "target": "missing"}],
            })

    def test_provider_classifies_rate_limit_error(self):
        from io import BytesIO
        from urllib.error import HTTPError

        def transport(request, timeout):
            raise HTTPError(request.full_url, 429, "limited", {}, BytesIO())

        provider = OpenAICompatibleProvider(
            ProviderConfig("https://example.test/v1", "glm-5.3", "secret"),
            transport=transport,
        )
        with self.assertRaisesRegex(ProviderError, "额度不足") as caught:
            provider.generate_spec("画一个圆")
        self.assertEqual(caught.exception.code, "rate_limit")

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

    def test_provider_repairs_invalid_code_once(self):
        class RepairingProvider:
            def __init__(self):
                self.prompts = []

            def generate(self, prompt):
                self.prompts.append(prompt)
                if len(self.prompts) == 1:
                    return "from manimlib import *\nclass Broken(Scene):\n def construct(self)"
                return """from manimlib import *

class RepairedScene(Scene):
    def construct(self):
        self.add(Circle())
        self.wait(1)
"""

        provider = RepairingProvider()
        result = generate_scene_source("画一个圆", mode="provider", provider=provider)
        self.assertEqual(result.backend, "provider")
        self.assertIn("class RepairedScene(Scene)", result.source)
        self.assertEqual(len(provider.prompts), 2)
        self.assertIn("检查错误", provider.prompts[1])
        self.assertIn("原始动画需求", provider.prompts[1])

    def test_provider_repair_failure_falls_back_in_auto_mode(self):
        class AlwaysBrokenProvider:
            def __init__(self):
                self.calls = 0

            def generate(self, _prompt):
                self.calls += 1
                return "not valid python !!!"

        provider = AlwaysBrokenProvider()
        result = generate_scene_source("画一个圆形", mode="auto", provider=provider)
        self.assertEqual(provider.calls, 2)
        self.assertEqual(result.backend, "local")
        self.assertIn("自动修复后仍未通过检查", result.warning)

    def test_provider_validation_rejects_indirect_builtin_access(self):
        class UnsafeProvider:
            def generate(self, _prompt):
                return """from manimlib import *

class UnsafeScene(Scene):
    def construct(self):
        getattr(__builtins__, "open")("unsafe.txt", "w")
        self.wait(1)
"""

        with self.assertRaisesRegex(ProviderError, "自动修复后仍未通过检查"):
            generate_scene_source("画一个圆", mode="provider", provider=UnsafeProvider())

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

    def test_square_can_be_inscribed_in_circle(self):
        source = generate_code(parse_prompt("创建一个圆和一个正方形，让正方形内接圆"))
        self.assertIn(
            "square_1.set_width(circle_1.get_width() / np.sqrt(2)).move_to(circle_1)",
            source,
        )
        self.assertEqual(check_code(source), [])

    def test_shapes_can_overlap_by_percentage(self):
        source = generate_code(parse_prompt("创建一个圆和一个正方形，让两个图形按50%重叠"))
        self.assertIn(
            "buff=-min(circle_1.get_width(), square_1.get_width()) * 0.5",
            source,
        )
        reversed_source = generate_code(
            parse_prompt("创建一个圆和一个正方形，让两个图形重叠30%")
        )
        self.assertIn("* 0.3", reversed_source)

    def test_shapes_can_be_automatically_tangent(self):
        source = generate_code(parse_prompt("创建一个圆和一个正方形，让两个图形相切"))
        self.assertIn("square_1.next_to(circle_1, RIGHT, buff=0)", source)

    def test_shape_can_be_centered_in_annulus(self):
        source = generate_code(parse_prompt("创建一个蓝色圆环和一个红色三角形，让三角形在圆环中心"))
        self.assertIn("annulus_1 = Annulus(inner_radius=0.8, outer_radius=1.5)", source)
        self.assertIn("triangle_1.move_to(annulus_1)", source)
        combined = generate_code(
            parse_prompt("创建一个圆环和一个正方形，让它们自动居中组合")
        )
        self.assertIn("square_1.move_to(annulus_1)", combined)
        self.assertIn("group_1 = VGroup(annulus_1, square_1)", combined)

    def test_group_moves_and_scales_as_one_object(self):
        source = generate_code(
            parse_prompt(
                "创建一个圆和一个正方形，将两个图形作为一个整体向右移动2个单位并缩放2倍"
            )
        )
        self.assertIn("group_1 = VGroup(circle_1, square_1)", source)
        self.assertIn("group_1.animate.shift(RIGHT * 2)", source)
        self.assertIn("group_1.animate.scale(2)", source)

    def test_irregular_triangle_uses_scalene_vertices(self):
        source = generate_code(parse_prompt("创建一个紫色不规则三角形并旋转"))
        self.assertIn("irregular_triangle_1 = Polygon(np.array(", source)
        self.assertIn(".set_color(PURPLE)", source)
        self.assertIn("Rotate(irregular_triangle_1)", source)
        self.assertEqual(check_code(source), [])

    def test_irregular_triangle_accepts_three_side_lengths(self):
        source = generate_code(
            parse_prompt("创建一个三边长为3、4、5的不规则三角形")
        )
        self.assertIn("Polygon(np.array(", source)
        self.assertNotIn("Triangle()", source)
        with self.assertRaisesRegex(ValueError, "三角形条件"):
            parse_prompt("创建一个三边长为1、2、5的不规则三角形")

    def test_square_and_triangular_pyramids_generate_3d_scenes(self):
        square_source = generate_code(parse_prompt("创建一个蓝色四棱锥并旋转"))
        self.assertIn("class GeneratedScene(ThreeDScene):", square_source)
        self.assertIn("pyramid_1 = VGroup3D(", square_source)
        self.assertEqual(square_source.count("Polygon("), 5)
        self.assertIn("Rotate(pyramid_1, axis=UP)", square_source)
        triangular_source = generate_code(parse_prompt("创建一个红色三棱锥"))
        self.assertEqual(triangular_source.count("Polygon("), 4)
        self.assertEqual(check_code(triangular_source), [])

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

    def test_extended_shape_templates_generate_valid_code(self):
        source = generate_code(
            parse_prompt("创建一个点、一条直线、一个箭头、一个长方形和一个椭圆")
        )
        self.assertIn("dot_1 = Dot()", source)
        self.assertIn("line_1 = Line(LEFT, RIGHT)", source)
        self.assertIn("arrow_1 = Arrow(LEFT, RIGHT)", source)
        self.assertIn("rectangle_1 = Rectangle(width=3, height=2)", source)
        self.assertIn("ellipse_1 = Ellipse(width=3, height=2)", source)
        self.assertNotIn("circle_1", source)
        self.assertNotIn("square_1", source)
        self.assertEqual(check_code(source), [])

    def test_diagonal_distance_fade_out_and_wait(self):
        source = generate_code(
            parse_prompt(
                "创建一个蓝色圆点，让圆点向右上移动2个单位持续3秒然后淡出，等待2秒"
            )
        )
        self.assertIn("Dot().set_color(BLUE)", source)
        self.assertIn("dot_1.animate.shift(UR * 2), run_time=3", source)
        self.assertIn("FadeOut(dot_1), run_time=3", source)
        self.assertIn("self.wait(2)", source)

    def test_fade_in_replaces_default_creation_animation(self):
        source = generate_code(parse_prompt("让一个矩形淡入"))
        self.assertIn("self.play(FadeIn(rectangle_1))", source)
        self.assertNotIn("ShowCreation(rectangle_1)", source)

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

    def test_render_failure_diagnostics_and_progress(self):
        self.assertIn("FFmpeg", classify_render_failure("ffmpeg was not found"))
        self.assertIn("LaTeX", classify_render_failure("xelatex: command not found"))
        self.assertIn("OpenGL", classify_render_failure("GLFW OpenGL init failed"))
        self.assertIn("依赖", classify_render_failure("ModuleNotFoundError: No module named 'cv2'"))
        self.assertIsNone(classify_render_failure("ordinary scene exception"))
        self.assertEqual(parse_render_progress("Rendering 47.6%"), 48)
        self.assertEqual(parse_render_progress("10% then 100%"), 100)
        self.assertIsNone(parse_render_progress("Rendering frame 12"))

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
