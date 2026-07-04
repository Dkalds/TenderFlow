---
adr: "015"
title: Identidad del producto — Tenderflow (plataforma genérica de licitaciones)
date: 2026-07-04
status: accepted
---

## Contexto

El proyecto nació como `licitaciones-sap` con el scoring y el motor de
búsqueda orientados a licitaciones SAP. Tras el RFC 2026-07-04 (scoring
genérico sin tecnología hardcodeada) y la Fase 3 del plan de reducción de
superficie (eliminación de FAISS), la plataforma es válida para cualquier
tipo de pliego y vertical tecnológico.

El nombre `tenderflow` ya estaba declarado en `pyproject.toml` como nombre
del paquete Python (`[project] name = "tenderflow"`). Este ADR oficializa
la alineación del resto del codebase con esa identidad.

## Decisión

- El producto se llama **Tenderflow** — plataforma de análisis e inteligencia
  de licitaciones públicas.
- SAP es un vertical más, gestionado mediante `config/keywords.py` y
  `ML_TECH_GATING_PRACTICES`. No requiere tratamiento especial en el motor
  de scoring ni en el motor de búsqueda.
- Cambios de identidad:
  - `config/constants.USER_AGENT` → `"TenderflowBot/1.0"` (scraping ético).
  - `config/settings.OTEL_SERVICE_NAME` default → `"tenderflow"`.
  - `docker-compose.yml`: contenedores renombrados a `tenderflow-*`.
  - `vercel_app.py` y `tenderflow/__init__.py` eliminados (stub innecesario
    tras la confirmación de que Vercel frontend es el único deployment web).
- Los ADRs, RFCs y changelogs históricos **no se reescriben** — conservan
  la terminología original como registro histórico.
- El repositorio en GitHub puede renombrarse manualmente; `git remote set-url`
  actualiza la URL local. La redirección de GitHub preserva los forks.

## Alternativas consideradas

| Alternativa | Motivo de descarte |
|---|---|
| Mantener `licitaciones-sap` como nombre público | Induce a pensar que es solo para SAP; contradice el scoring genérico |
| Rename completo incluyendo ADRs/RFCs | Reescribir historia del proyecto; coste alto, valor bajo |

## Impacto en invariantes

| Invariante | Impacto |
|---|---|
| §3.5 Pydantic v2 DTOs | Ninguno — no cambian campos de API |
| §3.8 Frontend no fabrica analítica | Ninguno |
| Todos los demás | Ninguno |
