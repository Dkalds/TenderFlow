---
id: ADR-002
title: "Streamlit vs FastAPI + React"
status: accepted
date: 2024-01-01
deciders: "Daniel Kalitovics"
tags: [adr]
---

# ADR-002: Streamlit vs FastAPI + React

**Status:** Accepted  
**Date:** 2024-01-01  
**Deciders:** Daniel Kalitovics

## Context

The dashboard needed to present scraped licitaciones data with interactive filters,
KPI cards, charts, and search. The choice was between a Streamlit single-script
application and a more traditional FastAPI backend + React SPA.

## Decision

Use **Streamlit** for the dashboard.

## Rationale

- **Speed of iteration:** Streamlit lets a single developer build a functional,
  interactive dashboard in hours rather than weeks.
- **Python-native:** All data manipulation (Pandas, Plotly) lives in the same
  process as the UI — no serialization layer needed.
- **No JS build toolchain:** Eliminates npm, webpack, TypeScript compilation,
  and a separate deployment unit.
- **Sufficient for the use case:** The dashboard serves a small internal team;
  Streamlit's execution model (full-script re-run on interaction) is acceptable
  at this scale.

## Consequences

- **Positive:** Single language, fast prototyping, built-in state management via
  `st.session_state`, OAuth handled with `st.experimental_get_query_params`.
- **Negative:**
  - Streamlit's re-run model makes fine-grained caching complex; `@st.cache_data`
    caches per-session but RAM usage grows with concurrent users.
  - Multi-page routing requires a custom router (`dashboard/router.py`) — Streamlit's
    native multi-page file-based routing is insufficient for our dynamic navigation.
  - No REST API: external integrations require adding one separately.
  - Harder to write unit tests for pages (Streamlit context required).
- **Migration path:** If concurrent users exceed ~20 or a REST API is needed,
  migrate the data-access layer to a FastAPI service and keep Streamlit as a thin
  UI layer calling the API, or replace the UI entirely with React.

## Alternatives Considered

| Alternative | Reason rejected |
|-------------|----------------|
| FastAPI + React | High upfront cost; disproportionate for a single-developer internal tool |
| Dash (Plotly) | Similar execution model to Streamlit but less ergonomic Python API |
| Panel | Less community traction; fewer integrations |
| Gradio | Designed for ML demos, not data dashboards |
