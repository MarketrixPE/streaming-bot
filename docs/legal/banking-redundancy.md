# Playbook de banking redundante

> Aplica a Mes 1 (banking minimo viable: 3 cuentas) y Mes 10
> (redundancia plena: 6+ cuentas en 3+ jurisdicciones). Revision
> trimestral. Cualquier institucion que congele fondos por
> "compliance check" debe poder ser sustituida en 24-48 horas sin
> perdida material de capital operativo.

## Principio rector

> "Nunca pongas mas del 40% de tu revenue en una institucion. Nunca
> pongas mas del 60% en una jurisdiccion. Nunca dejes mas de 60
> dias de runway en cuentas reportables (Wise/Mercury); barrido
> mensual al silo holding."

## Tier 1 — EMI/Bancos operativos primarios (cobro de royalties)

| Provider | Jurisdiccion | KYC dificultad | Tipica fee | Limites mensuales relevantes | Probabilidad freeze | Comentario operativo |
|----------|--------------|-----------------|------------|-------------------------------|--------------------|----------------------|
| **Wise Business** [^1] | UK / Belgica / US (multi-licensed) | Alta: requiere business docs, proof of revenue, descripcion de actividad creible | 0.43% (avg conversion), USD 31 setup | No hard limit, KYC review > USD 50k/mes | Mediana: si actividad "music distribution" no tiene contracts visibles, freeze a 60-120 dias | Mejor para royalties USD/EUR/GBP. NO acepta entidades BVI / RAK ICC. Acepta Wyoming LLC, Estonia OU. |
| **Mercury** [^2] | US (Choice Financial Group + Evolve Bank, Member FDIC) | Mediana: solo entidades US o Estonia OU + e-Residency | Free banking, fees solo en wires | 4 free outgoing wires / mes despues USD 5/wire | Baja-mediana: Mercury cierra cuentas con "high-risk industry" en review semestral; "music distribution" pasa con descripcion bien curada | Mejor para Wyoming LLC. NO opera con offshore puro. |
| **Revolut Business** [^3] | UK / EU (LT bank license) | Mediana: KYC + KYB, requires director ID | 0.4% conversion, plans desde EUR 25/mes | Plan Grow: 100 free local + 5 international transfers | Mediana-alta: Revolut conocido por freezes silenciosos en industries grises | Acepta Estonia OU, Wyoming LLC. Util para EUR/GBP. |
| **Airwallex** [^4] | HK + AU + EU (LT EMI) | Alta: due diligence detallada, requiere descripcion de business model | 0.4-0.6% FX, free local transfers | Limites custom segun tier | Baja para entities legitimas con substance, alta sin substance | Excelente para multi-currency. Acepta selectivo BVI con substance. |

[^1]: Wise Business pricing: <https://wise.com/pricing/business>. KYB requirements: <https://wise.com/help/articles/2932670/business-account-eligibility>.
[^2]: Mercury banking partners + FDIC disclosure: <https://mercury.com/legal/banking-partners>.
[^3]: Revolut Business pricing: <https://www.revolut.com/business/business-account-plans/>.
[^4]: Airwallex pricing: <https://www.airwallex.com/pricing>.

### Configuracion minima Tier 1 (Mes 1)

- **Cuenta primaria USD**: Mercury (entity Wyoming LLC).
- **Cuenta primaria EUR**: Wise Business (entity Estonia OU).
- **Cuenta secundaria multi-currency**: Airwallex (entity Estonia OU
  o Wyoming LLC, segun donde esta el director).

## Tier 2 — EMI/Bancos backup (overflow + freeze fallback)

