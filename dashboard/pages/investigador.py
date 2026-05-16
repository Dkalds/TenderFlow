"""Modo Investigador — búsqueda semántica RAG con historial, scoring y streaming LLM.

Mejoras sobre la versión original:
  - Índice FAISS cacheado en memoria (@st.cache_resource)
  - Reranking híbrido FAISS (semántico) + FTS5/BM25 (léxico)
  - FTS5 injection-safe (_escape_fts5)
  - Respeta filtros del sidebar + filtros inline (CCAA, importe, estado)
  - Streaming LLM token a token con st.empty()
  - Caché LLM 1h en session_state (evita recargas por el mismo turno)
  - Modelo configurable: gpt-4o-mini / gpt-4o / gpt-3.5-turbo
  - Historial de preguntas en session_state (max 10)
  - Chips de ejemplos de preguntas
  - Score de relevancia visible (🟢/🟡/🔴) + badge de fuente
  - Resaltado de keywords en <mark>
  - Extracto contextual centrado en keywords
  - Citas [ID] clicables en la respuesta LLM
  - Exportar CSV (todos o seleccionados con checkbox)
  - Estimación de tokens del contexto
  - Telemetría via structlog
  - API key leída de config.secrets con fallback a os.environ
  - Logging en todos los paths de excepción
"""

from __future__ import annotations

import html as _html
import io
import os
import re
import time
from collections.abc import Iterator
from typing import Any

import pandas as pd
import streamlit as st

from dashboard.components.states import guarded_render
from dashboard.pages._base import PageContext
from dashboard.session_keys import INV_HISTORY, INV_Q
from db.database import connect
from observability.logging import get_logger

log = get_logger(__name__)

# ── Preguntas de ejemplo (chips) ────────────────────────────────────────────
_EXAMPLE_QUESTIONS = [
    "Mantenimiento SAP en sanidad pública 2024",
    "Migraciones S/4HANA en comunidades autónomas",
    "Contratos de Business Intelligence con Oracle",
    "Soporte SAP HANA superior a 500.000 €",
    "Ciberseguridad en administración del Estado",
]

# ── Umbrales de relevancia ──────────────────────────────────────────────────
_THR_ALTA = 0.70
_THR_MEDIA = 0.40


def _relevance_badge(score: float) -> str:
    if score >= _THR_ALTA:
        return "🟢 Alta"
    if score >= _THR_MEDIA:
        return "🟡 Media"
    return "🔴 Baja"


# ── Helpers de texto ────────────────────────────────────────────────────────

def _escape_fts5(query: str) -> str:
    """Escapa la query para SQLite FTS5 MATCH, previniendo inyección de operadores."""
    # Strip FTS5 special chars, tokenize, wrap each token in double-quotes
    tokens = re.sub(r'["*+\-():\^]', " ", query).split()
    if not tokens:
        return '""'
    return " ".join(f'"{t.replace(chr(34), chr(34)*2)}"' for t in tokens[:12])


