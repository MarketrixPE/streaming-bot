/**
 * PoC SDK TypeScript para spinoff B2B SaaS — strict mode, ESM nativo.
 *
 * Objetivo del spike:
 *   Demostrar la experiencia de integracion en TypeScript para un cliente:
 *   3 metodos (sessions.open, behaviors.playSession, profiles.list) con
 *   tipos estrictos, retries con backoff exponencial, idempotency keys
 *   automaticos via crypto.randomUUID, y validacion runtime ligera. Compatible
 *   con el api_skeleton.py del mismo spike.
 *
 * Como ejecutarlo (Node 20+, ESM):
 *   # Setup proyecto local mininmo:
 *   #   mkdir spinoff-sdk-poc && cd spinoff-sdk-poc
 *   #   npm init -y
 *   #   npm pkg set type=module
 *   #   npm install --save-dev typescript@5.6 tsx@4 @types/node@22
 *   #   cp ../streaming-bot/spikes/year-3/sdk_typescript_poc.ts ./index.ts
 *   #   npx tsx index.ts
 *
 *   # Antes ejecuta el api_skeleton (otra terminal):
 *   #   uvicorn spikes.year_3.api_skeleton:app --reload --port 8090
 *
 * Dependencias explicitas (al integrarlo en un proyecto):
 *   - typescript >= 5.4
 *   - Node 20+ con WHATWG fetch nativo
 *   - tsx (solo para dev/exec); en build usa tsc
 *
 * Sin dependencias runtime externas — usa fetch global.
 */

// ---------- Types ----------

export type DeviceClass =
  | "mobile_android_premium"
  | "mobile_ios"
  | "desktop_macos"
  | "desktop_win";

export type BrowserEngine = "auto" | "patchright" | "camoufox";

export type ProxyMode = "managed" | "byo" | "none";

export type TargetType = "track" | "playlist" | "artist" | "album";

export type TargetDsp =
  | "spotify"
  | "deezer"
  | "soundcloud"
  | "apple_music"
  | "amazon_music";

export interface SessionOpenRequest {
  geo: string;
  deviceClass: DeviceClass;
  browserEngine?: BrowserEngine;
  ttlSeconds?: number;
  proxyMode?: ProxyMode;
  labels?: Record<string, string>;
}

export interface FingerprintSummary {
  ua_family: string;
  locale: string;
  timezone: string;
  ja4_hash: string;
}

export interface BillingMeta {
  mode: "session_basic" | "session_rich";
  credits_held_cents: number;
}

export interface SessionOpenResponse {
  session_id: string;
  ws_endpoint: string;
  expires_at: string;
  fingerprint_summary: FingerprintSummary;
  billing: BillingMeta;
}

export interface TargetSpec {
  type: TargetType;
  externalId: string;
  minPlays?: number;
  maxPlays?: number;
}

export interface BehaviorPlayRequest {
  targetDsp: TargetDsp;
  targets: TargetSpec[];
  behaviorProfileId: string;
  geo: string;
  deviceClass: DeviceClass;
  constraints?: Record<string, unknown>;
  callbackWebhookUrl?: string;
}

export interface BehaviorPlayResponse {
  session_id: string;
  behavior_run_id: string;
  status: "running" | "queued";
  estimated_duration_seconds: number;
  billing: BillingMeta;
}

export interface ProfileEntry {
  id: string;
  description: string;
  geo: string[];
  device_classes: DeviceClass[];
  params: Record<string, unknown>;
  version: string;
  trained_on_samples: number;
  compatibility: string[];
}

export interface ClientOptions {
  apiKey: string;
  baseUrl?: string;
  timeoutMs?: number;
  maxRetries?: number;
}

// ---------- Errors ----------

export class SpinoffClientError extends Error {
  constructor(
    public statusCode: number,
    public errorCode: string,
    message: string,
    public requestId: string,
  ) {
    super(`[${statusCode}/${errorCode}] ${message} (req=${requestId})`);
    this.name = "SpinoffClientError";
  }
}

