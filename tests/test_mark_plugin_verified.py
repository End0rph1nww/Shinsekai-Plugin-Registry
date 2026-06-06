from __future__ import annotations

import json
from pathlib import Path

from scripts.registry.mark_plugin_verified import main, mark_plugin_verified


def test_mark_plugin_verified_updates_review_fields() -> None:
    registry = [
        {
            "name": "demo_plugin",
            "author": "End0rph1n",
            "repo": "owner/demo",
            "description": "Demo",
            "entry": "plugins.demo.plugin:DemoPlugin",
            "trust_level": "community",
            "verified": False,
        }
    ]

    updated = mark_plugin_verified(
        registry,
        plugin_name="demo_plugin",
        reviewed_by="RachelForster",
        reviewed_at="2026-06-06",
        reviewed_commit="abcdef123456",
        reviewed_version="v1.0.0",
        notes="Reviewed source and dependencies.",
    )

    entry = updated[0]
    assert entry["trust_level"] == "verified"
    assert entry["verified"] is True
    assert entry["review"]["status"] == "maintainer_verified"
    assert entry["review"]["reviewed_commit"] == "abcdef123456"


def test_cli_infers_commit_and_version_from_generated_registry(tmp_path: Path) -> None:
    plugins = tmp_path / "plugins.json"
    generated = tmp_path / "plugin_cache_original.json"
    plugins.write_text(
        json.dumps(
            [
                {
                    "name": "demo_plugin",
                    "author": "End0rph1n",
                    "repo": "owner/demo",
                    "description": "Demo",
                    "entry": "plugins.demo.plugin:DemoPlugin",
                }
            ]
        ),
        encoding="utf-8",
    )
    generated.write_text(
        json.dumps(
            {
                "demo_plugin": {
                    "name": "demo_plugin",
                    "commit_sha": "abcdef123456",
                    "version": "v1.0.0",
                }
            }
        ),
        encoding="utf-8",
    )

    code = main(
        [
            "--plugins-json",
            str(plugins),
            "--generated-registry",
            str(generated),
            "--output",
            str(plugins),
            "--plugin-name",
            "demo_plugin",
            "--reviewed-by",
            "RachelForster",
            "--reviewed-at",
            "2026-06-06",
            "--notes",
            "Reviewed source and dependencies.",
        ]
    )

    entry = json.loads(plugins.read_text(encoding="utf-8"))[0]
    assert code == 0
    assert entry["review"]["reviewed_commit"] == "abcdef123456"
    assert entry["review"]["reviewed_version"] == "v1.0.0"
