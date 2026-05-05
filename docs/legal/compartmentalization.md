# Compartmentalizacion — el principio de capas no cruzadas

> "Tu nombre real NUNCA aparece en una capa expuesta. Cada capa
> opera con identidad propia, IPs propias, devices propios, email
> propio, telefono propio. Una brecha en cualquier capa NO debe
> permitir el descubrimiento de las otras."
>
> Este principio es la primera defensa contra el patron `US v. Smith`
> (subpoena vertical: distro -> banking -> ISP -> dev -> UBO).

## Capas operativas y reglas de aislamiento

```
┌───────────────────────────────────────────────────────────────────┐
│ CAPA 0  Operador real (tu)                                        │
│   - Nombre real, DOB real, pasaporte real                         │
│   - Banking personal en jurisdiccion de residencia                │
│   - Devices personales (laptop principal, telefono personal)      │
│   - NO toca las capas inferiores con devices/IP/email personales  │
└───────────────────────────────────────────────────────────────────┘
                            │ aporta capital + dirige via
                            │ "consulting agreement"
                            ▼
┌───────────────────────────────────────────────────────────────────┐
│ CAPA 1  Holding patrimonial (RAK ICC / BVI)                       │
│   - UBO formal: tu (vinculacion legal estricta solo aqui)         │
│   - Director: nominee (registered agent provider)                 │
│   - Direccion: oficina del registered agent                       │
│   - Banking patrimonial: 1 cuenta institucional (Wio, Statrys)    │
│   - Cripto: cold wallet multi-sig 2-of-3 (silo `holding`)         │
└───────────────────────────────────────────────────────────────────┘
                            │ shareholding 100% de capa 2
                            ▼
┌───────────────────────────────────────────────────────────────────┐
│ CAPA 2  Operativa fiscal (Wyoming LLC + Estonia OU)               │
│   - Director: nominee o tu (decision dependiente de juris.)       │
│   - Direccion: virtual office (Hoxton Mix, Anywhere365, iPostal1) │
│   - Banking operativo: 4-6 cuentas (ver banking-redundancy.md)    │
│   - Email corporativo: dedicado (Proton Business o Tutanota)      │
│   - VPN dedicada: WireGuard a IP estatica del data plane Hetzner  │
└───────────────────────────────────────────────────────────────────┘
                            │ contrata distros y servicios
                            ▼
┌───────────────────────────────────────────────────────────────────┐
│ CAPA 3  Distribuidores y DSP signing                              │
│   - Una entity por 2-3 distros max (ver multi-distributor v1)     │
│   - Cada distro firmado con email + telefono dedicados a esa      │
│     entity, NO compartidos con otra entity                        │
│   - Direccion fisica: virtual office distinto por entity          │
└───────────────────────────────────────────────────────────────────┘
                            │ publica como
                            ▼
┌───────────────────────────────────────────────────────────────────┐
│ CAPA 4  Identidades de artistas (alias_resolver)                  │
│   - Cada artist alias en una sola distro principal + 1 backup     │
│   - Nombre artistico, foto avatar (Stable Diffusion / Midjourney) │
│   - DOB ficticia, NUNCA matchea tu DOB real                       │
│   - Email artistico: alias en domain de la entity owner del distro│
│   - Web: opcional, link.tree-style en domain owned by entity      │
└───────────────────────────────────────────────────────────────────┘
                            │ se promueve via
                            ▼
┌───────────────────────────────────────────────────────────────────┐
│ CAPA 5  Cuentas DSP / IG / SoundCloud                             │
│   - Cada cuenta tiene email dedicado (mail.tm o aged purchase)    │
│   - Cada cuenta tiene IP de la granja (4G/5G por geo) o residential│
│   - Cada cuenta tiene fingerprint del Coherent Fingerprint Engine │
│   - Persona memory persistente NO compartida entre cuentas        │
└───────────────────────────────────────────────────────────────────┘
                            │ ejecuta en
                            ▼
┌───────────────────────────────────────────────────────────────────┐
│ CAPA 6  Infra ejecucion (Hetzner workers + granja modems)         │
│   - Hetzner contratado por la entity capa 2                       │
│   - Granja contratada via shell company local (UAB Lithuania,     │
│     OOD Bulgaria, Cong Ty TNHH Vietnam)                           │
│   - Cuentas Hetzner pagadas con cripto silo `infra_ops` o tarjeta │
│     prepaid no vinculada a ti                                      │
└───────────────────────────────────────────────────────────────────┘
```

## Reglas DURAS de aislamiento (no negociables)

### 1. Identidades artistas — alias_resolver

