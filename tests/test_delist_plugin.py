from __future__ import annotations

import json
from pathlib import Path

from scripts.registry.delist_plugin import delist_plugin, main


def test_delist_plugin_removes_named_plugin_from_array() -> None:
    registry = [
        {
            "name": "keep_plugin",
            "author": "Chihiro",
            "repo": "owner/keep",
            "description": "Keep this plugin",
            "entry": "keep.plugin:Plugin",
        },
        {
            "name": "remove_plugin",
            "author": "Chihiro",
            "repo": "owner/remove",
            "description": "Remove this plugin",
            "entry": "remove.plugin:Plugin",
        },
    ]

    updated = delist_plugin(registry, plugin_name="remove_plugin")

    assert [entry["name"] for entry in updated] == ["keep_plugin"]


def test_delist_plugin_removes_named_plugin_from_object_key() -> None:
    registry = {
        "plugins": {
            "keep_plugin": {
                "author": "Chihiro",
                "repo": "owner/keep",
                "description": "Keep this plugin",
                "entry": "keep.plugin:Plugin",
            },
            "remove_plugin": {
                "author": "Chihiro",
                "repo": "owner/remove",
                "description": "Remove this plugin",
                "entry": "remove.plugin:Plugin",
            },
        }
    }

    updated = delist_plugin(registry, plugin_name="remove_plugin")

    assert list(updated["plugins"]) == ["keep_plugin"]


def test_cli_fails_when_plugin_is_not_found(tmp_path: Path, capsys) -> None:
    plugins = tmp_path / "plugins.json"
    plugins.write_text(
        json.dumps(
            [
                {
                    "name": "keep_plugin",
                    "author": "Chihiro",
                    "repo": "owner/keep",
                    "description": "Keep this plugin",
                    "entry": "keep.plugin:Plugin",
                }
            ]
        ),
        encoding="utf-8",
    )

    code = main(
        [
            "--plugins-json",
            str(plugins),
            "--output",
            str(plugins),
            "--plugin-name",
            "missing_plugin",
        ]
    )

    captured = capsys.readouterr()
    assert code == 1
    assert "plugin not found: missing_plugin" in captured.out
