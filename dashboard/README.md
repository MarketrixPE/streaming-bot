# Streaming Dashboard MVP

Panel de control operativo para el sistema de streaming. SPA construida con
Next.js 15 (App Router), React 19, Tailwind CSS v4, shadcn/ui, Tremor, TanStack
Query/Table, Maplibre y Better Auth.

## Stack

- Next.js 15 (App Router, React Server Components por defecto)
- React 19 + TypeScript 5.7 (strict)
- Tailwind CSS v4 + tokens estilo shadcn
- Tremor 3.18 + Recharts 3 (fallback)
- TanStack Query 5 + TanStack Table 8
- Maplibre GL 5 (lazy-loaded, `ssr: false`)
- Better Auth 1.6 (adaptador Postgres opcional; fallback en memoria)
- next-intl 4 (ES/EN)
- Zustand 5, Zod 3

> Nota sobre versiones: el brief original pedía versiones que aún no existen en
> npm (TanStack Query 6, TanStack Table 9, Tremor 4). Se usan las últimas
> estables disponibles al cierre del MVP. Cuando Tremor 4 deje beta o TanStack
> publique v6/v9 GA basta con subir el rango en `package.json`.

## Requisitos

- Node.js 22 LTS
- pnpm 10

## Setup

```bash
cp .env.example .env.local
pnpm install
pnpm dev
```

El dashboard arranca en `http://localhost:3000`. Si `NEXT_PUBLIC_API_URL` está
vacío, el cliente de API devuelve fixtures en memoria, suficientes para ver las
5 vistas funcionando sin backend.

## Scripts

| Script          | Qué hace                                         |
| --------------- | ------------------------------------------------ |
| `pnpm dev`      | Next dev server con Turbopack                    |
| `pnpm build`    | Build de producción                              |
| `pnpm start`    | Server de producción                             |
| `pnpm lint`     | ESLint (`next/core-web-vitals` + TS strict)      |
| `pnpm typecheck`| `tsc --noEmit` con `strict` y `noUncheckedIndexedAccess` |
| `pnpm format`   | Prettier                                         |

## Vistas

- `/overview` — KPIs 24h + Maplibre en vivo + serie por DSP
- `/catalog` — tabla TanStack con filtros (DSP, tier, distribuidor, status)
- `/accounts` — heatmap geo × estado + filtros país/tier
- `/jobs` — cola Temporal, polling cada 5 s
- `/anomaly` — alertas activas, ack + timeline + sparkline

## Estructura

```text
dashboard/
├── src/
│   ├── app/
│   │   ├── (auth)/login/page.tsx
│   │   ├── (dashboard)/{overview,catalog,accounts,jobs,anomaly}/page.tsx
│   │   ├── (dashboard)/layout.tsx
│   │   ├── api/auth/[...all]/route.ts
│   │   ├── layout.tsx
│   │   ├── page.tsx
│   │   └── providers/*.tsx
│   ├── components/
│   │   ├── ui/*          # primitives estilo shadcn
│   │   ├── charts/*      # Tremor/Recharts + Maplibre wrapper
│   │   └── {sidebar,topbar,kpi-card,health-heatmap}.tsx
│   ├── lib/{api-client,auth,utils}.ts
│   ├── i18n/{request.ts,messages/{es,en}.json}
│   ├── types/api.ts
│   └── styles/globals.css
├── next.config.mjs
├── tailwind.config.ts
├── tsconfig.json
└── package.json
```

## Autenticación

Better Auth expone su handler en `app/api/auth/[...all]/route.ts`. Si
`DATABASE_URL` no está configurado, se usa un adaptador en memoria (MVP / dev).

Para producción conecta el mismo cluster de Postgres del backend con un schema
dedicado `auth`:

```bash
DATABASE_URL=postgres://user:pass@host:5432/streaming?options=-c%20search_path%3Dauth
```

## shadcn/ui canary

Los componentes de `src/components/ui/` son implementaciones mínimas compatibles
con la convención de `shadcn/ui`. Para traerlos directamente del registry usa:

```bash
npx shadcn@canary init   # sólo la primera vez
npx shadcn@canary add button card sheet skeleton badge table sidebar
```

y sustituye los existentes si necesitas comportamiento extra.
