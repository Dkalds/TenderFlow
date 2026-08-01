<!-- BEGIN:nextjs-agent-rules -->
# This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` before writing any code. Heed deprecation notices.
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
