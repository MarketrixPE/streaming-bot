# Año 3 — B2B Spinoff (Stealth + Behavioral ML como SaaS)

## Indice

1. [01-product-thesis.md](./01-product-thesis.md) — Tesis: ICP, producto SaaS, defensibilidad, no-cannibalizacion.
2. [02-product-spec.md](./02-product-spec.md) — API endpoints, SDK Python/TypeScript, pricing, integraciones.
3. [03-go-to-market.md](./03-go-to-market.md) — Distribucion discreta via referrals, pricing prepago cripto, pilots.
4. [04-architecture-spinoff.md](./04-architecture-spinoff.md) — Multi-tenancy, aislamiento, prevencion data leakage, billing cripto.
5. [05-financial-model.md](./05-financial-model.md) — Asunciones, revenue, costos, break-even.
6. [06-risks-mitigations.md](./06-risks-mitigations.md) — Cannibalizacion, exposure legal, mitigaciones medibles.

PoCs ejecutables: [`spikes/year-3/`](../../../spikes/year-3/).

---

## Tesis nuclear

> **El motor stealth (Patchright/Camoufox managed pool, Coherent Fingerprint Engine, ghost-cursor patterns, behavioral ML profiles entrenados sobre millones de sessions reales) que construimos para uso interno tiene valor SaaS B2B aislado para otros operadores. NO competimos con nosotros mismos: vendemos infrastructure ("pickaxes"), no growth services finales. El cliente compra el motor; sigue necesitando su catalogo, sus cuentas y sus proxies — que es donde realmente compite contra otros operadores y contra nosotros.**

Concretamente:

- En Año 1-2 acumulamos millones de sesiones reales (gestos mouse, secuencias scroll, decision delays, save/skip patterns) sobre Spotify, Deezer, SoundCloud, Apple, Amazon, Meta. Este corpus entrena modelos behaviorales que cualquier nuevo entrante no puede replicar.
- Esos modelos + la pool de fingerprints actualizada mensualmente + la integracion managed con Patchright/Camoufox son una capa de infrastructure que TIENE demanda en el mercado gris (operadores que no quieren ni pueden construirla solos).
- El SaaS NO incluye cuentas, NO incluye proxies, NO incluye catalogo. Solo el motor.
- El cliente paga por sesion stealth (`$0.05` basica con fingerprint coherente) o por sesion rich (`$0.20` con behavioral playback completo).

## Por que este spinoff y no otro

Tres razones:

1. **El asset ya esta**: 90% del codigo y 100% del corpus se reutiliza. CAPEX incremental real $80k.
2. **Defensibilidad asimetrica**: el corpus behavioral crece monotonicamente. Cada operador-cliente que opera contra DSPs alimenta nuevas senales (anonimas, agregadas) que mejoran los profiles.
3. **No-cannibalizacion clara**: nuestro propio operador interno consume el SaaS al precio de transferencia interno cero. El precio de mercado a clientes (un margen sobre el costo marginal de infra) impide que nos sub-coticen al revender pickaxes contra nosotros mismos en el mercado de royalties.

## Por que en Año 3 y no antes

- Año 1: el motor mismo aun esta en construccion. Vender lo a medio terminar es OPSEC suicida.
- Año 2: estabilizado pero sin masa critica de behavioral data. Producto sin moat.
- Año 3: corpus maduro, infra estable, granja a 1000+ modems en 4-5 paises (capacidad para servir tenants externos sin tocar nuestra capacidad propia), legal compartmentalizacion lista (holdings BVI/RAK, banking redundante).

## Resumen ejecutivo de KPIs Año 3

| KPI | Target Mes 12 Año 3 | Como se mide |
|---|---|---|
| Tenants activos | 50 | tenants con sesiones > 100/mes ultimos 30d |
| Sessions/mes total | 1.5M | union sesiones basicas + rich |
| ARPU mensual | $3.7k/tenant | revenue / tenants activos |
| MRR spinoff | $187k | revenue mensual recurrente |
| Margen bruto | >= 65% | (revenue - costos infra incremental) / revenue |
| Churn mensual | < 8% | tenants perdidos / tenants activos T-1 |
| Tiempo a primera sesion exitosa | < 60 min | desde firma a primer 200 OK en `/v1/sessions` |
| Tasa exito sesion basica | >= 92% | sessions con `status=completed` / sessions iniciadas |
| Tasa exito sesion rich | >= 85% | idem rich (mas exigente) |
| % revenue desde top-3 tenants | < 35% | (no concentracion peligrosa) |
| Break-even cumulativo | Mes 5-6 | revenue acumulado >= CAPEX + OPEX acumulado |
| Detection rate ratio cliente vs interno | <= 1.2x | bans / sessions cliente vs interno (ningun degradado) |

## No-objetivos explicitos

- NO se ofrecen cuentas / proxies / catalogo a tenants. Solo motor.
- NO se vende publicamente, NO marketing en LinkedIn, Twitter, Producthunt. Distribucion discreta.
- NO se acepta tarjeta de credito, NO Stripe, NO PayPal. Cripto-only.
- NO se hace soporte 24/7 white-glove. Self-serve docs + Telegram channel privado.
- NO hay SLA contractual riguroso (mercado gris no lo paga, y exponernos legalmente a SLAs es mala idea).
