# 02 — Product spec

## Convenciones generales

- Base URL: `https://api.[brand-spinoff].io/v1` (sustituible). Cloudflare Tunnel adelante; backend Hetzner.
- Auth: `Authorization: Bearer <api_key>` (API key prepago, generada en onboarding).
- JSON request/response, snake_case.
- Errores: estructura `{ "error_code": str, "message": str, "request_id": str }`.
- Idempotency: header `Idempotency-Key: <uuid>` aceptado en endpoints POST.
- Rate limit: 60 req/s burst / 30 req/s sostenido por tenant. 429 con `Retry-After`.
- Webhooks: HMAC-SHA256 con secreto compartido en header `X-Signature`.

## Endpoint 1 — `POST /v1/sessions`

Abrir una sesion de browser stealth managed.

### Request

```json
{
  "geo": "BR-SP",
  "device_class": "mobile_android_premium",
  "browser_engine": "auto",
  "ttl_seconds": 1800,
  "proxy_mode": "managed",
  "labels": {
    "tenant_internal_id": "campaign_42_track_xy"
  }
}
```

| Campo | Tipo | Descripcion |
|---|---|---|
| `geo` | str | ISO2 + region opcional (`BR`, `BR-SP`, `US-CA`) |
| `device_class` | enum | `mobile_android_premium`, `mobile_ios`, `desktop_macos`, `desktop_win` |
| `browser_engine` | enum | `auto`, `patchright`, `camoufox` |
| `ttl_seconds` | int | 60..3600 |
| `proxy_mode` | enum | `managed` (nuestros), `byo` (cliente trae), `none` (datacenter) |
| `labels` | object | meta opcional para auditoria cliente |

### Response 201

```json
{
  "session_id": "ses_01HZX...",
  "ws_endpoint": "wss://edge-fi-1.api.[brand-spinoff].io/v1/sessions/ses_01HZX.../ws",
  "expires_at": "2027-04-12T18:11:00Z",
  "fingerprint_summary": {
    "ua_family": "Chrome 137 / Android 16",
    "locale": "pt-BR",
    "timezone": "America/Sao_Paulo",
    "ja4_hash": "ja4_xxx"
  },
  "billing": {
    "mode": "session_basic",
    "credits_held_cents": 5
  }
}
```

### Errores especificos

- `INSUFFICIENT_CREDITS` 402.
- `GEO_UNAVAILABLE` 422.
- `RATE_LIMIT_EXCEEDED` 429.
- `BROWSER_POOL_SATURATED` 503 (con Retry-After).

### Pricing
$0.05 por sesion exitosamente cerrada (con `closed_at` registrado o `ttl` agotado en estado healthy). Sesiones que crashean por nuestra culpa NO se cobran.

---

## Endpoint 2 — `POST /v1/behaviors/play_session`

Ejecutar una sesion completa con behavioral playback. Este es el endpoint "rich".

### Request

```json
{
  "target_dsp": "spotify",
  "targets": [
    {
      "type": "playlist",
      "external_id": "37i9dQZF1DXcBWIGoYBM5M",
      "min_plays": 3,
      "max_plays": 6
    }
  ],
  "behavior_profile_id": "superfan_premium_br_v3",
  "geo": "BR-SP",
  "device_class": "mobile_android_premium",
  "constraints": {
    "min_save_rate": 0.06,
    "max_skip_rate": 0.25,
    "min_session_duration_s": 240,
    "max_session_duration_s": 900
  },
  "callback_webhook_url": "https://customer.example/hooks/session_end"
}
```

### Response 202

```json
{
  "session_id": "ses_01HZY...",
  "behavior_run_id": "br_01HZY...",
  "status": "running",
  "estimated_duration_seconds": 540,
  "billing": {
    "mode": "session_rich",
    "credits_held_cents": 20
  }
}
```

### Webhook OnSessionEnd

```json
{
  "event": "behavior_run.completed",
  "behavior_run_id": "br_01HZY...",
  "session_id": "ses_01HZY...",
  "status": "completed",
  "metrics": {
    "duration_seconds": 612,
    "plays_executed": 4,
    "saves": 1,
    "skips": 1,
    "queue_adds": 0,
    "playlist_explores": 1,
    "anomalies_detected": [],
    "captcha_count": 0,
    "completion_rate_session": 0.92
  },
  "billing": {
    "credits_charged_cents": 20
  },
  "fingerprint_summary": {
    "ja4_hash": "ja4_xxx",
    "locale": "pt-BR"
  },
  "ts": "2027-04-12T18:25:32Z"
}
```

`anomalies_detected` lista codigos como `"slow_response_serverside"`, `"unexpected_redirect"`, `"captcha_triggered"`, `"ip_warning_detected"`. Util para que el cliente correlacione bans con eventos.

---

## Endpoint 3 — `GET /v1/profiles`

Listar profiles disponibles.

### Response 200

