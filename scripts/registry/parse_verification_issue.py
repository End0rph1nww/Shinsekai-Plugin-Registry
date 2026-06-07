from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


FENCED_JSON_RE = re.compile(r"```json\s*(\{.*?\})\s*```", re.IGNORECASE | re.DOTALL)
NOTES_RE = re.compile(r"### Notes for Maintainers\s*(.*?)(?:\n### |\Z)", re.IGNORECASE | re.DOTALL)
REQUIRED_FIELDS = ("plugin_name",)


class VerificationIssueError(ValueError):
    """Raised when a verification issue cannot be parsed."""


def _as_string(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _single_line(value: str) -> str:
    return " ".join(value.split())


def parse_verification_payload(body: str) -> dict[str, str]:
    for match in FENCED_JSON_RE.finditer(body):
        try:
            payload = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        parsed = {
            "plugin_name": _as_string(payload.get("plugin_name") or payload.get("name")),
            "reviewed_commit": _as_string(payload.get("commit_sha") or payload.get("reviewed_commit")),
            "reviewed_version": _as_string(payload.get("version") or payload.get("reviewed_version")),
            "package_sha256": _as_string(payload.get("package_sha256") or payload.get("sha256")),
            "package_url": _as_string(payload.get("package_url") or payload.get("download_url")),
            "reason": _single_line(_as_string(payload.get("reason"))),
        }
        missing = [field for field in REQUIRED_FIELDS if not parsed[field]]
        if missing:
            raise VerificationIssueError(f"verification payload is missing {', '.join(missing)}.")
        return parsed
    raise VerificationIssueError("issue body must contain a fenced JSON verification payload.")


def parse_reviewer_notes(body: str) -> str:
    match = NOTES_RE.search(body)
    if not match:
        return ""
    notes = match.group(1).strip()
    if notes.lower() in {"_no response_", "no response"}:
        return ""
    return _single_line(notes)


def parse_issue_event(event: dict[str, Any]) -> dict[str, str]:
    issue = event.get("issue") if isinstance(event.get("issue"), dict) else {}
    body = _as_string(issue.get("body"))
    payload = parse_verification_payload(body)
    issue_number = _as_string(issue.get("number"))
    issue_url = _as_string(issue.get("html_url"))
    notes = parse_reviewer_notes(body)
    reason = payload.get("reason", "")
    note_parts = [part for part in (notes, reason, f"Verification request issue #{issue_number}" if issue_number else "", issue_url) if part]
    payload["notes"] = " | ".join(note_parts)
    payload["issue_number"] = issue_number
    payload["issue_url"] = issue_url
    return payload


def write_github_outputs(path: Path, outputs: dict[str, str]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        for key, value in outputs.items():
            handle.write(f"{key}={_single_line(value)}\n")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Parse a plugin verification issue event.")
    parser.add_argument("--event-path", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=None)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        event = json.loads(args.event_path.read_text(encoding="utf-8"))
        outputs = parse_issue_event(event)
        if args.output:
            write_github_outputs(args.output, outputs)
        else:
            print(json.dumps(outputs, ensure_ascii=False, indent=2))
    except (json.JSONDecodeError, OSError, VerificationIssueError) as exc:
        print(f"error: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
