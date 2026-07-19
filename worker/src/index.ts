const DEFAULT_REGISTRY_KEY = "registry/plugin_cache_original.json";
const DOWNLOAD_ID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const SAFE_SEGMENT_PATTERN = /^[A-Za-z0-9._-]{1,255}$/;
const EVENT_RETENTION_SECONDS = 30 * 24 * 60 * 60;
const MAX_REGISTRY_BYTES = 2 * 1024 * 1024;

type JsonObject = Record<string, unknown>;

interface DownloadCountRow {
  plugin_id: string;
  download_count: number;
}

export interface PackagePath {
  filename: string;
  key: string;
  owner: string;
  pluginId: string;
  version: string;
}

export interface DownloadEvent {
  createdAt: number;
  eventId: string;
  pluginId: string;
  version: string;
}

function isRecord(value: unknown): value is JsonObject {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function stringValue(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

export function normalizeDownloadId(value: unknown): string {
  const candidate = String(value ?? "").trim();
  return DOWNLOAD_ID_PATTERN.test(candidate) ? candidate : "";
}

function decodeSafeSegment(value: string): string {
  let decoded: string;
  try {
    decoded = decodeURIComponent(value);
  } catch {
    return "";
  }
  if (!SAFE_SEGMENT_PATTERN.test(decoded) || decoded === "." || decoded === "..") {
    return "";
  }
  return decoded;
}

export function parsePackagePath(pathname: unknown): PackagePath | null {
  const parts = String(pathname ?? "").split("/");
  if (parts.length !== 6 || parts[0] !== "" || parts[1] !== "plugins") {
    return null;
  }

  const owner = decodeSafeSegment(parts[2]);
  const pluginId = decodeSafeSegment(parts[3]);
  const version = decodeSafeSegment(parts[4]);
  const filename = decodeSafeSegment(parts[5]);
  if (!owner || !pluginId || !version || !filename.toLowerCase().endsWith(".zip")) {
    return null;
  }

  return {
    filename,
    key: `plugins/${owner}/${pluginId}/${version}/${filename}`,
    owner,
    pluginId,
    version,
  };
}

function publicPackagePath(parsed: PackagePath): string {
  const segments = [parsed.owner, parsed.pluginId, parsed.version, parsed.filename].map(encodeURIComponent);
  return `/plugins/${segments.join("/")}`;
}

function registryPluginEntries(root: unknown): Array<[string, JsonObject]> {
  if (Array.isArray(root)) {
    return root.filter(isRecord).map((plugin) => ["", plugin]);
  }
  if (!isRecord(root)) {
    return [];
  }

  const plugins = root.plugins;
  if (Array.isArray(plugins)) {
    return plugins.filter(isRecord).map((plugin) => ["", plugin]);
  }
  if (isRecord(plugins)) {
    return Object.entries(plugins).filter((entry): entry is [string, JsonObject] => isRecord(entry[1]));
  }
  return Object.entries(root).filter((entry): entry is [string, JsonObject] => isRecord(entry[1]));
}

function normalizeGatewayOrigin(value: unknown, fallback: string): string {
  for (const candidate of [stringValue(value), fallback]) {
    try {
      const parsed = new URL(candidate);
      if (parsed.protocol === "https:" || parsed.protocol === "http:") {
        return parsed.origin;
      }
    } catch {
      // Try the fallback value.
    }
  }
  return fallback;
}

function packageGatewayUrl(plugin: JsonObject, gatewayOrigin: string): string {
  const packageInfo = isRecord(plugin.package) ? plugin.package : null;
  const r2Key = stringValue(packageInfo?.r2_key).replace(/^\/+/, "");
  const parsedR2Key = parsePackagePath(`/${r2Key}`);
  if (parsedR2Key) {
    return `${gatewayOrigin}${publicPackagePath(parsedR2Key)}`;
  }

  const currentUrl = stringValue(packageInfo?.url) || stringValue(plugin.download_url);
  try {
    const parsedUrl = new URL(currentUrl);
    const parsedPath = parsePackagePath(parsedUrl.pathname);
    return parsedPath ? `${gatewayOrigin}${publicPackagePath(parsedPath)}` : "";
  } catch {
    return "";
  }
}

export function overlayRegistryDownloads(
  rawRegistry: unknown,
  rows: Iterable<DownloadCountRow> | null | undefined,
  gatewayOrigin: string,
): unknown {
  const output = structuredClone(rawRegistry);
  const counts = new Map<string, number>();
  for (const row of rows ?? []) {
    const pluginId = stringValue(row?.plugin_id);
    const count = Number(row?.download_count ?? 0);
    if (pluginId && Number.isFinite(count) && count >= 0) {
      counts.set(pluginId, Math.trunc(count));
    }
  }

  for (const [registryKey, plugin] of registryPluginEntries(output)) {
    const name = stringValue(plugin.name);
    const id = stringValue(plugin.id);
    const canonicalId = stringValue(plugin.plugin_id);
    const pluginId = name || id || registryKey;
    plugin.download_count =
      counts.get(pluginId) ?? counts.get(registryKey) ?? counts.get(canonicalId) ?? 0;

    const gatewayUrl = packageGatewayUrl(plugin, gatewayOrigin.replace(/\/$/, ""));
    if (!gatewayUrl) {
      continue;
    }
    plugin.download_url = gatewayUrl;
    if (isRecord(plugin.package)) {
      plugin.package.url = gatewayUrl;
    }
  }
  return output;
}

async function downloadCountRows(env: Env): Promise<DownloadCountRow[]> {
  const result = await env.DOWNLOADS_DB.prepare(
    "SELECT plugin_id, download_count FROM plugin_download_stats",
  ).all<DownloadCountRow>();
  return result.results;
}

export async function recordDownload(env: Env, event: DownloadEvent): Promise<void> {
  await env.DOWNLOADS_DB.prepare(
    `INSERT OR IGNORE INTO plugin_download_events(event_id, plugin_id, version, created_at)
     VALUES (?1, ?2, ?3, ?4)`,
  )
    .bind(event.eventId, event.pluginId, event.version, event.createdAt)
    .run();
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function logError(message: string, error: unknown, details: JsonObject = {}): void {
  console.error(JSON.stringify({ ...details, error: errorMessage(error), message }));
}

const CORS_HEADERS = {
  "Access-Control-Allow-Headers": "Range, X-Shinsekai-Download-Id",
  "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS",
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Expose-Headers": "Accept-Ranges, Content-Length, Content-Range, ETag",
};

function jsonResponse(payload: unknown, status = 200, extraHeaders: HeadersInit = {}): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: {
      ...CORS_HEADERS,
      "Content-Type": "application/json; charset=utf-8",
      "X-Content-Type-Options": "nosniff",
      ...extraHeaders,
    },
  });
}

