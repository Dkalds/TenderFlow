<!-- BEGIN:nextjs-agent-rules -->

# This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` (resolved from this file's directory; in monorepos the `next` package may not be visible from the repo root) before writing any code. Heed deprecation notices.

This block is written and re-added by `next dev` — verify at `node_modules/next/dist/server/lib/generate-agent-files.js`. Removing it from a diff only re-creates the uncommitted change; committing it with your work keeps the tree clean.

<!-- END:nextjs-agent-rules -->

# Integridad analítica del frontend (ADR-014, extensión de §3.8)

**El frontend no fabrica datos. El backend es la única fuente de verdad
analítica.** Detalle completo, anti-patrones y checklist en
[`docs/frontend-data-invariants.md`](../docs/frontend-data-invariants.md).

1. **No fabriques analítica.** Cross-tabs, grafos, agregados, totales y series
   temporales se calculan en **backend** sobre el dataset completo. El frontend
   renderiza; nunca deriva granularidad/relaciones/totales que el endpoint no dio.
   Si un valor es estimado, etiquétalo o ocúltalo — no lo presentes como real.
2. **El estado de usuario es server-side.** Reglas/alertas/destacados/vistas
   guardadas persisten en servidor; `localStorage` solo caché o migración one-shot.
3. **Sin hardcode que el backend/entorno deben proveer.** Listas (flags, usuarios),
   URLs (Grafana) y datos vienen de API/config. Prohibido `MOCK_*`/`LOCAL_*`/
   `localhost` en datos renderizados.

Verificado por `make check-frontend-invariants` (`scripts/check_frontend_invariants.py
--strict`). **Bloqueante desde 2026-07-28**, en local y en CI: un hallazgo nuevo
se corrige o se justifica en su línea con `fdi-allow:<categoria>`.

# Estado UX/UI

Diagnóstico crítico del frontend, con lo ya corregido y el roadmap de lo que
queda: [`docs/UX_AUDIT.md`](../docs/UX_AUDIT.md). Antes de rediseñar navegación,
cabeceras o formato de datos, leelo — varias de esas piezas ya tienen una
decisión tomada y un test que la fija.

# Motion (Emil Kowalski design engineering)

Tokens de easing, duraciones por tipo de elemento, primitivos enter/exit,
qué no animar nunca y por qué `motion`/Framer Motion salió del bundle:
[`docs/frontend-motion.md`](../docs/frontend-motion.md). Antes de tocar
cualquier animación, revisar ese documento y las skills `emil-design-eng` /
`review-animations` / `apple-design` (instaladas en los dos árboles: Claude Code
las carga de `.claude/skills/`, el resto de herramientas de `.agents/skills/`).

# Prefetch en servidor con hidratación (S7.1)

Las pantallas del dashboard son `"use client"`, pero su primer dato puede
pedirse en servidor y llegar hidratado al `QueryClient` del navegador. Patrón
de referencia: `resumen` (en `page.tsx`, porque sus consultas dependen del
ámbito de la URL) y `radar` (en `layout.tsx`, porque las suyas no). Piezas:
`web/src/lib/server-prefetch.ts` (reglas y límites),
`web/src/components/prefetch-servidor.tsx` y un módulo `_lib/prefetch` por ruta con
sus consultas.

1. **La clave sale de los mismos módulos puros que usa el hook**
   (`web/src/lib/filtered-query.ts`, `web/src/lib/filter-params.ts` y
   `web/src/lib/query-keys.ts`),
   nunca escrita a mano, y un test de paridad por ruta monta el hook real y
   comprueba que cachea bajo esa clave. Una clave distinta se paga dos veces.
2. **Nada que dependa de la organización activa**: vive en `localStorage` y el
   servidor no la ve. Prefetchearla daría un HTML distinto del primer render
   del cliente para quien eligió otra organización.
3. **El prefetch nunca bloquea ni rompe**: presupuesto por consulta, y lo que
   falla no se hidrata, así que la pantalla cae al comportamiento de siempre.
4. **Pocas consultas por ruta**: salen de la IP del servidor de Next y cuentan
   contra el rate-limit por IP de la API.

Para extenderlo a otra ruta: su módulo `_lib/prefetch`, la página (o el layout, si
no depende de la URL) envuelta en `PrefetchServidor`, y su test de paridad.

Los providers, el `Toaster` y el nonce de la CSP de las tres superficies con
sesión (dashboard, login y restablecer contraseña) se montan en
`web/src/components/layout/superficie-privada.tsx`; ningún layout los monta a mano.