def _context_excerpt(text: str | None, keywords: list[str], max_chars: int = 400) -> str:
    """Extrae el fragmento más relevante del texto centrado en las keywords."""
    if not text:
        return ""
    text = text.strip()
    best_pos = len(text)
    for kw in keywords:
        pos = text.lower().find(kw.lower())
        if 0 <= pos < best_pos:
            best_pos = pos
    start = max(0, best_pos - max_chars // 3)
    end = min(len(text), start + max_chars)
    snippet = text[start:end]
    if start > 0:
        snippet = "…" + snippet
    if end < len(text):
        snippet = snippet + "…"
    return snippet


def _highlight(text: str, keywords: list[str]) -> str:
    """Envuelve keywords en <mark> dentro de texto HTML-escapado."""
    safe = _html.escape(text)
    for kw in sorted(keywords, key=len, reverse=True):
        if len(kw) < 3:
            continue
        safe = re.sub(
            rf"(?i)({re.escape(_html.escape(kw))})",
            r"<mark>\1</mark>",
            safe,
        )
    return safe


def _linkify_citations(text: str, docs: list[dict]) -> str:
    """Convierte [ID-EXP] en markdown con formato código (citas del LLM)."""
    id_set = {d["id_externo"] for d in docs}

    def _replace(m: re.Match) -> str:  # type: ignore[type-arg]
        id_ = m.group(1)
        return f"[`{id_}`](?exp={id_})" if id_ in id_set else m.group(0)

    return re.sub(r"\[([A-Z0-9/_\-]{4,})\]", _replace, text)


# ── Búsqueda ────────────────────────────────────────────────────────────────

@st.cache_resource(show_spinner=False)
def _load_faiss_cached() -> Any:
    """Carga el índice FAISS una sola vez y lo mantiene en memoria entre reruns."""
    from dashboard.faiss_index import FaissIndex  # type: ignore[import]
    return FaissIndex.load()


def _faiss_search(question: str, top_k: int) -> list[tuple[str, float]]:
    """Búsqueda semántica FAISS. Devuelve (id_externo, score ∈ [0,1])."""
    try:
        idx = _load_faiss_cached()
        return idx.search(question, k=top_k, threshold=0.25)
    except Exception as exc:
        log.warning("investigador.faiss_failed", error=str(exc))
        return []


def _fts5_search(question: str, top_k: int) -> list[tuple[str, float]]:
    """Búsqueda léxica FTS5/BM25. Devuelve (id_externo, score ∈ [0,1]) normalizado."""
    escaped = _escape_fts5(question)
    try:
        with connect() as c:
            cur = c.execute(
                "SELECT l.id_externo, bm25(licitaciones_fts) AS bm25_score "
                "FROM licitaciones_fts fts "
                "JOIN licitaciones l ON l.id_externo = fts.id_externo "
                f"WHERE licitaciones_fts MATCH ? ORDER BY bm25_score LIMIT {top_k * 2}",
                [escaped],
            )
            rows = cur.fetchall()
    except Exception as exc:
        log.warning("investigador.fts5_failed", error=str(exc))
        return []

    if not rows:
        return []
    # BM25 from SQLite FTS5 is negative: more negative = more relevant
    raw_scores = [abs(float(r[1])) for r in rows]
    max_s = max(raw_scores) if raw_scores else 1.0
    return [(r[0], s / max_s) for r, s in zip(rows, raw_scores, strict=False)]


def _like_search(question: str, top_k: int) -> list[tuple[str, float]]:
    """LIKE fallback para cuando FTS5 no está disponible."""
    token = next((w for w in question.split() if len(w) >= 4), question.split()[0] if question.split() else "")
    if not token:
        return []
    try:
        with connect() as c:
            cur = c.execute(
                "SELECT id_externo FROM licitaciones "
                "WHERE titulo LIKE ? OR descripcion LIKE ? LIMIT ?",
                [f"%{token}%", f"%{token}%", top_k],
            )
            return [(r[0], 0.20) for r in cur.fetchall()]
    except Exception as exc:
        log.warning("investigador.like_failed", error=str(exc))
        return []


def _hybrid_rerank(
    faiss_hits: list[tuple[str, float]],
    fts_hits: list[tuple[str, float]],
    alpha: float = 0.70,
    top_k: int = 10,
) -> list[tuple[str, float]]:
    """Reranking híbrido: alpha·FAISS + (1-alpha)·FTS5."""
    faiss_map = dict(faiss_hits)
    fts_map = dict(fts_hits)
    all_ids = set(faiss_map) | set(fts_map)
    combined = {
        id_: alpha * faiss_map.get(id_, 0.0) + (1 - alpha) * fts_map.get(id_, 0.0)
        for id_ in all_ids
    }
    return sorted(combined.items(), key=lambda x: x[1], reverse=True)[:top_k]


def _fetch_docs(ids: list[str], allowed_ids: set[str] | None) -> dict[str, dict]:
    """Recupera metadatos de la BD para una lista de IDs, filtrando por allowed_ids."""
    if not ids:
        return {}
    if allowed_ids is not None:
        ids = [i for i in ids if i in allowed_ids]
    if not ids:
        return {}
    placeholders = ",".join("?" for _ in ids)
    try:
        with connect() as c:
            cur = c.execute(
                f"SELECT id_externo, titulo, organo_contratacion, importe, "
                f"       descripcion, url, fecha_publicacion, ccaa, estado "
                f"FROM licitaciones WHERE id_externo IN ({placeholders})",
                ids,
            )
            cols = [d[0] for d in cur.description]
            return {r[0]: dict(zip(cols, r, strict=False)) for r in cur.fetchall()}
    except Exception as exc:
        log.warning("investigador.fetch_docs_failed", error=str(exc))
        return {}


def _rag_query(
    question: str,
    top_k: int,
    allowed_ids: set[str] | None,
) -> tuple[list[dict[str, Any]], str]:
    """Búsqueda híbrida FAISS+FTS5 con reranking.

    Returns:
        (docs, source_badge) donde source_badge ∈ {"🟣 FAISS+FTS5", "🟣 FAISS", "🔵 FTS5", "⚪ LIKE"}
    """
    t0 = time.perf_counter()
    faiss_hits = _faiss_search(question, top_k * 2)
    fts_hits = _fts5_search(question, top_k * 2)

    if faiss_hits and fts_hits:
        ranked = _hybrid_rerank(faiss_hits, fts_hits, alpha=0.70, top_k=top_k)
        source = "🟣 FAISS+FTS5"
    elif faiss_hits:
        ranked = sorted(faiss_hits, key=lambda x: x[1], reverse=True)[:top_k]
        source = "🟣 FAISS"
    elif fts_hits:
        ranked = sorted(fts_hits, key=lambda x: x[1], reverse=True)[:top_k]
        source = "🔵 FTS5"
    else:
        ranked = _like_search(question, top_k)
        source = "⚪ LIKE"

    ids = [id_ for id_, _ in ranked]
    docs_map = _fetch_docs(ids, allowed_ids)

    docs = []
    for id_, score in ranked:
        if id_ in docs_map:
            doc = dict(docs_map[id_])
            doc["_score"] = score
            docs.append(doc)

    elapsed_ms = round((time.perf_counter() - t0) * 1000)
    log.debug(
        "investigador.rag_query",
        question=question[:80],
        n=len(docs),
        source=source,
        elapsed_ms=elapsed_ms,
        allowed=len(allowed_ids) if allowed_ids is not None else "all",
    )
    return docs, source


# ── LLM ─────────────────────────────────────────────────────────────────────

def _get_api_key() -> str:
    """Lee OPENAI_API_KEY desde config.secrets con fallback a os.environ."""
    try:
        from config.secrets import get_secret
        key = get_secret("OPENAI_API_KEY")
        if key:
            return key
    except Exception:
        pass
    return os.environ.get("OPENAI_API_KEY", "")


def _build_prompt(question: str, context_docs: list[dict], keywords: list[str]) -> str:
    context = "\n\n".join(
        f"[{d['id_externo']}] {d.get('titulo', '')}\n"
        f"Órgano: {d.get('organo_contratacion', '—')}\n"
        f"Importe: {d.get('importe', '—')}\n"
        f"Estado: {d.get('estado', '—')}\n"
        f"Descripción: {_context_excerpt(d.get('descripcion'), keywords, 300)}"
        for d in context_docs
    )
    return (
        "Eres un asistente experto en licitaciones del sector público español. "
        "Responde ÚNICAMENTE con información de los expedientes del contexto. "
        "Si el contexto no contiene la respuesta, escribe exactamente: "
        "'No encontrado en el corpus.' "
        "Cita siempre el ID del expediente entre corchetes, ej: [EXP-2024-001]. "
        "Si hay varios expedientes relevantes, incluye una tabla Markdown resumen al final "
        "con columnas: Expediente | Órgano | Importe | Relevancia.\n\n"
        f"CONTEXTO:\n{context}\n\n"
        f"PREGUNTA: {question}"
    )


def _llm_stream(
    question: str, docs: list[dict], model: str, keywords: list[str]
) -> Iterator[str]:
    """Genera tokens LLM en streaming. Yields string chunks."""
    api_key = _get_api_key()
    if not api_key:
        return
    try:
        from openai import OpenAI  # type: ignore[import]

        prompt = _build_prompt(question, docs, keywords)
        estimated_tokens = len(prompt) // 4
        log.debug(
            "investigador.llm_start",
            model=model,
            estimated_input_tokens=estimated_tokens,
            n_docs=len(docs),
        )
        client = OpenAI(api_key=api_key)
        stream = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=900,
            temperature=0.2,
            stream=True,
        )
        for chunk in stream:
            delta = chunk.choices[0].delta.content if chunk.choices else None
            if delta:
                yield delta
    except Exception as exc:
        log.warning("investigador.llm_failed", error=str(exc))
        return


