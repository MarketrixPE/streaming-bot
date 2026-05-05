# 04 — Arquitectura del spinoff

## Vista de bloques

```
+---------------------------------------------------------------+
|                  Edge (Cloudflare Tunnel)                     |
|              api.[brand-spinoff].io  TLS terminator            |
+--------------------------+------------------------------------+
                           |
              +------------v-------------+
              |  API Gateway (FastAPI)   |
              |  - JWT api key auth      |
              |  - Rate limit (Redis)    |
              |  - Idempotency keys      |
              |  - OpenAPI generator     |
              +------------+-------------+
                           |
       +-------------------+-------------------+
       |                   |                   |
+------v------+   +--------v---------+   +-----v-------+
| Sessions    |   | Behaviors        |   | Billing /   |
| service     |   | service          |   | tenants svc |
+------+------+   +--------+---------+   +-----+-------+
       |                   |                   |
+------v------+   +--------v---------+   +-----v-------+
| Browser pool|   | Behavior orches  |   | Postgres    |
| Patchright/ |   | (Temporal wf)    |   | RLS multi-  |
| Camoufox    |   |                  |   | tenant      |
+------+------+   +--------+---------+   +-------------+
       |                   |
       +---------+---------+
                 |
       +---------v---------+
       | Granja 4G / 5G    |
       | Multi-region      |
       | (LT/BG/VN)        |
       +-------------------+

       +-------------------+
       | ClickHouse events |
       | tenant_id partit. |
       +-------------------+

       +-------------------+
       | MinIO / S3        |
       | session artifacts |
       | encrypted at rest |
       +-------------------+
```

## Multi-tenancy — modelo y aislamiento

### Tenant id

Todas las tablas core llevan `tenant_id UUID` indexado. Nivel logico:

```sql
ALTER TABLE sessions       ADD COLUMN tenant_id UUID NOT NULL;
ALTER TABLE behavior_runs  ADD COLUMN tenant_id UUID NOT NULL;
ALTER TABLE api_keys       ADD COLUMN tenant_id UUID NOT NULL;
ALTER TABLE credits_ledger ADD COLUMN tenant_id UUID NOT NULL;
ALTER TABLE webhooks_log   ADD COLUMN tenant_id UUID NOT NULL;
```

### RLS Postgres

Aprovechamos Row-Level Security:

```sql
ALTER TABLE sessions ENABLE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation_sessions
  ON sessions
  USING (tenant_id = current_setting('app.current_tenant')::uuid);
```

Cada conexion del API gateway hace `SET LOCAL app.current_tenant = '<tenant>'` despues de validar la api key. Cualquier query sin set-tenant retorna 0 rows. Verificado por tests integration en CI.

### Aislamiento de cuentas / proxies

Recurso fisico que NO se comparte cross-tenant:

- **Cuentas DSP del cliente**: el SaaS no almacena cuentas DSP. El cliente provee credenciales via WSS encriptado por sesion. Las creds nunca persisten en disco SaaS.
- **Proxies**:
  - `proxy_mode=managed`: pool nuestro segregado en buckets `[tenant_id, geo, device_class]`. Un IP usado para tenant A NO se reasigna a tenant B en ventana 24h.
  - `proxy_mode=byo`: el cliente provee proxy en cada request. Nada que aislar.
- **Modems mobile**: pool managed con etiqueta `affinity_tenant_id` opcional. Tier Volume bloquea slot dedicado. Tier Standard share rotacional con politica de no-back-to-back en mismo IP.

### Behavioral profiles — compartidos pero anonimizados

Los profiles SI se entrenan con sesiones de todos los tenants (ese es el moat). Pero:

- Datos identificadores **NUNCA** cross-tenant: ni `account_id`, ni URLs especificas, ni track external_ids del cliente entran en el profile training pipeline.
- Lo que entra: gestos mouse normalizados (delta x/y, velocity, acceleration, jitter), timings entre eventos, scroll inertia, save/skip ratios desidentificados, distribucion temporal de plays.
- ETL `BehavioralCorpusIngest` se ejecuta diariamente con paso de **anonimizacion explicito** (ver sub-seccion).
- Auditoria: cada feature ingresa con campo `source_anonymized=true` y schema validacion CI.

### Anonimizacion — checks formales

```python
FORBIDDEN_FIELDS = {
    "account_id", "tenant_id", "track_id", "external_id",
    "playlist_id", "artist_id", "ip", "proxy_id", "fingerprint_id",
    "user_email", "username", "session_id", "url", "user_agent_full",
}

def assert_anonymous(record: dict) -> None:
    leaked = set(record.keys()) & FORBIDDEN_FIELDS
    if leaked:
        raise CorpusContaminationError(f"forbidden fields: {leaked}")
```

Test gating en CI: `pytest tests/integration/test_corpus_anonymization.py`. Falla si una run de ingest contiene un solo registro con campo prohibido. CI bloquea merge.

## Servicios

### Sessions service

- FastAPI + uvloop.
- Endpoints: `POST /v1/sessions`, `GET /v1/sessions/{id}`, `POST /v1/sessions/{id}/close`, `GET /v1/sessions/{id}/metrics`.
- Coordina con `Browser pool manager` para asignar slot.
- Persiste cookie jar / localStorage encriptado por tenant en MinIO (clave de envoltura tenant-specific en Vault local).

### Behaviors service