| Provider | Jurisdiccion | Caso de uso | Fee tipico | Notas operativas |
|----------|--------------|-------------|------------|------------------|
| **Payoneer** [^5] | US (NY) + UK (FCA EMI) | Recibe ACH desde DistroKid, RouteNote, Stem, Audiomack que pagan via Payoneer-as-rails. | 1-3% transferencia | Bajo umbral KYC. Util para sellos pequenos sin Wise/Mercury. |
| **Statrys** [^6] | HK | Multi-currency, acepta entities BVI / Seychelles / RAK ICC con substance demostrada | USD 88/mes setup + USD 28/mes service | Banca tradicional con UI EMI. Maneja USD/EUR/HKD/CNH. KYC duro pero acepta jurisdicciones ofrshore. |
| **Niall (Czech)** [^7] | Republica Checa (CZK + EUR + USD) | EU-friendly EMI con tolerancia industries grises (gaming, crypto, licenses) | EUR 1500-2500 setup, EUR 200-400/mes | Niall (rebrand "Niall Bank" desde 2024) es uno de los pocos EMI EU con apetito por high-risk merchants. |
| **BlackCat / Clear Junction (HK)** [^8] | HK | Cuentas USD/EUR/HKD para entities asiaticas (Singapore, HK Ltd, BVI) | USD 500-1500 setup, USD 80-200/mes | Solo via introducer; no aplicacion publica. |

[^5]: Payoneer fees: <https://www.payoneer.com/about/pricing/>.
[^6]: Statrys pricing: <https://statrys.com/pricing>.
[^7]: Niall (ex-Niall.cz) Czech EMI; sin URL publica de pricing, solo via comercial.
[^8]: Clear Junction: <https://clearjunction.com/services/banking-as-a-service/>.

## Tier 3 — Cripto on/off ramps (freeze fallback definitivo)

> Estos son el "anti-freeze" final. Si las Tier 1 + 2 te congelan a
> la vez (improbable pero el riesgo existe), cripto OTC permite
> mover capital en horas, NO dias.

| Provider / canal | Volumen tipico por trade | Fee | KYC |
|------------------|--------------------------|-----|-----|
| **Bitget OTC** [^9] | USD 10k-1M+ | 0.05-0.20% | Tier 2 Bitget account (passport + selfie). Setup 24-72h. |
| **MEXC OTC** [^10] | USD 5k-500k | 0.10-0.30% | Tier 2 MEXC account |
| **Binance P2P** [^11] | USD 100-50k por trade | 0% maker, 0.1-0.5% pago peer | Tier 2 Binance + escrow + KYC merchant |
| **Wirex** [^12] | USD 100-50k debit conv. crypto-to-fiat | 1-3% spread | KYC EU-grade |
| **Cold wallet self-custody** | unbounded | 0 (red fee BTC ~ USD 1-5) | N/A — destino final del barrido |

[^9]: Bitget OTC: <https://www.bitget.com/otc>.
[^10]: MEXC OTC: <https://www.mexc.com/otc>.
[^11]: Binance P2P: <https://p2p.binance.com>.
[^12]: Wirex EU: <https://wirexapp.com/eu>.

### Wallets cripto operativas — UN HD wallet por silo, NUNCA cruzados

> Generar 4 HD wallets BIP-39 distintas (24 palabras), almacenadas
> en hardware wallet separado o paper wallet en safe deposit box
> distinto. NUNCA derives todas del mismo seed master.

| Silo | Proposito | Direcciones derivadas | Hardware sugerido |
|------|-----------|------------------------|-------------------|
| `catalog_ops` | Pagos a productores AI (Suno, Udio creditos), masterizacion (LANDR), distros con cripto-payment opcional | BTC + USDC ETH + USDT TRC-20 | Ledger Nano X dedicado |
| `accounts_ops` | Pagos a 5SIM, ProxyEmpire, AccsMarket, AccsFarm, captcha solvers (CapSolver, 2Captcha) | BTC + USDT TRC-20 (mas barato fee) | Trezor Model T dedicado |
| `infra_ops` | Pagos a Hetzner Server Auction (acepta cripto via PayPro/BitPay), Cloudflare R2, MinIO/B2 backups | BTC + USDC ETH | Ledger Nano X dedicado |
| `holding` | Cold storage anual de profit, NO transaccional | BTC SegWit (cold), ETH + USDC L2 (Arbitrum/Base), USDC Solana | Air-gapped Trezor en safe deposit, multi-sig 2-of-3 |

