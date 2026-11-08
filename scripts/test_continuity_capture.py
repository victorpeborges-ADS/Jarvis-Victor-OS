"""Testes sintéticos do capturador de continuidade (sem rede)."""
from __future__ import annotations
import importlib.util
import json
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest

MODULE = Path(__file__).with_name("continuity_capture.py")
spec = importlib.util.spec_from_file_location("continuity_capture", MODULE)
cc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cc)


class TestContinuity(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        def call(*args):
            subprocess.run(["git", "-C", str(self.repo), *args], check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        call("init", "-q")
        call("config", "user.name", "Synthetic QA")
        call("config", "user.email", "qa@example.test")
        (self.repo / "README.md").write_text("segredo-ficticio-arquivo")
        call("add", "README.md")
        call("commit", "-m", "synthetic initial", "-q")

    def tearDown(self):
        self.tmp.cleanup()

    def test_capture_is_private_metadata_only(self):
        (self.repo / "nome-super-privado.txt").write_text("segredo-ficticio")
        info, output = cc.capture(self.repo, "manual")
        raw = output.read_text()
        self.assertEqual(info["untracked_files"], 1)
        self.assertNotIn("nome-super-privado", raw)
        self.assertNotIn("segredo-ficticio", raw)
        self.assertNotIn("qa@example.test", raw)
        if os.name == "posix":
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)
            self.assertEqual(output.parent.stat().st_mode & 0o777, 0o700)

    def test_resume_uses_existing_checkpoint(self):
        cc.capture(self.repo, "before")
        prompt = cc.resume(self.repo)
        self.assertIn("AGENTS.md", prompt)
        self.assertIn("Verifique o estado ATUAL", prompt)

    def test_wrapper_snapshots_without_shell(self):
        cmd = [sys.executable, str(MODULE), "--repo", str(self.repo), "run", "--",
               sys.executable, "-c", "print('synthetic')"]
        r = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        _, target = cc.paths(self.repo)
        data = json.loads(target.read_text())
        self.assertEqual(data["event"], "after")
        self.assertEqual(data["exit_code"], 0)

    def test_wrapper_preserves_failure_status(self):
        cmd = [sys.executable, str(MODULE), "--repo", str(self.repo), "run", "--",
               sys.executable, "-c", "import sys;sys.exit(17)"]
        r = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(r.returncode, 17)
        _, target = cc.paths(self.repo)
        data = json.loads(target.read_text())
        self.assertEqual(data["exit_code"], 17)

    def test_invalid_event_fails_without_writing(self):
        with self.assertRaises(ValueError):
            cc.capture(self.repo, "unknown")
        _, target = cc.paths(self.repo)
        self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main()