function methodNotAllowed(): Response {
  return new Response("Method Not Allowed", {
    status: 405,
    headers: { ...CORS_HEADERS, Allow: "GET, HEAD, OPTIONS" },
  });
}

async function serveRegistry(request: Request, env: Env): Promise<Response> {
  const registryKey = stringValue(env.REGISTRY_KEY || DEFAULT_REGISTRY_KEY).replace(/^\/+/, "");
  const object = await env.REGISTRY_BUCKET.get(registryKey);
  if (object === null) {
    return jsonResponse({ error: "registry not found", ok: false }, 404);
  }
  if (object.size > MAX_REGISTRY_BYTES) {
    return jsonResponse({ error: "registry is too large", ok: false }, 502);
  }

  let rawRegistry: unknown;
  try {
    rawRegistry = await object.json<unknown>();
  } catch (error) {
    logError("failed to parse registry", error, { registryKey });
    return jsonResponse({ error: "registry is invalid", ok: false }, 502);
  }

  let rows: DownloadCountRow[] = [];
  try {
    rows = await downloadCountRows(env);
  } catch (error) {
    logError("failed to load download counts", error);
  }

  const requestOrigin = new URL(request.url).origin;
  const gatewayOrigin = normalizeGatewayOrigin(env.PUBLIC_BASE_URL, requestOrigin);
  const payload = overlayRegistryDownloads(rawRegistry, rows, gatewayOrigin);
  const response = jsonResponse(payload, 200, {
    "Cache-Control": "public, max-age=30, stale-while-revalidate=60",
  });
  return request.method === "HEAD"
    ? new Response(null, { status: response.status, headers: response.headers })
    : response;
}

function packageHeaders(object: R2Object, filename: string, contentLength: number): Headers {
  const headers = new Headers(CORS_HEADERS);
  object.writeHttpMetadata(headers);
  headers.set("Accept-Ranges", "bytes");
  headers.set("Cache-Control", "public, max-age=31536000, immutable");
  headers.set("Content-Disposition", `attachment; filename="${filename.replace(/[^A-Za-z0-9._-]/g, "_")}"`);
  headers.set("Content-Length", String(contentLength));
  headers.set("Content-Type", "application/zip");
  headers.set("ETag", object.httpEtag);
  headers.set("X-Content-Type-Options", "nosniff");
  return headers;
}