| Atributo | Regla | Vector de coincidencia |
|----------|-------|------------------------|
| Nombre artistico | Generador de aliases (curado, no random) por nicho | Nunca contiene tu apellido, ciudad, fecha. NUNCA reusar entre 2 distribuidores. |
| Fecha de nacimiento ficticia | Random uniforme entre 1985-2005 | NUNCA matchea tu DOB real. NUNCA matchea entre 2 aliases (mismo dia/mes/ano = correlacion trivial). |
| Foto avatar | Stable Diffusion / Midjourney 2026 con seed unica + post-process | NUNCA reusar imagen entre aliases. Pasar reverse image search check. |
| Email | Alias dedicado en dominio owned por la entity del distro | NUNCA matchea email personal. NUNCA reusa username pattern. |
| Telefono | Numero del granja modem (4G/5G) en geo apropiada al alias | NUNCA matchea tu telefono real. NUNCA reusa entre aliases. |
| Bio en distros | Generada por GPT-4 con prompt de nicho coherente con la musica | Pasar test "googling 3 frases" sin volver a tus otros aliases. |
| Pais residencia declarada | Geo coherente con la entity del distro y con la geo de royalties | Si el distro declara US, el banking destino debe ser US. |

> Workflow tooling sugerido: tabla `artist_aliases` en Postgres con
> integrity check al insertar. NO implementado en este modulo (ver
> `application/alias_resolver.py` futuro).

### 2. Capa cuenta DSP

| Atributo | Regla |
|----------|-------|
| Email | mail.tm temporal (free) o aged purchase. NUNCA un email reused. |
| Telefono | Granja modem 4G/5G por geo, alquiler temporal via SMS hub propio (no 5SIM por defecto en cuentas de produccion). |
| IP en signup | IP del modem 4G/5G del geo declarado de la cuenta. NO datacenter, NO residential rotativo en signup (el signup es el momento de mas friccion antifraud). |
| Device fingerprint | Generado por Coherent Fingerprint Engine v2 con UA correlacionado al pais + locale. NUNCA reusar fingerprint exacto entre cuentas. |
| Persona memory | Persistida en Postgres (`persona_memory_snapshots`); incluye preferencias musicales, horario tipico, click patterns. |

### 3. Capa email / dominio

> Cada entity legal opera SU PROPIO dominio. Dominio debe ser:
> - Comprado a registrar distinto del personal (ej: tu personal en
>   Cloudflare Registrar, entities en Namecheap, Porkbun, INWX).
> - Pagado con cripto silo `infra_ops` o con tarjeta prepaid emitida
>   a nombre de la entity, NUNCA tarjeta personal tuya.
> - Privacy WHOIS habilitado por default.
> - Email corp en Proton Business o Tutanota (ambos aceptan pago en
>   cripto).
> - DKIM/SPF/DMARC configurado correctamente para que llegue a
>   compliance de bancos.

### 4. Capa IP

| Capa | IP source aceptable | IP NUNCA aceptable |
|------|---------------------|---------------------|
| Tu navegacion personal a banca / DSP corp / docs | VPN comercial (Mullvad, IVPN, Proton VPN) o residential premium SOLO para acceso admin | IP de tu hogar, IP del workplace |
| Operacion DSP (cuentas) | Granja 4G/5G propia, residential premium (ProxyEmpire, IPRoyal Mobile) | Datacenter (DigitalOcean, AWS, OVH), tu VPN personal |
| Operacion banking corp | VPN dedicada del entity (WireGuard a Hetzner control plane) | Tu IP personal, granja modem 4G (mobile en banking levanta KYC) |
| Operacion infra (SSH a Hetzner) | VPN dedicada operador + WireGuard mesh | Tu IP personal directa |

### 5. Capa device

| Capa | Device aceptable |
|------|------------------|
| Tu vida personal | Laptop principal, telefono personal |
| Banking corp | Laptop dedicada (Macbook Air o Thinkpad usado, comprado en cash, jamas conectado a wifi de tu casa con su MAC original; nuevo MAC randomizado) corriendo macOS o Tails |
| Operacion DSP admin | Laptop dedicada distinta del banking, OS endurecido (Tails o Whonix), browser profile distinto por entity |
| Operacion granja / SSH infra | Misma laptop anterior pero perfil de usuario distinto del navegador admin |

> NUNCA uses los mismos hardware identifiers entre capas. Devices
> dedicados se pagan en cash o cripto, jamas tarjeta a tu nombre.

## Setup de operadores nominales (registered agent + nominee director)

> Esto es lo que separa "shell company casera" de "estructura
> profesional". Sin nominee director, tu nombre aparece en filings
> publicos (Estonia OU) o aparece como UBO trazable (BVI/RAK).

