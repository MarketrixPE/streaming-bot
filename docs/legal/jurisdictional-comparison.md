# Comparativa de jurisdicciones para el holding

> Aplica a Mes 10-12, fase `legal-setup`. Decision a tomar UNA vez,
> con review anual. Esta tabla NO sustituye consejo legal local;
> es input para una conversacion con un tax lawyer.

## Resumen ejecutivo (TL;DR operativo)

| Criterio operativo dominante | Recomendacion 2026 |
|------------------------------|--------------------|
| Banking compatible con USD/EUR sin friccion | **Estonia OU** o **Wyoming LLC** |
| Anonimato beneficiario real (UBO) maximo | **RAK ICC (UAE)** o **BVI** (con caveats) |
| Treaty network amplio para repatriacion | **Estonia OU** |
| Coste y velocidad de setup | **Wyoming LLC** o **Seychelles IBC** |
| Reputacional minimo ante DSP/distribuidor | **Estonia OU** o **Wyoming LLC** |
| Resistencia a CRS / intercambio automatico | **Wyoming LLC** (US no participa en CRS sino en FATCA reverso, ver caveat) |

> **Reco operativa**: la mayoria de operadores black-hat profesionales
> 2025-2026 corren un **stack 2 capas**: Wyoming LLC (operativa con
> banking USD: Mercury/Wise, baja friccion) + RAK ICC o BVI como
> holding patrimonial superior (UBO no publico, separacion patrimonial).
> Estonia OU es alternativa whitelist-friendly si el operador acepta
> reporting publico via e-Business Register.

## Matriz de comparacion 2026

> Datos de coste actualizados a Q1 2026; revisar antes de incorporar.
> Fuentes en notas al pie.

| Criterio | Estonia OU | BVI BC | Seychelles IBC | Wyoming LLC | RAK ICC (UAE) |
|----------|-----------|--------|----------------|-------------|---------------|
| Setup cost (incorporacion + 1er ano) | EUR 190 state fee + EUR 250-450 e-Residency + EUR 350-900 service [^1] | USD 1,500-2,500 incl. registered agent + USD 450 government fee [^2] | USD 800-1,500 + USD 100 government fee [^3] | USD 102 state filing + USD 199-499 registered agent service [^4] | AED 13,000-16,500 (~USD 3,540-4,490) all-in [^5] |
| Setup time | 1-3 dias habiles si hay e-Residency, 2-4 semanas si no | 5-15 dias habiles | 3-10 dias habiles | 1-3 dias habiles | 5-10 dias habiles |
| Ongoing cost / ano (renewal + agent) | EUR 350-900 + accounting EUR 1,200-2,400 | USD 1,200-2,000 | USD 750-1,200 | USD 199-499 | AED 11,000-14,000 (~USD 2,990-3,810) |
| Banking compatibility | Excelente: Wise, Revolut Business, LHV (residente), Swedbank (KYC duro) | Mediana: bancos locales (CIBC FirstCaribbean, Bank of Asia limit), EMI: Wise rechaza, Mercury rechaza, Airwallex selectivo | Baja: pocos EMI, Statrys revisa caso a caso, banking local solo con presencia | Excelente: Mercury, Wise Business, Relay, Brex (con US presence), Airwallex | Mediana-alta: Wio Bank, Mashreq Neo, RAKBANK, Wise rechaza UAE en 2025-2026 [^6] |
| Accounting requirement | Anual obligatorio + reporte e-Business Register publico (cuentas firmadas) | Solo si pide auditoria fiscal o EU MICA: minimal record-keeping | Minimal record-keeping (no audit obligatoria) | Solo Schedule K-1 si tiene members US-resident, FBAR si activo > USD 10k offshore | Audit obligatorio anual en RAK ICC desde 2024 [^7] |
| UBO publico | Si, e-Business Register expone director (no shareholder por defecto si registras privado) | UBO obligatorio en Beneficial Ownership Secure System (BOSS), no publico pero accesible a autoridades EU/UK por treaty | UBO en registro confidencial, accesible solo bajo treaty | NO publico; LLC member info solo en Operating Agreement privado [^8] | UBO obligatorio ante autoridad RAK ICC; no publico |
| Treaty network (DTT) | 60+ tratados (incluye US, UK, Alemania, Francia, India) [^9] | ~16 tratados, mayoria offshore | ~30 tratados, foco DTT con sub-Saharan + Asia | US treaty network amplio (US-resident only beneficios), pero LLC pass-through complica acceso | UAE tiene 137 tratados [^10], pero RAK ICC offshore generalmente excluido del beneficio |
| CRS / intercambio automatico | Si (CRS desde 2017) | Si (CRS desde 2017) | Si (CRS desde 2017) | NO CRS (US fuera del sistema, solo FATCA reverso) [^11] | Si (CRS desde 2018) |
| Tax corporate | 0% sobre beneficios retenidos, 22% al distribuir dividendos (2026) [^12] | 0% | 0% (nondomestic income) | Pass-through: tributa el member; si UBO no-US y operativa fuera US, 0% federal | 0% RAK ICC offshore + 9% UAE corporate tax para mainland (federal CT) [^13] |
| Tax dividend a UBO | 0% withholding a no-residente | 0% | 0% | 30% withholding salvo treaty (FDAP) | 0% |
| Reputational risk DSP/distribuidor | Bajo (jurisdiccion EU) | Alto (FATF grey-list intermitente, EU AMLD blacklist 2024-2026) [^14] | Alto (idem BVI) | Bajo en US, neutro en EU | Mediano (UAE saliendo de FATF grey list 2024) [^15] |
| Sanctions exposure | Bajo | Bajo | Bajo | Si UBO o counterparty en lista OFAC: bloqueo automatico via banking | Bajo si opera fuera de Iran/Syria/Sudan |
| Substance requirement | No para holding pasivo, si para tax residence | Si tiene "relevant activity" (Economic Substance Act 2018, BVI [^16]): oficina + staff | Si para "core income generating activities" desde Economic Substance Act 2018 | No federal, depende del state | Si para "qualifying activity" segun ESA 2024 (oficina o director residente) |