> **Regla DURA**: una direccion del silo `accounts_ops` NUNCA recibe
> fondos directamente del silo `holding`. Si necesitas top-up de
> ops, el path es: holding -> exchange OTC -> Wise/Mercury (o un
> EMI Tier 2) -> conversion fiat -> on-ramp a wallet ops desde una
> direccion limpia. La traza on-chain entre silos es la primera
> prueba que un investigator usa para clusterizar.

## Formula de diversificacion (regla 40/60/3/2)

```
- Max 40% revenue mensual por institucion
- Max 60% AUM por jurisdiccion
- Min  3 cuentas activas en Tier 1+2
- Min  2 jurisdicciones distintas
```

Calculo de chequeo (ejecutar cada mes con script trivial):

```sh
# Pseudo-calculo manual; un dashboard real vive en Grafana panel
# "Banking diversification".
# Para cada cuenta: $revenue_mensual / $revenue_total >= 0.40 -> ALERT
# Para cada juris:  sum($AUM_juris) / sum($AUM_total) >= 0.60 -> ALERT
```

## Procedimiento "compliance check" / freeze — mover fondos en 24-48h

> Trigger: la institucion congela operaciones, pide documentos
> adicionales, o anuncia "review" sin timeline. Asume freeze full
> en 5 dias habiles.

### Checklist primeros 60 minutos

- [ ] Capturar TODOS los documentos pidiendo (screenshot del email,
  ticket de soporte, captura de UI).
- [ ] Preguntar al support: "What is the case number? Is the account
  fully restricted or only outgoing transfers? What is your timeline
  for response?" Documentar respuesta literal.
- [ ] Confirmar saldo actual exacto. Tirar export CSV de transacciones
  de los ultimos 90 dias.
- [ ] NO discutir con compliance via chat: tono profesional, frases
  cortas, NO admitir nada sobre el origen de fondos. Decir "I'm
  preparing the requested documentation, will respond by [+48h]."
- [ ] Cancelar TODAS las facturas recurrentes que cobran a esa
  cuenta (Hetzner, Cloudflare, etc.) y mover billing a backup.

### Checklist primeras 24 horas

- [ ] Si la cuenta permite outgoing: enviar 90% del saldo a Tier 2
  o Tier 1 alterna en SPLITS de < USD 9,500 (umbral SAR US) por
  transaccion para evitar trigger automatic. NO splittear si la
  cuenta es UE; los splits debajo de USD 10k por debajo del umbral
  CRS son red flag mas grande que un transfer unico de USD 30k.
- [ ] Si no permite outgoing: empieza prep documental con tax lawyer
  para apelar el freeze formalmente en plazo legal.
- [ ] Cargar previsiones de runway con saldo restante en Tier 2 +
  Tier 3.
- [ ] Notificar al holding silo: posible barrido extraordinario
  necesario si runway < 30 dias.

### Checklist 24-48 horas

- [ ] Migrar TODOS los cobros entrantes (DistroKid, RouteNote, etc.)
  a la cuenta backup. Login en cada distribuidor, cambiar payout
  method.
- [ ] Si el saldo no se libero: convertir a cripto via Tier 3 OTC.
  Usar Bitget OTC para tickets > USD 50k (mejor spread); MEXC OTC
  o Binance P2P para tickets < USD 50k.
- [ ] Documentar incidente en `docs/runbooks/dr/postmortem-template.md`
  con time-to-recovery real. Output al runbook anual de DR.

### Procedimiento si la cuenta es congelada totalmente sin outgoing

```
T+0:        Documentar freeze, tono profesional al support.
T+24h:      Engage tax lawyer local (UK FCA / NY DFS / EU AMLD).
T+5 dias:   Submit formal complaint regulator si compliance no
            responde (UK: Financial Ombudsman; US Mercury: Choice
            Financial Group via partner; EU: regulador EMI nacional).
T+30 dias:  Tipico fondos liberados con explicacion (>= 60% casos)
            o fondos retornados a la cuenta de origen (~30% casos)
            o liquidacion forzada con pago al UBO acreditado (~10%).
```

