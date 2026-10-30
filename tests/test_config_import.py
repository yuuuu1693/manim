import subprocess
import sys
import unittest

from manimlib.config import _is_manim_cli_entrypoint, parse_cli


class ConfigImportTests(unittest.TestCase):
    def test_library_import_ignores_host_application_arguments(self):
        code = (
            "import sys; "
            "sys.argv = ['host-tool', '--host-only-flag', 'host-value']; "
            "import manimlib; "
            "print(manimlib.manim_config.run.file_name)"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "None")

    def test_cli_parser_still_accepts_explicit_arguments(self):
        args = parse_cli(["example.py", "DemoScene", "--hd", "-w"])
        self.assertEqual(args.file, "example.py")
        self.assertEqual(args.scene_names, ["DemoScene"])
        self.assertTrue(args.hd)
        self.assertTrue(args.write_file)

    def test_python_module_invocation_is_detected_before_main_loads(self):
        self.assertTrue(
            _is_manim_cli_entrypoint(
                argv0="python.exe",
                original_argv=["python.exe", "-m", "manimlib", "scene.py"],
            )
        )


if __name__ == "__main__":
    unittest.main()