export class SpinoffServerError extends Error {
  constructor(public statusCode: number, message: string) {
    super(`[${statusCode}] ${message}`);
    this.name = "SpinoffServerError";
  }
}

// ---------- Internal helpers ----------

function snakeCase(input: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(input)) {
    const sk = k.replace(/[A-Z]/g, (m) => "_" + m.toLowerCase());
    if (Array.isArray(v)) {
      out[sk] = v.map((it) =>
        typeof it === "object" && it !== null
          ? snakeCase(it as Record<string, unknown>)
          : it,
      );
    } else if (v !== null && typeof v === "object" && !(v instanceof Date)) {
      out[sk] = snakeCase(v as Record<string, unknown>);
    } else {
      out[sk] = v;
    }
  }
  return out;
}

async function sleep(ms: number): Promise<void> {
  return new Promise((res) => setTimeout(res, ms));
}

// ---------- Sub-clients ----------

class Sessions {
  constructor(private readonly client: Client) {}

  async open(
    req: SessionOpenRequest,
    idempotencyKey?: string,
  ): Promise<SessionOpenResponse> {
    if (req.ttlSeconds !== undefined && (req.ttlSeconds < 60 || req.ttlSeconds > 3600)) {
      throw new Error("ttlSeconds must be in [60, 3600]");
    }
    const body = snakeCase(req as unknown as Record<string, unknown>);
    return this.client.requestWithRetry<SessionOpenResponse>(
      "POST",
      "/v1/sessions",
      body,
      idempotencyKey ?? crypto.randomUUID(),
    );
  }
}

class Behaviors {
  constructor(private readonly client: Client) {}

  async playSession(
    req: BehaviorPlayRequest,
    idempotencyKey?: string,
  ): Promise<BehaviorPlayResponse> {
    if (!req.targets || req.targets.length === 0) {
      throw new Error("at least one target required");
    }
    const body = snakeCase(req as unknown as Record<string, unknown>);
    return this.client.requestWithRetry<BehaviorPlayResponse>(
      "POST",
      "/v1/behaviors/play_session",
      body,
      idempotencyKey ?? crypto.randomUUID(),
    );
  }
}

class Profiles {
  constructor(private readonly client: Client) {}

  async list(): Promise<ProfileEntry[]> {
    const resp = await this.client.requestWithRetry<{ profiles: ProfileEntry[]; total: number }>(
      "GET",
      "/v1/profiles",
    );
    return resp.profiles;
  }
}

// ---------- Client ----------

export class Client {
  private readonly apiKey: string;
  private readonly baseUrl: string;
  private readonly timeoutMs: number;
  private readonly maxRetries: number;

  public readonly sessions: Sessions;
  public readonly behaviors: Behaviors;
  public readonly profiles: Profiles;

  constructor(opts: ClientOptions) {
    if (!opts.apiKey) throw new Error("apiKey required");
    this.apiKey = opts.apiKey;
    this.baseUrl = opts.baseUrl?.replace(/\/$/, "") ?? "http://127.0.0.1:8090";
    this.timeoutMs = opts.timeoutMs ?? 30_000;
    this.maxRetries = opts.maxRetries ?? 3;

    this.sessions = new Sessions(this);
    this.behaviors = new Behaviors(this);
    this.profiles = new Profiles(this);
  }

  async requestWithRetry<T>(
    method: "GET" | "POST",
    path: string,
    body?: Record<string, unknown>,
    idempotencyKey?: string,
  ): Promise<T> {
    let lastErr: unknown = null;
    for (let attempt = 0; attempt <= this.maxRetries; attempt++) {
      try {
        return await this.requestOnce<T>(method, path, body, idempotencyKey);
      } catch (e) {
        lastErr = e;
        if (e instanceof SpinoffClientError) throw e;
        if (e instanceof SpinoffServerError || e instanceof TypeError) {
          if (attempt === this.maxRetries) break;
          const wait = Math.min(8000, 500 * 2 ** attempt) + Math.random() * 250;
          await sleep(wait);
          continue;
        }
        throw e;
      }
    }
    throw lastErr;
  }