> Asume worst-case: cuenta perdida 100% durante 90-180 dias. Tu
> runway DEBE estar disenado para sobrevivir esto sin dejar de
> operar. Si runway en cuentas backup + cripto < 90 dias de OPEX,
> ajusta diversificacion ANTES de seguir creciendo.

## Lista de OTC contacts y criterios de seleccion

> Esta es una decision delicada. Los OTC desks no estan publicos al
> nivel directorio; se accede via referrals o broker intermediarios.
> Criterios para escoger un OTC desk:

1. **Volumen historico verificable**: pide reporte de trades del
   ultimo trimestre (NDA mediante). Desk con < USD 100M/mes no es
   institucional; te puede frontrunear.
2. **Custody**: el desk NO debe pedirte enviar fondos antes de fijar
   precio. Workflow correcto: "RFQ -> price quote in 30s window -> tu
   confirmas -> escrow simultaneo -> settlement in T+0 o T+1".
3. **Settlement options**: debe ofrecer minimo 3 settlement rails
   (Fedwire, SWIFT, SEPA, Faster Payments UK, USDT TRC-20).
4. **KYC compatible con tu jurisdiccion**: si tu UBO esta en UAE o
   BVI, confirma que el desk te acepta sin "enhanced due diligence"
   adicional sobre la entity.
5. **Reputacional**: pregunta a 2 referencias previas. Si el desk se
   niega a dar referencias, pasa.

| Tipo de desk | Donde buscar |
|--------------|--------------|
| Crypto-native institutional | Cumberland (DRW), Galaxy Digital OTC, Genesis (post-bankruptcy review), Coinbase Prime |
| Exchange-affiliated OTC | Bitget OTC, OKX OTC, Bybit Institutional, MEXC OTC |
| Local market makers | Singapore: QCP Capital; UAE: Rain OTC; CH: Sygnum; HK: HashKey OTC |
| P2P last resort | Binance P2P (alto fee, alta KYC), Bisq decentralized (lento, low ticket) |

## Tabla resumen — setup recomendado por fase

### Mes 1 (minimo viable)

| Cuenta | Entity | Saldo target |
|--------|--------|--------------|
| Mercury USD | Wyoming LLC | 30-60 dias runway |
| Wise Business EUR | Estonia OU | 30 dias runway + buffer cobros |
| Cripto wallet `accounts_ops` | self | USD 5-10k operativo |

### Mes 6 (operacion en regimen)

| Cuenta | Entity | Saldo target |
|--------|--------|--------------|
| Mercury USD | Wyoming LLC | 30 dias runway US-side |
| Wise Business EUR | Estonia OU | 30 dias runway EU-side |
| Airwallex multi | Estonia OU | 30 dias runway buffer |
| Statrys multi | BVI BC o RAK ICC | reservorio 60-90 dias |
| Cripto wallets x4 silos | self | profit acumulado mes anterior |

### Mes 12 (resiliencia plena)

Anadir:
| Niall Czech EUR | Estonia OU | overflow / freeze backup |
| Payoneer USD | Wyoming LLC | rails para distros minor |
| Holding cold cripto multi-sig | RAK ICC patrimonial | profit acumulado anual |

## Checks operativos automatizables

Tareas para anadir al `cron` del control plane (referencia, no
implementadas en este modulo):

```cron
# Snapshot diario de saldos a Postgres + alerta Telegram si cualquier
# cuenta cae bajo runway 30 dias.
0 7 * * * /opt/streaming-bot/infra/scripts/banking/snapshot-balances.sh

# Reporte semanal de diversificacion (40/60/3/2).
0 9 * * 1 /opt/streaming-bot/infra/scripts/banking/diversification-check.sh
```

> NOTA: estos scripts NO estan en la whitelist de este runbook. Su
> creacion va en una fase posterior (modulo banking dedicado).
