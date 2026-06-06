# Plugin Distribution CI

This stage packages approved plugins from `plugins.json`, uploads immutable zip files to Cloudflare R2, and writes generated install metadata.

## Required Secrets

```text
R2_ACCOUNT_ID
R2_ACCESS_KEY_ID
R2_SECRET_ACCESS_KEY
R2_BUCKET
R2_PUBLIC_BASE_URL
```

Optional: `REGISTRY_BOT_TOKEN` can replace the default `github.token` on `main` if maintainers need bot-authored pushes. It should have the minimum repository permissions required to push generated metadata back to `main`.

## R2 Key Format

```text
plugins/{owner}/{plugin_name}/{version_without_v}/{plugin_name}-{version_without_v}-{commit12}.zip
```

Example:

```text
plugins/End0rph1nww/cloud_tts/1.0.0/cloud_tts-1.0.0-abcdef123456.zip
```

## Dry Run

Run the workflow manually with:

```text
dry_run=true
plugin_names=cloud_tts
```

Dry runs package and validate selected plugins, but skip R2 upload and skip generated-file commits.

Set `force=true` only when maintainers need to rebuild an already packaged plugin with the same registry entry. Non-dry publishes are blocked unless the workflow runs on `main`.

## Local Validation

```powershell
python -m pytest tests -q
python scripts\registry\validate_plugins.py plugins.json
python scripts\registry\update_generated_registry.py --dry-run --plugin-name cloud_tts
```

The generated `plugin_cache_original.json` is written as an object keyed by plugin name, matching the AstrBot-style generated registry shape while `plugins.json` can remain the lightweight submission list.
