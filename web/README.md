# TenderFlow — Web frontend

Frontend Next.js 16 (App Router) de TenderFlow: dashboard analítico, búsqueda,
watchlist, competidores y administración. Consume exclusivamente la API REST
en `api/` — no accede a `db.*` ni a la capa Python de servicios directamente
(invariante, ver [`AGENTS.md`](AGENTS.md) §3.8 en la raíz del repo).

## Desarrollo

```bash
npm install
npm run dev          # http://localhost:3000, requiere la API en :8080 (make api)
```

O desde la raíz del repo: `make web-dev`.

## Cliente API tipado (OpenAPI)

`src/generated/api.d.ts` se genera a partir del schema OpenAPI de la API
FastAPI — nunca se edita a mano.

```bash
npm run codegen        # requiere la API corriendo en :8080
npm run codegen:file   # genera desde ../api/openapi.json (offline)
npm run codegen:best-effort  # intenta :8080, si falla usa el archivo (usado en `build`)
```

Desde la raíz: `make web-codegen`, o `make openapi` (exporta el JSON offline +
regenera el cliente en un solo paso).

## Estructura

```
src/
├── app/                    # App Router
│   ├── (dashboard)/        # Rutas autenticadas: resumen, pipeline-alertas,
│   │                       #   competidores, tendencias, empresas, organos,
│   │                       #   investigador, geografia, clusters, utes,
│   │                       #   mi-watchlist, administracion, ...
│   └── login/              # Login (password + Google OAuth)
├── components/             # Componentes reutilizables
│   └── ui/                 # Primitivos UI (Radix + shadcn-style)
├── hooks/                  # Hooks de datos (TanStack Query)
├── lib/                    # API client, filtros nuqs, utilidades (ask-stream, etc.)
├── generated/              # api.d.ts generado desde OpenAPI (no editar a mano)
├── test/                   # Tests e2e (Playwright)
└── middleware.ts           # Middleware de Next.js (auth/redirects)
```

## Tests

```bash
npm run test            # Vitest (unit/componentes)
npm run test:coverage   # con cobertura — thresholds en vitest.config.ts
npm run test:e2e        # Playwright
npm run test:e2e:ui     # Playwright con UI
```

Equivalentes desde la raíz: `make web-test-e2e`, `make web-test-e2e-ui`.

## Calidad de código

```bash
npm run lint        # ESLint
npm run typecheck   # tsc --noEmit
npm run format      # Prettier
```

Equivalentes desde la raíz: `make web-lint`, `make web-typecheck`.

## Invariantes del frontend

Dos documentos son de lectura obligatoria antes de tocar analítica o
animaciones — están enlazados también desde `AGENTS.md` de este directorio:

- [`../docs/frontend-data-invariants.md`](../docs/frontend-data-invariants.md)
  (ADR-014): el frontend no fabrica datos analíticos — cross-tabs, agregados,
  totales y series temporales se calculan en backend sobre el dataset
  completo. Verificado por `python scripts/check_frontend_invariants.py`
  (modo aviso).
- [`../docs/frontend-motion.md`](../docs/frontend-motion.md): tokens de
  easing/duración, primitivos enter/exit y qué no animar nunca.

## Despliegue

En Docker, el build usa `../docker/Dockerfile.web` (ver `docker-compose.yml`
en la raíz). El build de producción (`npm run build`) corre
`codegen:best-effort` antes de `next build`, así que no requiere que la API
esté disponible para compilar.
