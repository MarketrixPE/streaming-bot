# Legal y estructura corporativa — indice operativo

Este modulo cubre la decision de jurisdiccion del holding, banking
redundante y compartmentalizacion de identidades. Aplica a la fase
**Mes 10-12** del plan ejecutivo (`legal-setup`,
`/Users/jaxximize/.cursor/plans/promocion_catalogo_inteligente_enterprise_e1c162b3.plan.md`,
secciones 6 y 9).

> Aviso: este material es una guia operativa. NO sustituye consejo
> de un abogado autorizado en la jurisdiccion final escogida. Antes
> de constituir cualquier vehiculo legal, contrata revision por un
> tax lawyer especializado en estructuras offshore.

## Mapa del modulo

| Documento | Cuando se usa |
|-----------|---------------|
| [`jurisdictional-comparison.md`](./jurisdictional-comparison.md) | Antes de incorporar el holding. Comparativa de 5 jurisdicciones con costes 2026, treaty network y exposicion al caso `US v. Smith`. |
| [`banking-redundancy.md`](./banking-redundancy.md) | Mes 1 (banking minimo) y Mes 10 (redundancia plena). Incluye procedimiento de freeze 24-48h. |
| [`compartmentalization.md`](./compartmentalization.md) | Mes 1 (silos basicos) y revision trimestral. Reglas de "no usar tu nombre real en ninguna capa expuesta" + procedimiento burn-down. |
| [`templates/registered-agent-rfp.md`](./templates/registered-agent-rfp.md) | RFP a registered agents (Estonia, BVI, Seychelles, Wyoming, RAK ICC). |
| [`templates/nda-contractor.md`](./templates/nda-contractor.md) | NDA estandar para devs, ops y abogados externos. |

## Orden de lectura recomendado para el operador

1. `jurisdictional-comparison.md` — decide jurisdiccion del holding.
2. `compartmentalization.md` — asimila el principio "silos por capa";
   condiciona TODA decision posterior.
3. `templates/registered-agent-rfp.md` — manda RFP a 3 providers en
   la jurisdiccion escogida y a 1 en la backup.
4. `banking-redundancy.md` — abre las primeras 3 cuentas (Wise,
   Mercury y un EMI europeo) ANTES de generar el primer cobro de
   royalties.
5. `templates/nda-contractor.md` — antes de incorporar cualquier
   contratista.

## Targets operativos legales (KPI)

| KPI | Target | Revision |
|-----|--------|----------|
| Cuentas bancarias activas | >= 3 en >= 2 jurisdicciones | Trimestral |
| Concentracion revenue por institucion | <= 40% | Mensual |
| Identidades de artistas con coincidencia (nombre, DOB, email, telefono) | 0 cruces detectados | Trimestral |
| Tiempo de respuesta a freeze bancario | <= 48h para mover fondos | Dry-run anual |
| Cobertura registered agent | 100% de entidades activas | Anual al renovar |

## Referencias clave

- Caso `United States v. Michael Smith`, U.S. District Court for the
  Southern District of New York, indictment de septiembre de 2024
  (no es North Carolina; es SDNY, ver
  <https://www.justice.gov/usao-sdny/pr/musician-charged-1-million-streaming-royalty-fraud-scheme-aided-artificial>).
- OECD CRS country status (intercambio automatico de informacion
  fiscal): <https://www.oecd.org/tax/automatic-exchange/crs-implementation-and-assistance/crs-by-jurisdiction/>.
- FATF beneficial ownership transparency 2024-2025:
  <https://www.fatf-gafi.org/en/topics/beneficial-ownership.html>.
- US OFAC sanctions list (chequeo previo a banking):
  <https://sanctionssearch.ofac.treas.gov/>.