export function downloadEventId(request: Request): string | null {
  return normalizeDownloadId(request.headers.get("X-Shinsekai-Download-Id")) || null;
}

async function servePackage(
  request: Request,
  env: Env,
  ctx: ExecutionContext,
  parsed: PackagePath,
): Promise<Response> {
  if (request.method === "HEAD") {
    const object = await env.REGISTRY_BUCKET.head(parsed.key);
    if (object === null) {
      return new Response("Not Found", { status: 404, headers: CORS_HEADERS });
    }
    const headers = packageHeaders(object, parsed.filename, object.size);
    // Workers validates Content-Length against the actual response body. A HEAD
    // response has no body, so advertising the object size here causes an edge 500.
    headers.delete("Content-Length");
    return new Response(null, {
      status: 200,
      headers,
    });
  }

  // Cloudflare handles HTTP Range slicing at the edge and strips Range before
  // invoking the Worker. Return the full immutable object as a normal 200.
  const object = await env.REGISTRY_BUCKET.get(parsed.key);
  if (object === null) {
    return new Response("Not Found", { status: 404, headers: CORS_HEADERS });
  }

  const eventId = downloadEventId(request);
  if (eventId) {
    const event = {
      createdAt: Math.floor(Date.now() / 1000),
      eventId,
      pluginId: parsed.pluginId,
      version: parsed.version,
    } satisfies DownloadEvent;
    ctx.waitUntil(
      recordDownload(env, event).catch((error: unknown) => {
        logError("failed to record plugin download", error, {
          eventId,
          pluginId: parsed.pluginId,
          version: parsed.version,
        });
      }),
    );
  }

  const headers = packageHeaders(object, parsed.filename, object.size);
  return new Response(object.body, { status: 200, headers });
}

function preflightResponse(): Response {
  return new Response(null, { status: 204, headers: CORS_HEADERS });
}

export async function handleRequest(
  request: Request,
  env: Env,
  ctx: ExecutionContext,
): Promise<Response> {
  const url = new URL(request.url);
  const packagePath = parsePackagePath(url.pathname);
  const isRegistry = url.pathname === "/registry/plugin_cache_original.json";
  const isHealth = url.pathname === "/health";

  if (request.method === "OPTIONS" && (isRegistry || packagePath || isHealth)) {
    return preflightResponse();
  }
  if (isHealth) {
    if (request.method !== "GET" && request.method !== "HEAD") {
      return methodNotAllowed();
    }
    const response = jsonResponse({
      ok: true,
      registry: stringValue(env.REGISTRY_KEY || DEFAULT_REGISTRY_KEY),
      service: "shinsekai-plugin-download-gateway",
    });
    return request.method === "HEAD"
      ? new Response(null, { status: response.status, headers: response.headers })
      : response;
  }
  if (isRegistry) {
    if (request.method !== "GET" && request.method !== "HEAD") {
      return methodNotAllowed();
    }
    return serveRegistry(request, env);
  }
  if (packagePath) {
    if (request.method !== "GET" && request.method !== "HEAD") {
      return methodNotAllowed();
    }
    return servePackage(request, env, ctx, packagePath);
  }

  return jsonResponse(
    {
      endpoints: [
        "/health",
        "/registry/plugin_cache_original.json",
        "/plugins/:owner/:plugin/:version/:file.zip",
      ],
      ok: false,
      service: "shinsekai-plugin-download-gateway",
    },
    404,
  );
}

async function cleanupDownloadEvents(env: Env): Promise<void> {
  const cutoff = Math.floor(Date.now() / 1000) - EVENT_RETENTION_SECONDS;
  await env.DOWNLOADS_DB.prepare("DELETE FROM plugin_download_events WHERE created_at < ?1")
    .bind(cutoff)
    .run();
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    try {
      return await handleRequest(request, env, ctx);
    } catch (error) {
      logError("unhandled request error", error, { path: new URL(request.url).pathname });
      return jsonResponse({ error: "internal server error", ok: false }, 500);
    }
  },
  async scheduled(_controller, env, ctx): Promise<void> {
    ctx.waitUntil(
      cleanupDownloadEvents(env).catch((error: unknown) => {
        logError("failed to clean old download events", error);
      }),
    );
  },
} satisfies ExportedHandler<Env>;
