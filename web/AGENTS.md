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
de referencia: `resumen` (con el ámbito de la URL) y `radar` (sin él); en los
dos, una `page.tsx` de servidor envuelve la vista cliente. Piezas:
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
3. **El prefetch nunca rompe y retiene poco**: el render lo espera, así que
   cada consulta tiene un presupuesto corto (`PRESUPUESTO_PREFETCH_MS`, pensado
   para funciones en `fra1`, junto a la API), y lo que falla o no llega a tiempo
   no se hidrata: la pantalla cae al comportamiento de siempre y el hook lo pide
   desde el navegador. Las consultas pendientes no se deshidratan: con
   `useQuery` desajustarían la hidratación (el porqué, en `server-prefetch.ts`).
4. **Pocas consultas por ruta**: salen de la IP del servidor de Next y cuentan
   contra el rate-limit por IP de la API.

Para extenderlo a otra ruta: su módulo `_lib/prefetch`, la página envuelta en
`PrefetchServidor`, y su test de paridad. **En la página, no en el layout**,
aunque las consultas no dependan de la URL: el `loading.tsx` de un segmento
envuelve su página pero no su layout, así que un `await` en el layout deja la
navegación en el esqueleto genérico del padre; y si el segmento tiene
`loading.tsx`, cada prefetch de un `<Link>` —el rail enlaza todos los
espacios— ejecuta el layout y sus consultas. Radar lo hizo en el layout hasta
2026-09 y por eso no tenía `loading.tsx` propio; hoy vive en su página, como
en Resumen.

Los providers, el `Toaster` y el nonce de la CSP de las tres superficies con
sesión (dashboard, login y restablecer contraseña) se montan en
`web/src/components/layout/superficie-privada.tsx`; ningún layout los monta a mano.