  private async requestOnce<T>(
    method: "GET" | "POST",
    path: string,
    body?: Record<string, unknown>,
    idempotencyKey?: string,
  ): Promise<T> {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), this.timeoutMs);
    try {
      const headers: Record<string, string> = {
        "Authorization": `Bearer ${this.apiKey}`,
        "User-Agent": "spinoff-saas-sdk-ts/0.1.0",
      };
      if (body !== undefined) headers["Content-Type"] = "application/json";
      if (idempotencyKey) headers["Idempotency-Key"] = idempotencyKey;

      const resp = await fetch(`${this.baseUrl}${path}`, {
        method,
        headers,
        body: body !== undefined ? JSON.stringify(body) : undefined,
        signal: ctrl.signal,
      });

      if (resp.status >= 500 || resp.status === 429) {
        const txt = await resp.text();
        throw new SpinoffServerError(resp.status, txt.slice(0, 200));
      }
      if (resp.status >= 400) {
        let payload: { error_code?: string; message?: string; request_id?: string } = {};
        try {
          payload = (await resp.json()) as typeof payload;
        } catch {
          payload = { error_code: String(resp.status), message: await resp.text() };
        }
        throw new SpinoffClientError(
          resp.status,
          String(payload.error_code ?? resp.status),
          String(payload.message ?? "client error"),
          String(payload.request_id ?? "?"),
        );
      }
      return (await resp.json()) as T;
    } finally {
      clearTimeout(timer);
    }
  }
}

// ---------- Demo ----------

async function demo(): Promise<void> {
  const apiKey = process.env.SPINOFF_API_KEY ?? "sk_test_demo_001";
  const baseUrl = process.env.SPINOFF_BASE_URL ?? "http://127.0.0.1:8090";

  const client = new Client({ apiKey, baseUrl });

  const profiles = await client.profiles.list();
  console.log(`[sdk-ts] profiles available: ${profiles.length}`);
  for (const p of profiles.slice(0, 3)) {
    console.log(`  - ${p.id} v${p.version}  geo=${JSON.stringify(p.geo)}`);
  }

  const ses = await client.sessions.open({
    geo: "BR-SP",
    deviceClass: "mobile_android_premium",
    ttlSeconds: 900,
  });
  console.log(`[sdk-ts] session opened: ${ses.session_id}`);
  console.log(`  ws_endpoint = ${ses.ws_endpoint}`);
  console.log(`  expires_at  = ${ses.expires_at}`);

  const play = await client.behaviors.playSession({
    targetDsp: "spotify",
    targets: [
      {
        type: "playlist",
        externalId: "37i9dQZF1DXcBWIGoYBM5M",
        minPlays: 3,
        maxPlays: 5,
      },
    ],
    behaviorProfileId: "superfan_premium_br_v3",
    geo: "BR-SP",
    deviceClass: "mobile_android_premium",
    constraints: { min_save_rate: 0.06, max_skip_rate: 0.25 },
  });
  console.log(`[sdk-ts] behavior run started: ${play.behavior_run_id}`);
  console.log(`  estimated_duration_s = ${play.estimated_duration_seconds}`);
}

const isMain =
  typeof process !== "undefined" &&
  Array.isArray(process.argv) &&
  process.argv[1] !== undefined &&
  /sdk_typescript_poc\.(ts|js|mjs)$/.test(process.argv[1]);

if (isMain) {
  demo().catch((err) => {
    if (err instanceof SpinoffClientError) {
      console.error(`[sdk-ts] client error: ${err.message}`);
    } else if (err instanceof SpinoffServerError) {
      console.error(`[sdk-ts] server error after retries: ${err.message}`);
    } else {
      console.error("[sdk-ts] unexpected error:", err);
    }
    process.exitCode = 1;
  });
}
