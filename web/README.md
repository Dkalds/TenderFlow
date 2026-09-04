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
├── test/                   # Setup de Vitest (los e2e están en web/e2e/)
└── proxy.ts                # Proxy de borde (sesión + CSP). Se llamaba
                            # middleware.ts hasta Next 16.
```

Qué páginas son públicas —qué sirve el proxy sin sesión, qué permite robots.txt
y qué anuncia el sitemap— se declara una sola vez en `src/lib/rutas-publicas.ts`.

## Capturas de la landing

Las imágenes del producto que enseña la portada se regeneran con el stack
levantado (Postgres sembrado + API + `npm run dev`):

```bash
npm run capturas:landing
```

Escriben sobre `src/app/(publico)/_assets/`. Revisar el resultado antes de
commitear: lo que se publica es el escaparate del producto.

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

## Variables de entorno

Las del frontend viven en [`.env.example`](.env.example), con su explicación
una a una. Dos cosas que se olvidan con facilidad:

- **`NEXT_PUBLIC_*` se hornea en el build.** Cambiar el valor en Vercel no
  surte efecto hasta un redespliegue sin caché de build.
- **`API_BASE_URL` es obligatoria en producción.** `next.config.ts` rompe el
  build a propósito si falta, para no publicar una web sin datos.

El guard de paridad de entorno (`make check-env-parity`) solo cubre el backend
—compara `config/settings.py`, el `.env.example` de la raíz y `render.yaml`—,
así que las de aquí no las verifica nadie automáticamente: al añadir una,
documentarla en ese fichero es el único paso que evita que se convierta en una
variable fantasma.
