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

Verificado por `python scripts/check_frontend_invariants.py` (modo aviso;
`fdi-allow` por línea para excepciones justificadas).
