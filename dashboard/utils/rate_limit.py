"""Rate limiting por sesión basado en session_state.

Diseñado como complemento defensivo a la caché de Streamlit: detecta sesiones
que invocan operaciones costosas (carga de DataFrame, invalidación de caché,
queries pesadas) más rápido de lo razonable y aplica throttling.

Implementación simple basada en una ventana deslizante de timestamps por
sesión, almacenada en ``st.session_state``.
"""

from __future__ import annotations

import time
from collections import deque
from typing import Any

import streamlit as st

from observability.logging import get_logger

log = get_logger(__name__)


def check_rate_limit(
    key: str,
    *,
    max_calls: int = 30,
    window_seconds: float = 60.0,
) -> bool:
    """Devuelve ``True`` si la operación está dentro del límite, ``False`` si lo excede.

    Mantiene una deque de timestamps por ``key`` en ``st.session_state``.
    Las llamadas más antiguas que ``window_seconds`` se descartan.

    Args:
        key: Identificador de la operación (e.g. ``"load_dataframe"``).
        max_calls: Máximo de invocaciones permitidas dentro de la ventana.
        window_seconds: Tamaño de la ventana en segundos.

    Returns:
        ``True`` si se permite la operación, ``False`` si se ha excedido el límite.
    """
    state_key = f"_rl_{key}"
    now = time.monotonic()
    cutoff = now - window_seconds

    timestamps = st.session_state.get(state_key)
    if timestamps is None:
        timestamps = deque(maxlen=max_calls + 1)
        st.session_state[state_key] = timestamps

    # Purgar timestamps fuera de la ventana
    while timestamps and timestamps[0] < cutoff:
        timestamps.popleft()

    if len(timestamps) >= max_calls:
        log.warning(
            "rate_limit_exceeded",
            key=key,
            calls_in_window=len(timestamps),
            max_calls=max_calls,
            window_seconds=window_seconds,
        )
        return False

    timestamps.append(now)
    return True


def throttled(
    key: str,
    *,
    max_calls: int = 30,
    window_seconds: float = 60.0,
    warn_message: str | None = None,
) -> bool:
    """Versión interactiva: si excede el límite, muestra warning en UI y retorna ``False``.

    Returns:
        ``True`` si la operación puede continuar, ``False`` si se debe abortar.
    """
    if check_rate_limit(key, max_calls=max_calls, window_seconds=window_seconds):
        return True
    msg = warn_message or (
        f"Demasiadas operaciones en poco tiempo ({max_calls} en "
        f"{int(window_seconds)}s). Espera unos segundos antes de continuar."
    )
    try:
        st.warning(msg, icon="⏱️")
    except Exception:  # pragma: no cover — entorno sin contexto Streamlit
        pass
    return False


def reset(key: str) -> None:
    """Resetea el contador para una clave (útil en tests o tras autenticación)."""
    state_key = f"_rl_{key}"
    if state_key in st.session_state:
        del st.session_state[state_key]


# ── API helpers para uso desde data_loader ────────────────────────────────


def get_call_count(key: str) -> int:
    """Devuelve cuántas llamadas hay actualmente en la ventana (para tests)."""
    timestamps: Any = st.session_state.get(f"_rl_{key}")
    return len(timestamps) if timestamps is not None else 0