### Providers reales 2026 con costes

| Provider | Jurisdicciones | Producto | Coste/ano [^1] |
|----------|----------------|----------|---------------|
| **Hoxton Mix** | UK | Virtual office London + mail forwarding | GBP 25-65/mes |
| **Anywhere365 / Earth Class Mail** | US (Wyoming, Delaware, NV) | Virtual office + mail scan | USD 19-99/mes |
| **iPostal1** | US (50 states) | Virtual address + scan | USD 9.99-39.99/mes |
| **Sterling Office (Estonia)** | Estonia | e-Residency contact person + virtual office + accounting | EUR 100-150/mes |
| **Xolo (Estonia)** [^2] | Estonia | Full-service: e-Residency, OU constitution, accounting, contact person | EUR 89-189/mes |
| **OCRA Worldwide** [^3] | BVI, Seychelles, RAK ICC | Nominee director + nominee shareholder + registered office | USD 1,500-3,500/ano + USD 800-1,500 setup nominee |
| **Sovereign Group** [^4] | Multi (BVI, Seychelles, UAE, Mauritius, Hong Kong) | Idem nominee + corporate secretary | USD 2,000-4,000/ano |
| **Trident Trust** [^5] | Multi (BVI, Cayman, Singapore, BVI, NL Antilles) | Tier-1 nominee provider, used by professional structures | USD 3,000-6,000/ano (mas KYC pesado) |
| **Vistra** [^6] | Multi (Tier-1) | Idem Trident Trust, foco corporate clients | USD 3,500-7,000/ano |

[^1]: Precios verificados Q1 2026 directamente en sitios web; revisar al contratar.
[^2]: Xolo: <https://www.xolo.io/zz-en/leap>.
[^3]: OCRA Worldwide: <https://www.ocra.com/services>.
[^4]: Sovereign Group: <https://www.sovereigngroup.com/services/>.
[^5]: Trident Trust: <https://www.tridenttrust.com>.
[^6]: Vistra: <https://www.vistra.com>.

### Procedimiento contratacion nominee director

1. Manda RFP a 3 providers (template
   `templates/registered-agent-rfp.md`).
2. Verifica con AML check (provider debe poder demostrar AML license
   en su jurisdiccion).
3. Negocia clausula de nominee agreement: tu firmas un nominee
   declaration (declaracion privada de que el nominee actua en tu
   nombre y NUNCA toma decisiones autonomas), provider firma el
   reverso comprometiendose a actuar solo bajo tu instruccion.
4. NUNCA firmes nominee director con poder amplio (general power
   of attorney). Limitar a "specific instructions communicated in
   writing via secure channel".
5. Define canal seguro: PGP-encrypted email a Proton account
   dedicado, o Signal con verificacion de huella en sesion inicial
   en persona o video llamada con ID display.

## Procedimiento "burn down" — capa comprometida

> Trigger: detectas que una capa fue comprometida (cuenta dispatch
> banneada en cluster, distribuidor congela tracks, banking pide
> docs irreversibles, dev contractor amenaza filtrar info).

### Decision matrix por capa comprometida

| Capa | Burn-down accion | Coste estimado | Tiempo |
|------|-------------------|----------------|--------|
| Capa 5 (cuenta DSP individual) | Quarantine via kill-switch (modo `quarantine` ya en dominio), retiro fondos del royalty pool si aplica | Casi cero | Minutos |
| Capa 5 cluster (50+ cuentas mismo IP/fingerprint pattern) | Quarantine cluster + rotar IP del modem afectado + revisar fingerprint coherence | Costo SIM rotation USD 200-500 | 1-3 dias |
| Capa 4 (artist alias) | Takedown del catalogo asociado en TODOS los distros + retiro del alias + reasignar campaigns en routing a aliases sanos | Costo distro takedown 0-USD 200, perdida revenue ~USD 200-1000 segun lifetime track | 7-30 dias hasta full delisting |
| Capa 3 (entity ante distribuidor con KYC review intrusivo) | Cerrar firma con ese distro + redistribuir catalogo a otro distro + cerrar entity si la review escala | Costo cierre entity USD 500-2000 | 30-90 dias |
| Capa 2 (entity operativa con problema fiscal o banking compromiso serio) | Cierre formal con tax lawyer, transferencia activos a entity nueva, dilucion contractual de obligaciones | USD 5,000-15,000 (lawyer + filings) | 90-180 dias |
| Capa 1 (holding patrimonial UBO expuesto) | Reorganizacion estructural completa: nuevo UBO via trust o foundation, transferencia patrimonio a holding nuevo | USD 15,000-50,000 (incluyendo abogados especializados internacional) | 180-365 dias |
| Capa 0 (tu identidad real expuesta a investigacion criminal) | OUT OF SCOPE: requiere tax lawyer + criminal lawyer en jurisdiccion de residencia. NO improvisar. |

