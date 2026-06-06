from __future__ import annotations

from pathlib import Path

from scripts.registry.static_security_scan import scan_directory


def test_scan_directory_passes_clean_plugin(tmp_path: Path) -> None:
    plugin = tmp_path / "demo"
    plugin.mkdir()
    (plugin / "plugin.py").write_text("class DemoPlugin:\n    pass\n", encoding="utf-8")

    result = scan_directory(plugin)

    assert result["pass"] is True
    assert result["findings"] == []


def test_scan_directory_blocks_eval(tmp_path: Path) -> None:
    plugin = tmp_path / "demo"
    plugin.mkdir()
    (plugin / "plugin.py").write_text("eval(user_input)\n", encoding="utf-8")

    result = scan_directory(plugin)

    assert result["pass"] is False
    assert result["findings"][0]["rule"] == "raw-eval"


def test_scan_directory_does_not_block_eval_in_string(tmp_path: Path) -> None:
    plugin = tmp_path / "demo"
    plugin.mkdir()
    (plugin / "plugin.py").write_text("text = 'eval(user_input)'\n", encoding="utf-8")

    result = scan_directory(plugin)

    assert result["pass"] is True


def test_scan_directory_blocks_shell_true_popen(tmp_path: Path) -> None:
    plugin = tmp_path / "demo"
    plugin.mkdir()
    (plugin / "plugin.py").write_text("import subprocess\nsubprocess.Popen('whoami', shell=True)\n", encoding="utf-8")

    result = scan_directory(plugin)

    assert result["pass"] is False
    assert result["findings"][0]["rule"] == "subprocess-shell"


def test_scan_directory_allows_shell_false_subprocess(tmp_path: Path) -> None:
    plugin = tmp_path / "demo"
    plugin.mkdir()
    (plugin / "plugin.py").write_text("import subprocess\nsubprocess.run(['whoami'], shell=False)\n", encoding="utf-8")

    result = scan_directory(plugin)

    assert result["pass"] is True


def test_scan_directory_blocks_credential_literal(tmp_path: Path) -> None:
    plugin = tmp_path / "demo"
    plugin.mkdir()
    (plugin / "plugin.py").write_text("AWS_SECRET_ACCESS_KEY = 'abc'\n", encoding="utf-8")

    result = scan_directory(plugin)

    assert result["pass"] is False
    assert result["findings"][0]["rule"] == "credential-literal"
