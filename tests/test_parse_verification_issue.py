from __future__ import annotations

import json

from scripts.registry.parse_verification_issue import parse_issue_event, parse_verification_payload


def test_parse_verification_payload_reads_fenced_json() -> None:
    payload = parse_verification_payload(
        """
        ### Verification Info

        ```json
        {
          "plugin_name": "cloud_tts",
          "repo": "https://github.com/End0rph1nww/Shinsekai-Cloud-TTS",
          "version": "v0.0.0",
          "commit_sha": "8f3d262ac388",
          "package_sha256": "abc123",
          "package_url": "https://example.com/cloud_tts.zip",
          "reason": "Reviewed and ready"
        }
        ```
        """
    )

    assert payload["plugin_name"] == "cloud_tts"
    assert payload["reviewed_commit"] == "8f3d262ac388"
    assert payload["reviewed_version"] == "v0.0.0"
    assert payload["package_sha256"] == "abc123"
    assert payload["reason"] == "Reviewed and ready"


def test_parse_issue_event_builds_review_notes() -> None:
    event = {
        "issue": {
            "number": 12,
            "html_url": "https://github.com/owner/registry/issues/12",
            "body": """
### Verification Info

```json
{
  "plugin_name": "cloud_tts",
  "version": "v0.0.0",
  "commit_sha": "8f3d262ac388",
  "reason": "Maintainer checked the package diff"
}
```

### Notes for Maintainers

Source, dependencies, entry point, and package diff reviewed.
""",
        }
    }

    parsed = parse_issue_event(json.loads(json.dumps(event)))

    assert parsed["plugin_name"] == "cloud_tts"
    assert parsed["reviewed_commit"] == "8f3d262ac388"
    assert parsed["reviewed_version"] == "v0.0.0"
    assert "Source, dependencies" in parsed["notes"]
    assert "Verification request issue #12" in parsed["notes"]