[^1]: Estonia e-Residency cost: <https://www.e-resident.gov.ee/become-an-e-resident/>; OU registration fee 190 EUR: <https://www.notar.ee/en/services/notarial-services/establishment-of-companies>.

[^2]: BVI BC fees: <https://www.bvifsc.vg/library/business-companies-application-fees>.

[^3]: Seychelles IBC: <https://fsaseychelles.sc/services/international-corporate-services/international-business-companies>.

[^4]: Wyoming LLC filing fee USD 102: <https://wyobiz.wyo.gov/Business/FilingFees.aspx>.

[^5]: RAK ICC fee schedule: <https://www.rakicc.com/incorporation-fees>.

[^6]: Wise UAE policy 2025: Wise no opera con entidades UAE incorporadas en zonas RAK ICC offshore para Business accounts <https://wise.com/help/articles/2932672/who-can-open-a-business-account>.

[^7]: RAK ICC 2024 ESR audit requirement: <https://www.rakicc.com/economic-substance-regulations>.

[^8]: Wyoming LLC UBO privacy: el state acepta nominee organizer + Operating Agreement privado <https://sos.wyo.gov/Business/Docs/LLCFAQ.pdf>. CTA (Corporate Transparency Act) US 2024 obligaba reporte FinCEN; suspendido temporalmente para "domestic" companies en marzo 2025 por ejecutivo, pero sigue para "reporting companies" extranjeros: <https://www.fincen.gov/boi>.

[^9]: Estonian Tax and Customs Board, lista de DTT: <https://www.emta.ee/en/businesses/registration-business/double-taxation/list-tax-treaties>.

[^10]: UAE MOF DTT list: <https://mof.gov.ae/double-taxation-agreements/>.

[^11]: US no participa en OECD CRS, solo en FATCA bilateral: <https://www.oecd.org/tax/automatic-exchange/international-framework-for-the-crs/MCAA-and-CRS-FAQs.pdf>.

[^12]: Estonian distributed-profit tax 22% desde 2025: <https://www.emta.ee/en/businesses/taxes-businesses/income-tax-companies>.

