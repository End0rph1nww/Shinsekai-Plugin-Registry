import { env } from "cloudflare:workers";
import {
  createExecutionContext,
  waitOnExecutionContext,
} from "cloudflare:test";
import { beforeEach, describe, expect, it } from "vitest";

import {
  downloadEventId,
  handleRequest,
  normalizeDownloadId,
  overlayRegistryDownloads,
  parsePackagePath,
  recordDownload,
} from "../src/index";

const PACKAGE_KEY = "plugins/example/demo/1.0.0/demo-1.0.0.zip";
const PACKAGE_URL = `https://downloads.shinsekai.studio/${PACKAGE_KEY}`;

async function dispatch(request: Request): Promise<Response> {
  const ctx = createExecutionContext();
  const response = await handleRequest(request, env, ctx);
  await waitOnExecutionContext(ctx);
  return response;
}

async function downloadCount(pluginId: string): Promise<number | null> {
  const row = await env.DOWNLOADS_DB.prepare(
    "SELECT download_count FROM plugin_download_stats WHERE plugin_id = ?1",
  )
    .bind(pluginId)
    .first<{ download_count: number }>();
  return row?.download_count ?? null;
}

beforeEach(async () => {
  await env.DOWNLOADS_DB.batch([
    env.DOWNLOADS_DB.prepare("DELETE FROM plugin_download_events"),
    env.DOWNLOADS_DB.prepare("DELETE FROM plugin_download_stats"),
  ]);
  await env.REGISTRY_BUCKET.put(PACKAGE_KEY, "zip payload", {
    httpMetadata: { contentType: "application/zip" },
  });
});

describe("request parsing", () => {
  it("accepts safe package paths and rejects traversal", () => {
    expect(parsePackagePath(`/${PACKAGE_KEY}`)).toEqual({
      filename: "demo-1.0.0.zip",
      key: PACKAGE_KEY,
      owner: "example",
      pluginId: "demo",
      version: "1.0.0",
    });
    expect(parsePackagePath("/plugins/example/%2E%2E/1.0.0/demo.zip")).toBeNull();
    expect(parsePackagePath("/plugins/example/demo/1.0.0/demo.exe")).toBeNull();
  });

  it("accepts UUIDv4 install IDs and rejects anonymous or malformed IDs", () => {
    const eventId = "918aa1e2-2bbd-4aa8-b861-cfd76990312a";
    expect(normalizeDownloadId(eventId)).toBe(eventId);
    expect(normalizeDownloadId("install_request_123456")).toBe("");
    expect(normalizeDownloadId("short")).toBe("");
    expect(downloadEventId(new Request(PACKAGE_URL))).toBeNull();
    expect(
      downloadEventId(
        new Request(PACKAGE_URL, { headers: { "X-Shinsekai-Download-Id": eventId } }),
      ),
    ).toBe(eventId);
  });
});

describe("registry overlay", () => {
  it("adds counts and rewrites package URLs without mutating the source", () => {
    const source = {
      demo: {
        download_url: "https://r2.example/plugins/example/demo/1.0.0/demo-1.0.0.zip",
        name: "demo",
        package: {
          r2_key: PACKAGE_KEY,
          url: "https://r2.example/plugins/example/demo/1.0.0/demo-1.0.0.zip",
        },
      },
    };

    expect(
      overlayRegistryDownloads(
        source,
        [{ download_count: 42, plugin_id: "demo" }],
        "https://downloads.shinsekai.studio",
      ),
    ).toEqual({
      demo: {
        download_count: 42,
        download_url: PACKAGE_URL,
        name: "demo",
        package: {
          r2_key: PACKAGE_KEY,
          url: PACKAGE_URL,
        },
      },
    });
    expect(source.demo).not.toHaveProperty("download_count");
  });
});

describe("download gateway", () => {
  it("deduplicates retries that reuse one install request ID", async () => {
    const eventId = "918aa1e2-2bbd-4aa8-b861-cfd76990312a";
    for (let attempt = 0; attempt < 2; attempt += 1) {
      const response = await dispatch(
        new Request(PACKAGE_URL, {
          headers: { "X-Shinsekai-Download-Id": eventId },
        }),
      );
      expect(response.status).toBe(200);
      expect(new TextDecoder().decode(await response.arrayBuffer())).toBe("zip payload");
    }
    expect(await downloadCount("demo")).toBe(1);
  });

  it("does not count HEAD or package requests without an install ID", async () => {
    const headResponse = await dispatch(new Request(PACKAGE_URL, { method: "HEAD" }));
    expect(headResponse.status).toBe(200);
    expect(headResponse.headers.get("Content-Length")).toBeNull();
    const anonymousResponse = await dispatch(
      new Request(PACKAGE_URL, { headers: { Range: "bytes=0-2" } }),
    );
    expect(anonymousResponse.status).toBe(200);
    expect(new TextDecoder().decode(await anonymousResponse.arrayBuffer())).toBe("zip payload");
    expect(await downloadCount("demo")).toBeNull();
  });

  it("serves a live registry with D1 counts", async () => {
    await recordDownload(env, {
      createdAt: 1_700_000_000,
      eventId: "4abae3ea-29cc-4933-bbb3-9ddcc7352507",
      pluginId: "demo",
      version: "1.0.0",
    });
    await env.REGISTRY_BUCKET.put(
      "registry/plugin_cache_original.json",
      JSON.stringify({
        demo: {
          download_url: "https://r2.example/old.zip",
          name: "demo",
          package: { r2_key: PACKAGE_KEY, url: "https://r2.example/old.zip" },
        },
      }),
      { httpMetadata: { contentType: "application/json" } },
    );

    const response = await dispatch(
      new Request("https://downloads.shinsekai.studio/registry/plugin_cache_original.json"),
    );
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({
      demo: {
        download_count: 1,
        download_url: PACKAGE_URL,
        name: "demo",
        package: { r2_key: PACKAGE_KEY, url: PACKAGE_URL },
      },
    });
  });
});