```json
{
  "profiles": [
    {
      "id": "superfan_premium_br_v3",
      "description": "Super-fan premium BR — sesiones largas 5-15 min, repeat behavior, save rate 5-12%, queue rate 3-5%, premium listener.",
      "geo": ["BR-SP", "BR-RJ", "BR-MG"],
      "device_classes": ["mobile_android_premium", "mobile_ios"],
      "params": {
        "min_save_rate": 0.05,
        "max_skip_rate": 0.30,
        "intensity_levels": ["low", "medium", "high"]
      },
      "version": "3.1.0",
      "trained_on_samples": 184523,
      "compatibility": ["spotify", "deezer"]
    },
    {
      "id": "casual_premium_us_v2",
      "description": "Casual premium US — sesiones cortas 2-6 min, low save rate, normal skip distribucion.",
      "geo": ["US"],
      "device_classes": ["desktop_macos", "desktop_win", "mobile_ios"],
      "version": "2.4.1",
      "trained_on_samples": 412004,
      "compatibility": ["spotify", "apple_music", "amazon_music"]
    }
  ],
  "total": 38
}
```

---

## SDK Python

Disponible en `pypi.org/project/[brand-spinoff]-sdk/`.

```python
# pip install [brand-spinoff]-sdk

from [brand_spinoff_sdk] import Client, BehaviorRequest, Target

client = Client(api_key="sk_live_xxx")

run = client.behaviors.play_session(
    BehaviorRequest(
        target_dsp="spotify",
        targets=[Target(type="playlist", external_id="37i9...", min_plays=3, max_plays=6)],
        behavior_profile_id="superfan_premium_br_v3",
        geo="BR-SP",
        device_class="mobile_android_premium",
    )
)
print(run.session_id, run.status)

for event in client.behaviors.subscribe(run.behavior_run_id):
    print(event)
```

Caracteristicas SDK Python:
- Async-first (`asyncio`), wrapper sync con `client.sync.*`.
- Pydantic v2 models.
- Retries con backoff exponencial sobre 5xx y 429.
- Validacion local de payloads antes de enviar.
- Pagination automatica donde aplique.

## SDK TypeScript

Disponible en `npmjs.com/package/@[brand-spinoff]/sdk`.

```typescript
// npm install @[brand-spinoff]/sdk

import { Client } from "@[brand-spinoff]/sdk";

const client = new Client({ apiKey: process.env.SPINOFF_API_KEY! });

const run = await client.behaviors.playSession({
  targetDsp: "spotify",
  targets: [{ type: "playlist", externalId: "37i9...", minPlays: 3, maxPlays: 6 }],
  behaviorProfileId: "superfan_premium_br_v3",
  geo: "BR-SP",
  deviceClass: "mobile_android_premium",
});

for await (const evt of client.behaviors.stream(run.behaviorRunId)) {
  console.log(evt);
}
```

Caracteristicas SDK TypeScript:
- Strict TypeScript (target ES2022, `"strict": true`).
- Tipos generados automaticamente desde OpenAPI spec.
- Funciona en Node 20+ y en edge runtimes (Cloudflare Workers).
- ESM nativo.

## Pricing model — resumen

| Item | Precio |
|---|---|
| Sesion basica (`/v1/sessions` exitosa) | $0.05 |
| Sesion rich (`/v1/behaviors/play_session`) | $0.20 |
| Sesion fallida culpa nuestra | $0 |
| Sesion fallida con `proxy_mode=byo` y proxy del cliente caido | $0.02 (housekeeping) |
| Profile catalog (`/v1/profiles`) | gratuito |
| Webhook reintentos | gratis (3 reintentos exponential, despues delivery dead-letter) |
| Subscription tier opcional | $99/mes para descuento 10% sobre todas las sesiones |

## Integraciones / webhooks

| Evento | Trigger |
|---|---|
| `session.opened` | sesion `/v1/sessions` lista para usar (WS connectable) |
| `session.closed` | sesion cerrada (manual o TTL) |
| `behavior_run.completed` | rich session terminada (success o partial) |
| `behavior_run.failed` | rich session fallida con razon |
| `tenant.credits_low` | cuando credits < umbral configurable |
| `tenant.credits_exhausted` | cuando credits = 0 |
| `tenant.api_key_rotated` | cuando admin rota api key |

## Observabilidad expuesta al cliente

- Endpoint `GET /v1/sessions/{session_id}/metrics` con JSON de metricas finales.
- Dashboard self-hosted (Grafana publico-tenant via tokens) para tenant que paga subscription tier.
- Logs por sesion accessible 7 dias gratis, 30 dias subscription tier, despues purga.

## OpenAPI spec

`/v1/openapi.json` siempre disponible. Generador SDK CI/CD recompila clients en cada release de spec.

## Versionado

- API: prefix `/v1`. Cambios breaking solo en `/v2` futuro.
- Behavior profiles: semver (`major.minor.patch`). Cliente puede pinear a `superfan_premium_br_v3@3.1.0`. Default es ultima `3.x`.
- SDK: semver alineado con OpenAPI.
