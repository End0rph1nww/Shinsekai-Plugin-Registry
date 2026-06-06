from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path
from typing import Any


TEXT_SUFFIXES = {
    ".py",
    ".txt",
    ".md",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".cfg",
    ".env",
}

TEXT_RULES: list[tuple[str, re.Pattern[str], str]] = [
    (
        "suspicious-exfiltration",
        re.compile(r"(discord(?:app)?\.com/api/webhooks|api\.telegram\.org/bot|pastebin\.com|webhook\.site)", re.IGNORECASE),
        "suspicious exfiltration endpoint literal",
    ),
    (
        "credential-literal",
        re.compile(
            r"(AWS_SECRET_ACCESS_KEY|R2_SECRET_ACCESS_KEY|SECRET_ACCESS_KEY|GITHUB_TOKEN|-----BEGIN [A-Z ]*PRIVATE KEY-----)",
            re.IGNORECASE,
        ),
        "credential-looking literal",
    ),
]
BLOCKED_BUILTINS = {"eval", "exec", "compile"}
SUBPROCESS_CALLS = {"Popen", "run", "call", "check_call", "check_output"}


def iter_text_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() in TEXT_SUFFIXES or path.name.lower() in {".env", "requirements.txt"}:
            files.append(path)
    return files


def finding(rule: str, message: str, path: Path, root: Path, line: int) -> dict[str, Any]:
    return {
        "rule": rule,
        "message": message,
        "path": path.relative_to(root).as_posix(),
        "line": line,
    }


def dotted_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = dotted_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    return ""


def scan_python_ast(path: Path, root: Path, text: str) -> list[dict[str, Any]]:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []

    findings: list[dict[str, Any]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = dotted_name(node.func)
        if name in BLOCKED_BUILTINS:
            findings.append(finding(f"raw-{name}", f"raw {name}() call", path, root, node.lineno))
            continue
        if name == "os.system":
            findings.append(finding("os-system", "os.system() call", path, root, node.lineno))
            continue
        if name.startswith("subprocess.") and name.rsplit(".", 1)[-1] in SUBPROCESS_CALLS:
            for keyword in node.keywords:
                if keyword.arg == "shell" and isinstance(keyword.value, ast.Constant) and keyword.value.value is True:
                    findings.append(
                        finding("subprocess-shell", "subprocess call with shell=True", path, root, node.lineno)
                    )
                    break
    return findings


def scan_file(path: Path, root: Path) -> list[dict[str, Any]]:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = path.read_text(encoding="utf-8", errors="ignore")

    findings: list[dict[str, Any]] = []
    if path.suffix.lower() == ".py":
        findings.extend(scan_python_ast(path, root, text))
    for rule, pattern, message in TEXT_RULES:
        match = pattern.search(text)
        if not match:
            continue
        line = text.count("\n", 0, match.start()) + 1
        findings.append(finding(rule, message, path, root, line))
    return findings


def scan_directory(root: Path) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    for path in iter_text_files(root):
        findings.extend(scan_file(path, root))

    passed = not findings
    return {
        "pass": passed,
        "msg": "No blocked patterns found." if passed else f"{len(findings)} blocked pattern(s) found.",
        "findings": findings,
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a minimal static security scan over a plugin directory.")
    parser.add_argument("path", type=Path)
    parser.add_argument("--output", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    result = scan_directory(args.path)
    text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
