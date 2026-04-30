# streaming-bot

Framework de automatización browser con **Clean Architecture**, **asyncio**,
**fingerprinting coherente** y **observabilidad** lista para producción.

> ⚠️ **Aviso ético/legal**: este proyecto es un refactor educativo de un bot
> de streaming público. **NO ejecutes esta herramienta contra Spotify u otro
> servicio cuyos ToS prohíban automatización**. La estrategia de demo apunta
> a [`demo.playwright.dev/todomvc`](https://demo.playwright.dev/todomvc/),
> un sitio público hecho para automatización. Los principios arquitectónicos
> aquí aplicados son útiles para scrapers legítimos, RPA, testing E2E, QA, etc.

---

## ¿Por qué existe este proyecto?

Es la versión "100x" de un script monolítico de ~200 líneas. Las mejoras
clave sobre el original:

| Eje | Antes | Ahora |
|---|---|---|
| Concurrencia | secuencial (1 cuenta a la vez) | `asyncio.Semaphore`, 10–500 cuentas en paralelo |
| Browser | Chrome completo por cuenta (~400 MB) | Playwright `BrowserContext` (~40 MB) |
| Login | siempre desde cero | `storage_state` cifrado por cuenta |
| Fingerprint | random.choice independiente (tz / lat-lon / lang) | coherente IP↔TZ↔Geo↔Locale↔UA |
| User-Agent | Chrome 94 (de 2021) | Chrome 130 / Firefox 130 / Safari 18 |
| Errores | `try/except: pass` | jerarquía Transient/Permanent + retry exponencial |
| Logs | `print()` con colorama | `structlog` JSON con contexto bindeado |
| Credenciales | `accounts.txt` plano | repo cifrado con Fernet |
| Testabilidad | imposible (god function) | puertos mockeables, tests sub-segundo |
| CI/CD | nada | GitHub Actions + Docker multi-stage |
| Observabilidad | nada | Prometheus + Grafana |

---

## Arquitectura

```
src/streaming_bot/
├── domain/                        # 🟦 Reglas de negocio puras (sin I/O)
│   ├── entities.py                # Account, StreamJob
│   ├── value_objects.py           # Fingerprint, ProxyEndpoint, GeoCoord, StreamResult
│   ├── exceptions.py              # TransientError vs PermanentError
│   └── ports/                     # Protocols (interfaces)
│       ├── browser.py             # IBrowserDriver, IBrowserSession
│       ├── account_repo.py        # IAccountRepository
│       ├── proxy_provider.py      # IProxyProvider
│       ├── fingerprint.py         # IFingerprintGenerator
│       └── session_store.py       # ISessionStore
│
├── application/                   # 🟩 Casos de uso (orquestan dominio)
│   ├── stream_song.py             # StreamSongUseCase + ISiteStrategy
│   └── orchestrator.py            # StreamOrchestrator (concurrencia + retry)
│
├── infrastructure/                # 🟧 Implementaciones concretas
│   ├── browser/playwright_driver.py  # Playwright + stealth
│   ├── repos/encrypted_account_repo.py  # Fernet
│   ├── repos/file_session_store.py
│   ├── proxies/proxy_pool.py      # Health-check + cuarentena
│   ├── fingerprints/coherent_fingerprint.py
│   └── observability/             # structlog + Prometheus
│
└── presentation/                  # 🟨 CLI / TUI
    ├── cli.py                     # Typer + Rich
    └── strategies/                # ISiteStrategy concretas
        └── demo_todomvc.py
```

**Dirección de las dependencias** (regla D de SOLID):

```
presentation ─→ application ─→ domain ←─ infrastructure
                                  ▲
                              (puertos)
```

`domain` no importa nada. `application` solo conoce `domain` (puertos).
`infrastructure` y `presentation` cablean implementaciones via `container.py`.

---

## Quickstart

### Requisitos
- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (`curl -LsSf https://astral.sh/uv/install.sh | sh`)

### 1. Instalar

```sh
cd streaming-bot
uv sync --all-extras
uv run playwright install chromium
```

### 2. Configurar

```sh
cp .env.example .env
uv run streaming-bot keygen   # genera una master key
# pega la clave en .env como SB_STORAGE__MASTER_KEY=...
```

### 3. Importar cuentas (formato user:pass por línea)

```sh
uv run streaming-bot import-accounts ./accounts.txt --country ES
```

### 4. Ejecutar contra el demo

```sh
uv run streaming-bot run --strategy demo_todomvc
```

### 5. Ejecutar contra una URL custom

```sh
uv run streaming-bot run --url https://demo.playwright.dev/todomvc/ --strategy demo_todomvc
```

---

## Calidad

```sh
uv run ruff check src tests       # lint
uv run ruff format src tests      # format
uv run mypy src                   # type-check estricto
uv run pytest                     # tests + cobertura
```

Todo esto corre automáticamente en CI (`.github/workflows/ci.yml`) en
matriz Python 3.11/3.12 + build de imagen Docker.

---

## Docker

```sh
docker compose up --build
```

Levanta:
- `bot` con la app + Chromium
- `prometheus` en `:9091`
- `grafana` en `:3000` (admin/admin)

Métricas expuestas:
- `streaming_bot_stream_attempts_total{country,result}`
- `streaming_bot_stream_duration_seconds{country,result}`
- `streaming_bot_accounts_blocked_total`
- `streaming_bot_proxies_failed_total`
- `streaming_bot_active_sessions`

---

## Añadir un sitio nuevo (OCP)

1. Crea `src/streaming_bot/presentation/strategies/mi_sitio.py`:

```python
from streaming_bot.application.stream_song import ISiteStrategy

class MiSitioStrategy(ISiteStrategy):
    async def is_logged_in(self, page): ...
    async def login(self, page, account): ...
    async def perform_action(self, page, target_url, listen_seconds): ...
```

2. Regístrala en `cli.py::_build_strategy`.
3. **No tocas nada del dominio ni del caso de uso**. Eso es OCP en práctica.

---

## Roadmap

- [ ] Sprint 2: tests E2E con Playwright real contra `demo_todomvc`.
- [ ] Sprint 2: TUI con Textual (dashboard live de progreso).
- [ ] Sprint 3: scheduler con APScheduler / Temporal.
- [ ] Sprint 3: provider de proxies con API (Bright Data / Oxylabs).
- [ ] Sprint 3: anti-captcha (2captcha) como puerto enchufable.

---

## Licencia

MIT.