[^13]: UAE Corporate Tax 9% para mainland desde junio 2023, exencion para qualifying free zone persons: <https://mof.gov.ae/corporate-tax/>.

[^14]: EU AMLD high-risk third countries list, ultima actualizacion 2024 incluye intermitentemente BVI/Seychelles: <https://finance.ec.europa.eu/financial-crime/eu-policy-high-risk-third-countries_en>.

[^15]: UAE retirado del FATF grey list febrero 2024: <https://www.fatf-gafi.org/en/publications/High-risk-and-other-monitored-jurisdictions/Increased-monitoring-february-2024.html>.

[^16]: BVI Economic Substance Act 2018: <https://www.bvifsc.vg/library/economic-substance-companies-and-limited-partnerships-act-2018>.

## Caso `United States v. Michael Smith` aplicado por jurisdiccion

> **Fact pattern del caso real**: Michael Smith (musico, Carolina del
> Norte residente; indictment formal en SDNY, NO en NC pese a la
> residencia) cargado en septiembre de 2024 con wire fraud, money
> laundering conspiracy y conspiracy to commit wire fraud. Generaba
> billions of fraudulent streams via bots en Spotify, Amazon Music,
> Apple Music y YouTube Music, cobrando >USD 10 millones en royalties
> via shell companies. Plea deal abril 2025: hasta 60 anos.
> Source: <https://www.justice.gov/usao-sdny/pr/musician-charged-1-million-streaming-royalty-fraud-scheme-aided-artificial>.

### Vector de prueba que uso DOJ
1. Subpoena a DistroKid + AdRev + Audiomack obtuvo identificacion
   directa de Smith como UBO de las shell companies (US-domestic LLCs).
2. Subpoena a bancos US (Bank of America, Wells Fargo) trazo flujos
   USD 10M+ a cuentas personales.
3. Subpoena a ISP + Spotify obtuvo logs IP correlacionados con devices
   de Smith.
4. Tower dump + grand jury testimony de un dev contratado.

### Aplicacion por jurisdiccion en escenario "DOJ replica investigacion contra ti"

| Jurisdiccion | Vector subpoena directa al UBO | Vector via banking | Vector via DSP | Mitigacion adicional |
|--------------|--------------------------------|---------------------|----------------|----------------------|
| **Estonia OU** | Posible: e-Business Register publico expone director (no UBO si registraste UBO via tercero), pero MLA EU-US treaty permite revelar UBO en investigacion criminal en 6-18 meses | EU bancos cooperan via MLAT en weeks. Wise responde a USD subpoena en 30-90 dias | Si Estonia OU es la entity ante distribuidor, vincula directo | Capa Wyoming LLC operativa + Estonia OU patrimonial, royalties cobrados en Wyoming, transferidos via dividendo a Estonia OU |
| **BVI BC** | UBO en BOSS, no publico. MLA US-BVI Treaty 2002 permite revelar UBO en investigacion criminal grave (typical 12-24 meses) [^17] | Bancos BVI cooperan via MLAT. Mercury/Wise no operan con BVI Business salvo casos curados. EMI tipo Statrys revela en days bajo subpoena | Si BVI es la entity ante distribuidor, distribuidor en US (DistroKid, RouteNote) entrega contract data | Necesitas capa intermedia US o EU operativa, BVI solo holding patrimonial |
| **Seychelles IBC** | UBO confidencial pero MLA US-Seychelles existe via 2002 treaty + UN Convention against Transnational Organized Crime, demoras 18-36 meses | Banking dificil. Si tiene cuenta, MLA aplica idem | Igual que BVI; Seychelles ante distribuidor levanta red flags KYC inmediatos | Solo recomendable como holding patrimonial, NO operativa |
| **Wyoming LLC** | DOJ tiene jurisdiction directa: federal grand jury subpoena al registered agent en days. CTA reporting suspendido para domestic 2025 pero FBI puede pedir Operating Agreement via search warrant | Bancos US cooperan en days bajo grand jury subpoena. SAR (suspicious activity report) automatico a USD 10k+ | DSP US entrega contract data inmediato bajo subpoena (sin MLAT necesario) | NO usar Wyoming LLC si UBO esta fuera US y operativa esta en US: convergencia juridiccional total |
| **RAK ICC (UAE)** | UBO ante autoridad RAK ICC, no publico. UAE-US MLAT firmado pero NO ratificado a Q1 2026 [^18]. UAE ha cooperado en casos de drug trafficking y terrorism, no claro en wire fraud unilateral | Banca UAE coopera selectivamente; SAR via UAE FIU a US FinCEN solo en caso especifico | Si UAE es la entity ante distribuidor, distribuidor US sigue subpoena al distro | Mejor proteccion UBO de la lista, peor friccion banking USD |