- FastAPI thin layer.
- Despacha al `Behavior orches` (Temporal workflow `RunBehaviorPlayback`).
- Activities: open_session, login_account_via_creds_passed_in_request, navigate_to_target, run_behavior_engine_with_profile, collect_metrics, close_session, emit_webhook.

### Billing / tenants service

- Postgres `tenants`, `api_keys`, `credits_ledger`, `topups`, `invoices`.
- Integracion con BTCPay self-hosted para detectar transacciones cripto incoming.
- Cron `ReconcileCredits` cada 5 min: checa pending topups y libera credits. Idempotente.

### Browser pool manager

- Servicio interno (no API publica).
- Mantiene un pool de browsers warm-launched (Patchright/Camoufox).
- Politica: target = utilization 70% para responder bursts. Auto-scale up al 85%, down al 50%.
- Pool fragmentado por `[geo, device_class, browser_engine]`.

### Granja 4G / 5G — capacidad para tenants externos

En Año 3 la granja interna escala a 1000+ modems en 4-5 paises. Capacidad target Mes 12 Año 3:

| Geo | Modems | Sesiones/dia capacidad |
|---|---|---|
| Lithuania (FI/EU) | 350 | ~140k |
| Bulgaria (EU) | 250 | ~100k |
| Vietnam | 250 | ~100k |
| Mexico | 100 | ~40k |
| (rotacion redundancia) | 100 | overflow |

Total ~1000 modems, ~480k sesiones/dia, ~14.4M sesiones/mes capacidad. Demanda estimada Mes 12 Año 3 = 1.5M sesiones/mes spinoff + 3-5M sesiones/mes operador interno = ~6.5M. Sobra capacidad 2x para crecimiento o failover.

## Data leakage prevention — controles explicitos

| Control | Mecanismo |
|---|---|
| RLS Postgres en todas las tablas tenant-scoped | Policies + tests integration |
| Logs no incluyen payload sensible cross-tenant | Linter de logs con regex bloqueada en CI |
| MinIO buckets por tenant con SSE-KMS y key per-tenant | KMS local Vault |
| Backups por tenant separables (selective restore) | Schemas Postgres + scripts mantenimiento |
| Audit logs todos los accesos cross-tenant (ej. soporte interno) | Tabla `ml_audit.cross_tenant_access` con justificacion + ttl |
| Profiles training: anonimizacion CI gating | `assert_anonymous` + tests |
| API keys hashed con argon2id | DB nunca contiene plaintext |

## Billing — cripto-only

### Stack

- BTCPay Server self-hosted en VPS aislado (no en cluster principal). Acepta BTC, USDT (ERC20/TRC20/Solana), USDC, LTC.
- Reconciliacion cada 5 min cron via webhook BTCPay -> billing service.
- Refunds manuales solo (gastos de gas a cargo del SaaS si error nuestro).
- Wallet operativa rotada cada 90 dias (cold storage del 80%, hot 20% para refunds y ops).

### Tabla `credits_ledger`

```sql
CREATE TABLE credits_ledger (
    id           BIGSERIAL PRIMARY KEY,
    tenant_id    UUID NOT NULL,
    delta_cents  BIGINT NOT NULL,         -- + topup, - charge
    reason       TEXT NOT NULL,
    reference_id TEXT,                    -- session_id / behavior_run_id / topup_tx_hash
    balance_cents_after BIGINT NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

Append-only. Balance se calcula `SUM(delta_cents)` o usa la columna materializada. Auditoria mensual reconcilia con BTCPay.

### Invoicing

- No emitimos facturas fiscales formales (compatible con setup BVI/RAK + cripto-only).
- Cliente solicita "receipt" PDF on-demand con metadata minima (tenant_id, periodo, agregado de cargos, hash del periodo). No tax id.
- Si cliente requiere factura fiscal: rechazar (no compatible con OPSEC).

### Compliance

- KYC ligero: email + wallet origen del primer topup.
- AML check: tx desde mixers conocidos (Tornado, Sinbad) → bloqueo manual + revision. Metodo: client-list desde Chainalysis-style API (Crystal o similar).
- Sanciones: chequeo wallet contra OFAC SDN list cada 24h.
- TOS: limita uso a "automated testing of public web services" — terminologia neutra, no se compromete a "music streaming".

## Compute footprint incremental

### Hetzner

- 2 nuevos nodos EX dedicados spinoff (separados del cluster operador interno).
- VPN privada WireGuard mesh entre los 2 clusters para uso compartido de granja modems.
- DBs separadas (Postgres + ClickHouse), backups separados.

### Costos infra incremental Año 3

- Hetzner spinoff: $1.5k/mes.
- Cloudflare Tunnel + plus: $0.5k/mes.
- BTCPay VPS: $0.1k/mes.
- Granja: 0 incremental (capacidad sobrada, share del operador interno).
- Bandwidth / storage: $0.5k/mes.
- Total infra incremental: ~$2.6k/mes.

Esto se complementa con [05-financial-model.md](./05-financial-model.md) donde el costo total opex spinoff se calcula con todos los componentes (devs, soporte, etc).

## Disaster recovery

- Postgres: replica streaming + backup nightly cifrado a S3 region distinta.
- ClickHouse: backup ZooKeeper-managed nightly.
- MinIO: 3-way replication local + sync a object storage offshore.
- API endpoint failover: 2 nodos API en regiones diferentes (FI/DE) con DNS LB Cloudflare.
- Granja: si pais X cae (corte cellular, regulatorio), otros 3 paises absorben hasta 30% incremental temporary.
