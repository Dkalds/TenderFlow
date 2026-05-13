"""M8 — Timeline vertical para historial de cambios de una licitación."""

from __future__ import annotations

import json
from datetime import datetime

import streamlit as st

from db.database import get_history


_TIMELINE_CSS = """
<style>
.tl-container{position:relative;padding-left:24px;margin:0.5rem 0}
.tl-container::before{content:'';position:absolute;left:8px;top:0;bottom:0;width:2px;background:#cbd5e1}
.tl-item{position:relative;margin-bottom:1rem;padding-left:12px}
.tl-item::before{content:'';position:absolute;left:-20px;top:4px;width:10px;height:10px;
  border-radius:50%;background:var(--tl-dot,#3b82f6);border:2px solid #fff;z-index:1}
.tl-date{font-size:0.75rem;color:#64748b}
.tl-body{font-size:0.85rem;margin-top:2px}
.tl-change{color:#059669;font-weight:500}
</style>
"""


def timeline_popover(id_externo: str, *, key: str = "") -> None:
    """Render a popover button that shows the change history timeline."""
    with st.popover("📅 Historial", use_container_width=True):
        try:
            history = get_history(id_externo, limit=20)
        except Exception:
            st.caption("No se pudo cargar el historial.")
            return

        if not history:
            st.caption("Sin historial de cambios registrado.")
            return

        parts = [_TIMELINE_CSS, '<div class="tl-container">']
        for entry in history:
            ts_raw = entry.get("captured_at", "")
            try:
                ts = datetime.fromisoformat(str(ts_raw)).strftime("%d/%m/%Y %H:%M")
            except Exception:
                ts = str(ts_raw)[:16]

            changed = entry.get("changed_fields") or ""
            if changed:
                try:
                    fields = json.loads(changed) if isinstance(changed, str) else changed
                    if isinstance(fields, list):
                        changed_txt = ", ".join(str(f) for f in fields[:5])
                    elif isinstance(fields, dict):
                        changed_txt = ", ".join(f"{k}: {v}" for k, v in list(fields.items())[:5])
                    else:
                        changed_txt = str(fields)[:120]
                except Exception:
                    changed_txt = str(changed)[:120]
            else:
                changed_txt = ""

            source = entry.get("source", "sync")
            dot_color = "#3b82f6" if source == "sync" else "#f59e0b"

            parts.append(
                f'<div class="tl-item" style="--tl-dot:{dot_color}">'
                f'<div class="tl-date">{ts} · {source}</div>'
            )
            if changed_txt:
                parts.append(f'<div class="tl-body"><span class="tl-change">{changed_txt}</span></div>')
            parts.append("</div>")

        parts.append("</div>")
        st.markdown("".join(parts), unsafe_allow_html=True)