[^17]: BVI-US MLAT: <https://www.state.gov/wp-content/uploads/2019/02/02-708-British-Virgin-Islands-Mutual-Legal-Assistance.pdf>.

[^18]: UAE-US treaty status: <https://www.state.gov/u-s-bilateral-relations-fact-sheets/>.

## Patron recomendado: 2 capas verticales

```
                    ┌──────────────────────────────────────────┐
                    │  CAPA 2 — HOLDING PATRIMONIAL            │
                    │  RAK ICC (UAE) o BVI BC                  │
                    │  - UBO no publico                        │
                    │  - 0% tax                                │
                    │  - Recibe dividendos de capa 1           │
                    │  - Banca: Wio Bank o local UAE; cripto   │
                    │    cold wallets (SegWit BTC, ETH, USDC)  │
                    └──────────────────┬───────────────────────┘
                                       │ dividendos / inter-company loan
                    ┌──────────────────┴───────────────────────┐
                    │  CAPA 1 — OPERATIVA Y REPORTABLE         │
                    │  Wyoming LLC + Estonia OU                │
                    │  - Wyoming: cobra royalties USD          │
                    │    (Mercury/Wise/Relay)                  │
                    │  - Estonia OU: cobra royalties EUR/      │
                    │    GBP, banca Wise + LHV                 │
                    │  - Distribuidores firmados con Wyoming   │
                    │    o Estonia segun moneda dominante      │
                    │  - Pago a contratistas, cripto on-ramp   │
                    └──────────────────────────────────────────┘
```

## Decision matrix concreta — escenarios

| Escenario | Recomendacion |
|-----------|---------------|
| Operador 100% solo, < USD 100k/ano revenue, foco US/UK | Solo Wyoming LLC + cripto cold wallet personal. Renunciar holding offshore (overhead > beneficio). |
| Operador con > USD 250k/ano, expande a EU + LATAM | Wyoming LLC + Estonia OU operativos, sin holding patrimonial todavia. |
| Operador con > USD 500k/ano, > 3 contratistas | Estructura 2 capas plena: Wyoming + Estonia operativas, RAK ICC patrimonial. Renta dividendos anuales a holding. |
| Operador con > USD 1M/ano, foco Asia (JioSaavn, KKBox, NetEase) | Anadir Singapore Pte Ltd como capa Asia (no en lista comparativa por requerir nominee director residente, ~USD 8k/ano). |
| Operador con co-fundadores (>= 2 personas) | NO compartir UBO en holding patrimonial: cada cofounder tiene su propio holding patrimonial (RAK ICC o BVI), holdings paralelos firman shareholder agreement off-record. |

## Reglas DURAS (no negociables)

1. NUNCA cobres royalties directamente a una cuenta personal a tu
   nombre real con el mismo IP/device usado para operar la granja.
2. NUNCA uses la misma direccion fisica en KYC bancario y registro
   de la entity (usa Hoxton Mix UK, Anywhere365, o equivalente
   ver `compartmentalization.md`).
3. NUNCA registres todos los distros con la misma entity legal:
   distribuye 2-3 distros por entity, max 3 entities en cobro de
   royalties; mas concentracion = subpoena pattern facil.
4. NUNCA mantengas mas de 60 dias de runway en una sola cuenta
   bancaria; barrida mensual a holding patrimonial.
5. ANUALMENTE: revisa estado FATF y EU AMLD blacklist de cada
   jurisdiccion. BVI ha entrado/salido del grey list 3 veces en
   2020-2025; cambio reputacional impacta banking.
