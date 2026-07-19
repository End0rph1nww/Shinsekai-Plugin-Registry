CREATE TABLE IF NOT EXISTS plugin_download_stats (
  plugin_id TEXT PRIMARY KEY,
  download_count INTEGER NOT NULL DEFAULT 0 CHECK (download_count >= 0),
  updated_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS plugin_download_events (
  event_id TEXT PRIMARY KEY,
  plugin_id TEXT NOT NULL,
  version TEXT NOT NULL,
  created_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_plugin_download_events_created_at
  ON plugin_download_events(created_at);

CREATE TRIGGER IF NOT EXISTS increment_plugin_download_count
AFTER INSERT ON plugin_download_events
BEGIN
  INSERT INTO plugin_download_stats(plugin_id, download_count, updated_at)
  VALUES (NEW.plugin_id, 1, NEW.created_at)
  ON CONFLICT(plugin_id) DO UPDATE SET
    download_count = plugin_download_stats.download_count + 1,
    updated_at = excluded.updated_at;
END;