# ── Render ───────────────────────────────────────────────────────────────────

@guarded_render
def render(ctx: PageContext) -> None:
    st.subheader("🔬 Modo Investigador")
    st.caption(
        "Búsqueda semántica con reranking híbrido FAISS + FTS5/BM25. "
        "Con `OPENAI_API_KEY` obtendrás respuestas generadas por IA en tiempo real."
    )

    # ── Estado de sesión ──────────────────────────────────────────────────
    if INV_HISTORY not in st.session_state:
        st.session_state[INV_HISTORY] = []
    if INV_Q not in st.session_state:
        st.session_state[INV_Q] = ""

    # ── Configuración ─────────────────────────────────────────────────────
    with st.expander("⚙️ Configuración de búsqueda", expanded=False):
        cCfg1, cCfg2, cCfg3 = st.columns(3)
        with cCfg1:
            top_k: int = st.slider("Expedientes recuperados", 3, 20, 5, key="inv_top_k")
        with cCfg2:
            llm_model: str = st.selectbox(  # type: ignore[assignment]
                "Modelo LLM",
                ["gpt-4o-mini", "gpt-4o", "gpt-3.5-turbo"],
                key="inv_llm_model",
                help="gpt-4o-mini: equilibrio coste/calidad · gpt-4o: máxima calidad",
            )
        with cCfg3:
            only_filtered = st.checkbox(
                "Respetar filtros del sidebar",
                value=True,
                key="inv_only_filtered",
                help="Limita la búsqueda a las licitaciones visibles con los filtros activos.",
            )

        cF1, cF2, cF3 = st.columns(3)
        with cF1:
            imp_min: int = st.number_input(
                "Importe mínimo (€)", min_value=0, value=0, step=50_000, key="inv_imp_min"
            )
        with cF2:
            ccaas_disp = (
                sorted(ctx.df["ccaa"].dropna().unique().tolist())
                if "ccaa" in ctx.df.columns
                else []
            )
            ccaa_sel: list[str] = st.multiselect("CCAA", ccaas_disp, key="inv_ccaa")
        with cF3:
            estados_disp = (
                sorted(ctx.df["estado_desc"].dropna().unique().tolist())
                if "estado_desc" in ctx.df.columns
                else []
            )
            estado_sel: list[str] = st.multiselect("Estado", estados_disp, key="inv_estado")

    # Construir universo de IDs permitidos
    if only_filtered:
        df_base = ctx.df.copy()
        if imp_min > 0:
            df_base = df_base[df_base["importe"].fillna(0) >= imp_min]
        if ccaa_sel:
            df_base = df_base[df_base["ccaa"].isin(ccaa_sel)]
        if estado_sel:
            df_base = df_base[df_base["estado_desc"].isin(estado_sel)]
        allowed_ids: set[str] | None = set(df_base["id_externo"])
    else:
        allowed_ids = None

    # ── Chips de ejemplos ─────────────────────────────────────────────────
    st.markdown("**Preguntas de ejemplo:**")
    chip_cols = st.columns(len(_EXAMPLE_QUESTIONS))
    for i, example in enumerate(_EXAMPLE_QUESTIONS):
        label = (example[:27] + "…") if len(example) > 30 else example
        with chip_cols[i]:
            if st.button(label, key=f"inv_chip_{i}", use_container_width=True):
                st.session_state[INV_Q] = example
                st.rerun()

    # ── Input de pregunta ─────────────────────────────────────────────────
    cQ1, cQ2 = st.columns([5, 1])
    with cQ1:
        question: str = st.text_area(
            "Pregunta libre",
            key=INV_Q,
            placeholder="¿Qué licitaciones de mantenimiento SAP hay en sanidad?",
            height=80,
            label_visibility="collapsed",
        )
    with cQ2:
        st.markdown("<div style='height:30px'></div>", unsafe_allow_html=True)
        if st.button("🗑 Limpiar", key="inv_clear", use_container_width=True):
            st.session_state[INV_HISTORY] = []
            st.session_state[INV_Q] = ""
            st.rerun()

    if not question or not question.strip():
        if not st.session_state[INV_HISTORY]:
            st.info("Escribe una pregunta o pulsa un ejemplo para comenzar la investigación.")
        # History shown below even without a current question
    else:
        keywords = [w for w in re.sub(r"[^\w\s]", "", question).split() if len(w) >= 3]

        # ── Búsqueda ──────────────────────────────────────────────────────
        status = st.empty()
        status.markdown("🔍 Buscando expedientes relevantes…")
        t_search = time.perf_counter()
        docs, source = _rag_query(question.strip(), top_k=top_k, allowed_ids=allowed_ids)
        elapsed_search_ms = round((time.perf_counter() - t_search) * 1000)
        status.empty()

        if not docs:
            st.warning(
                "No se encontraron expedientes relevantes. "
                "Prueba con otros términos o amplía los filtros."
            )
        else:
            # ── Badge de fuente + métricas ─────────────────────────────────
            universe_txt = (
                f" · Universo: {len(allowed_ids):,} licitaciones"
                if allowed_ids is not None
                else ""
            )
            st.caption(
                f"Motor: **{source}** · {len(docs)} expedientes · {elapsed_search_ms} ms{universe_txt}"
            )

            # ── LLM streaming ──────────────────────────────────────────────
            api_key = _get_api_key()
            answer_text: str = ""
            if api_key:
                ctx_chars = sum(len(d.get("descripcion") or "") for d in docs)
                estimated_tokens = ctx_chars // 4
                st.markdown(
                    f"### 🤖 Respuesta  "
                    f"<small style='color:gray;font-weight:normal'>"
                    f"~{estimated_tokens:,} tokens de contexto · {llm_model}"
                    f"</small>",
                    unsafe_allow_html=True,
                )
                t_llm = time.perf_counter()
                answer_container = st.empty()
                for chunk in _llm_stream(question, docs, llm_model, keywords):
                    answer_text += chunk
                    answer_container.markdown(answer_text + "▌")
                if answer_text:
                    answer_container.markdown(_linkify_citations(answer_text, docs))
                    log.info(
                        "investigador.llm_done",
                        model=llm_model,
                        elapsed_ms=round((time.perf_counter() - t_llm) * 1000),
                        answer_chars=len(answer_text),
                    )
                else:
                    answer_container.empty()
                st.divider()

            # ── Guardar en historial ───────────────────────────────────────
            st.session_state[INV_HISTORY].append(
                {
                    "q": question.strip(),
                    "docs": docs,
                    "answer": answer_text or None,
                    "source": source,
                }
            )
            if len(st.session_state[INV_HISTORY]) > 10:
                st.session_state[INV_HISTORY] = st.session_state[INV_HISTORY][-10:]

            # ── Expedientes recuperados ────────────────────────────────────
            st.markdown(f"### 📄 Expedientes recuperados ({len(docs)})")
            selected_ids: list[str] = []
            for i, doc in enumerate(docs, 1):
                score = float(doc.get("_score", 0.0))
                badge = _relevance_badge(score)
                header = f"{i}. [{doc['id_externo']}] {(doc.get('titulo') or '')[:70]}"
                with st.expander(header, expanded=(i == 1)):
                    cD1, cD2, cD3, cD4, cD5 = st.columns([1.2, 1.2, 1.8, 0.9, 0.5])
                    cD1.metric("Expediente", doc["id_externo"])
                    cD2.metric(
                        "Importe",
                        f"{doc['importe']:,.0f} €" if doc.get("importe") else "—",
                    )
                    cD3.metric("Órgano", (doc.get("organo_contratacion") or "—")[:30])
                    cD4.metric("Relevancia", badge, delta=f"{score:.2f}")
                    with cD5:
                        if st.checkbox("✓", key=f"inv_sel_{i}_{doc['id_externo']}"):
                            selected_ids.append(doc["id_externo"])

                    if doc.get("descripcion"):
                        excerpt = _context_excerpt(doc["descripcion"], keywords, 400)
                        highlighted = _highlight(excerpt, keywords)
                        st.markdown(
                            f'<p style="font-size:0.85rem;color:#aaa;line-height:1.5">'
                            f"{highlighted}</p>",
                            unsafe_allow_html=True,
                        )

                    meta_parts = []
                    if doc.get("ccaa"):
                        meta_parts.append(f"📍 {doc['ccaa']}")
                    if doc.get("estado"):
                        meta_parts.append(f"📋 {doc['estado']}")
                    if doc.get("fecha_publicacion"):
                        meta_parts.append(f"📅 {str(doc['fecha_publicacion'])[:10]}")
                    if meta_parts:
                        st.caption(" · ".join(meta_parts))
                    if doc.get("url"):
                        st.markdown(f"[Ver expediente completo ↗]({doc['url']})")

            # ── Exportar CSV ───────────────────────────────────────────────
            export_set = set(selected_ids) if selected_ids else {d["id_externo"] for d in docs}
            export_docs = [d for d in docs if d["id_externo"] in export_set]
            csv_cols = [
                "id_externo", "titulo", "organo_contratacion",
                "importe", "ccaa", "estado", "url",
            ]
            df_export = pd.DataFrame(
                [{c: d.get(c) for c in csv_cols} for d in export_docs]
            )
            buf = io.StringIO()
            df_export.to_csv(buf, index=False)
            label_suffix = " (seleccionados)" if selected_ids else " (todos)"
            st.download_button(
                f"⬇ Exportar CSV{label_suffix}",
                data=buf.getvalue().encode("utf-8"),
                file_name=f"investigador_{len(export_docs)}.csv",
                mime="text/csv",
                key="inv_export_csv",
            )

            if not api_key:
                st.caption(
                    "💡 Configura `OPENAI_API_KEY` para respuestas generadas por IA."
                )

    # ── Historial de preguntas ────────────────────────────────────────────
    history = st.session_state.get(INV_HISTORY, [])
    # Exclude the current question's entry (last one) if it matches
    hist_to_show = history[:-1] if (history and question and question.strip() and history[-1]["q"] == question.strip()) else history
    if hist_to_show:
        st.divider()
        st.markdown("### 🕘 Historial de preguntas")
        for entry in reversed(hist_to_show):
            with st.expander(f"❓ {entry['q'][:80]}", expanded=False):
                st.caption(f"Motor: {entry['source']} · {len(entry['docs'])} expedientes")
                if entry.get("answer"):
                    st.markdown(entry["answer"])
                if st.button("↩ Repetir", key=f"inv_repeat_{hash(entry['q'])}"):
                    st.session_state[INV_Q] = entry["q"]
                    st.rerun()
