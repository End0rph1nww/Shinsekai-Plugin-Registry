from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.registry.parse_issue_submission import (
    SubmissionError,
    build_registry_entry,
    extract_json_block,
    main,
    update_registry,
)


def issue_body(payload: str) -> str:
    return f"Please review this plugin.\n\n```json\n{payload}\n```\n"


def valid_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "display_name": "Demo Plugin",
        "desc": "Short description",
        "author": "End0rph1n",
        "repo": "https://github.com/owner/shinsekai-plugin-demo",
        "entry": "plugins.demo.plugin:DemoPlugin",
        "tags": ["tool", "demo"],
        "social_link": "https://github.com/owner",
    }
    payload.update(overrides)
    return payload


def test_extracts_first_fenced_json_block() -> None:
    payload = extract_json_block(issue_body(json.dumps(valid_payload())))

    assert payload["display_name"] == "Demo Plugin"


def test_missing_fenced_block_fails() -> None:
    with pytest.raises(SubmissionError, match="Missing fenced"):
        extract_json_block("no json here")


def test_malformed_json_fails() -> None:
    with pytest.raises(SubmissionError, match="Malformed JSON"):
        extract_json_block("```json\n{\n```")


def test_build_entry_from_valid_payload_derives_name_and_normalizes_repo() -> None:
    entry = build_registry_entry(valid_payload())

    assert entry == {
        "name": "shinsekai_plugin_demo",
        "display_name": "Demo Plugin",
        "author": "End0rph1n",
        "repo": "owner/shinsekai-plugin-demo",
        "description": "Short description",
        "desc": "Short description",
        "entry": "plugins.demo.plugin:DemoPlugin",
        "tags": ["tool", "demo"],
        "social_link": "https://github.com/owner",
    }


def test_name_overrides_repo_derived_name() -> None:
    entry = build_registry_entry(valid_payload(name="custom_plugin"))

    assert entry["name"] == "custom_plugin"


def test_invalid_repo_url_fails() -> None:
    with pytest.raises(SubmissionError, match="repo must use"):
        build_registry_entry(valid_payload(repo="https://example.com/owner/repo"))


def test_repo_url_ending_git_fails() -> None:
    with pytest.raises(SubmissionError, match="must not end with .git"):
        build_registry_entry(valid_payload(repo="https://github.com/owner/repo.git"))


def test_too_many_tags_fails() -> None:
    with pytest.raises(SubmissionError, match="at most 5"):
        build_registry_entry(valid_payload(tags=["a", "b", "c", "d", "e", "f"]))


def test_missing_entry_fails() -> None:
    payload = valid_payload()
    payload.pop("entry")

    with pytest.raises(SubmissionError, match="entry is required"):
        build_registry_entry(payload)


def test_desc_too_long_fails() -> None:
    with pytest.raises(SubmissionError, match="200 characters"):
        build_registry_entry(valid_payload(desc="x" * 201))


def test_update_existing_plugin_in_list_registry() -> None:
    registry = [{"name": "shinsekai_plugin_demo", "author": "old"}]
    entry = build_registry_entry(valid_payload(author="new"))

    updated = update_registry(registry, entry)

    assert len(updated) == 1
    assert updated[0]["author"] == "new"


def test_cli_updates_plugins_json_and_writes_summary(tmp_path: Path) -> None:
    issue = tmp_path / "issue.md"
    registry = tmp_path / "plugins.json"
    summary = tmp_path / "summary.md"
    issue.write_text(issue_body(json.dumps(valid_payload())), encoding="utf-8")
    registry.write_text("[]", encoding="utf-8")

    code = main(
        [
            "--issue-body-file",
            str(issue),
            "--plugins-json",
            str(registry),
            "--output",
            str(registry),
            "--summary-file",
            str(summary),
        ]
    )

    assert code == 0
    assert json.loads(registry.read_text(encoding="utf-8"))[0]["name"] == "shinsekai_plugin_demo"
    assert "shinsekai_plugin_demo" in summary.read_text(encoding="utf-8")