### Checklist burn-down de un alias artista (capa 4)

```
[ ] T+0:    Pausar todas campaigns Spotify/Deezer/SoundCloud para tracks del alias
[ ] T+0:    Pausar Reels generators para el alias en Meta layer
[ ] T+1h:   Solicitar takedown manual via UI a TODOS los distros donde el alias publica
[ ] T+24h:  Confirmar takedown propagado a DSPs (Spotify Artist, Deezer Artist, SoundCloud)
[ ] T+24h:  Liberar el alias del alias_resolver (mark deprecated, NO borrar para audit)
[ ] T+48h:  Reasignar tracks "vivos" a aliases sanos via re-distribute con metadata mutada
[ ] T+72h:  Audit log scan: ningun activity en cuentas DSP que aun referencien el alias
[ ] T+7d:   Postmortem template completado (root cause, time-to-recovery, gap analysis)
```

### Checklist burn-down de una cuenta dispatch (capa 5 individual)

```
[ ] T+0:    Trigger kill_switch para la cuenta (estado quarantined)
[ ] T+0:    Pausar el modem que serviva la cuenta + alert manual ops si flagged_count >= 3
[ ] T+0:    Bloqueo cobros pendientes asociados (ningun aplica en capa 5 individual normalmente)
[ ] T+5min: Snapshot de fingerprint, persona memory, IP history a Postgres `account_audit`
[ ] T+1h:   Cargar evento a anomaly detection model como label "banned" para reentrenar
[ ] T+24h:  Si patron repetible: lanzar burn-down de cluster (siguiente checklist)
```

### Checklist burn-down de un cluster cuentas (capa 5 cluster)

```
[ ] T+0:    Identificar el cluster por: mismo IP origen, mismo fingerprint hash, misma SIM iccid, mismo creador (mes signup)
[ ] T+0:    Quarantine masivo: kill_switch a todas las cuentas del cluster
[ ] T+1h:   Rotar IPs de los modems involucrados (rotation_cooldown_seconds reset)
[ ] T+1h:   Si SIM common: incrementar flagged_count del modem; si flagged_count > 5 marcar para reemplazo fisico
[ ] T+24h:  Revisar fingerprint coherence: coverage de UA/OS/locale del cluster vs distribucion humana real esperada
[ ] T+48h:  Retiro preventivo de cuentas con anomaly_score > 0.7 fuera del cluster identificado (rebote)
[ ] T+7d:   Postmortem
```

## Tabla de correspondencia capa <-> que NO debe nunca cruzar a otra

| Cruce prohibido | Por que |
|-----------------|---------|
| Email personal Capa 0 reused en cualquier otra capa | Subpoena email service revela TODO |
| Telefono personal en cualquier signup automatizado | Reverse phone lookup linkea inmediato |
| IP de tu casa en signup DSP | First-party DSP signal limpio que asocia |
| Wallet `holding` envia a wallet `accounts_ops` directamente | On-chain clusterizacion trivial via Chainalysis/Elliptic |
| Mismo nombre de UBO repetido en 2 entities operativas distintas | Subpoena cruzada via beneficial ownership treaty |
| Mismo registered agent provider para holding patrimonial Y operativa | Provider tiene visibilidad total de la pirata; risk concentracion |
| Mismo dominio email para 2 distros distintos | DSP/distro fraud team correlaciona via email pattern |

## Revision trimestral — checklist

Cada 90 dias (calendario fijo, NO opcional):

```
[ ] Audit trim-1: Cuentas bancarias activas vs limites 40/60/3/2 (banking-redundancy.md)
[ ] Audit trim-2: alias_resolver: cualquier coincidencia DOB/foto/email entre aliases?
[ ] Audit trim-3: Modems flagged_count > 5 sin rotacion fisica? -> rotate-flagged-sim.sh
[ ] Audit trim-4: Distribuidor con > 25% del catalogo? -> redistribuir
[ ] Audit trim-5: Logs Postgres de accesos admin (UI dashboard, SSH bastion) -> alguna IP no esperada?
[ ] Audit trim-6: Wallet cripto: cualquier transaccion cross-silo? -> postmortem
[ ] Audit trim-7: Vault/sops secret rotation hace > 90 dias? -> rotate-credentials.sh
[ ] Audit trim-8: Provider registered agent renewal: vencimiento en proximos 90 dias?
[ ] Audit trim-9: Reputational scan jurisdicciones holdings: FATF / EU AMLD changes?
```
