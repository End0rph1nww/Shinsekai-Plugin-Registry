from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.registry.validate_plugins import RegistryValidationError, main, validate_registry


def valid_entry(**overrides: object) -> dict[str, object]:
    entry: dict[str, object] = {
        "name": "demo_plugin",
        "author": "End0rph1n",
        "repo": "owner/demo-plugin",
        "description": "Long description",
        "entry": "plugins.demo.plugin:DemoPlugin",
    }
    entry.update(overrides)
    return entry


def test_current_array_shape_is_valid() -> None:
    validate_registry([valid_entry()])


def test_object_shape_is_valid() -> None:
    validate_registry({"demo_plugin": valid_entry()})


def test_object_shape_uses_key_as_name() -> None:
    entry = valid_entry()
    entry.pop("name")

    validate_registry({"demo_plugin": entry})


def test_plugins_object_shape_is_valid() -> None:
    validate_registry({"plugins": {"demo_plugin": valid_entry()}})


def test_repo_can_be_full_github_url() -> None:
    validate_registry([valid_entry(repo="https://github.com/owner/demo-plugin")])


def test_invalid_repo_fails() -> None:
    with pytest.raises(RegistryValidationError, match="repo must"):
        validate_registry([valid_entry(repo="https://example.com/owner/demo-plugin")])


def test_repo_ending_git_fails() -> None:
    with pytest.raises(RegistryValidationError, match="must not end"):
        validate_registry([valid_entry(repo="owner/demo-plugin.git")])


def test_missing_entry_fails() -> None:
    entry = valid_entry()
    entry.pop("entry")

    with pytest.raises(RegistryValidationError, match="entry is required"):
        validate_registry([entry])


def test_duplicate_name_fails() -> None:
    with pytest.raises(RegistryValidationError, match="duplicate"):
        validate_registry([valid_entry(), valid_entry()])


def test_too_many_tags_fails() -> None:
    with pytest.raises(RegistryValidationError, match="at most 5"):
        validate_registry([valid_entry(tags=["a", "b", "c", "d", "e", "f"])])


def test_desc_length_is_checked_when_desc_field_is_present() -> None:
    with pytest.raises(RegistryValidationError, match="200 characters"):
        validate_registry([valid_entry(desc="x" * 201)])


def test_cli_validates_current_registry_file() -> None:
    repo_root = Path(__file__).resolve().parents[1]

    assert main([str(repo_root / "plugins.json")]) == 0


def test_cli_reports_invalid_json_file(tmp_path: Path) -> None:
    plugins = tmp_path / "plugins.json"
    plugins.write_text(json.dumps([valid_entry(repo="bad repo")]), encoding="utf-8")

    assert main([str(plugins)]) == 1
