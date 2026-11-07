"""Settings del LLM: etiquetado batch, guion de oferta, presupuesto de gasto y timeout de /ask.

Módulo hermano de ``config/settings.py`` (P3 «Los dos módulos-dios»): ``Settings``
hereda de esta clase, así que los nombres de las variables de entorno y el
acceso (``settings.LLM_BUDGET_MODE``) son los de siempre.

Sin ``model_config`` propio, por lo mismo que ``config/settings_resumen.py``.
"""

from __future__ import annotations

from typing import Literal

from pydantic_settings import BaseSettings


class LlmSettings(BaseSettings):
    """Carriles LLM y su presupuesto (``llm/budget.py``)."""

    # ── LLM: etiquetado batch de tecnología sobre la metadata del anuncio ────
    # Categorizar a mano la cola de active learning es inviable por volumen.
    # Este carril clasifica con un LLM leyendo solo el anuncio (sin pliegos),
    # así que cubre todo el universo y no la minoría con documentos. Off por
    # defecto: genera gasto, se activa de forma explícita como PLIEGO_FACTS.
    LLM_TECH_LABELING_ENABLED: bool = False
    # Mantener sincronizado con llm.client.DEFAULT_MODEL (lo comprueba
    # tests/test_llm_client.py): deepseek-v4-pro y deepseek-v4-flash-0731
    # acabaron en 410 (EOL en NVIDIA el 2026-08-07 y el 2026-09-21) y
    # nemotron-3-super en 404 (2026-10-20). El modelo entra en `signal_version`,
    # así que cambiarlo vuelve a etiquetar el corpus desde lo más reciente, a
    # razón de LLM_TECH_LABELING_BATCH por corrida.
    LLM_TECH_LABELING_MODEL: str = "nvidia/nemotron-3-ultra-550b-a55b"
    # Licitaciones clasificadas por corrida. Mismo caveat que PLIEGO_*_BATCH:
    # sin REDIS_URL en el runner, el presupuesto LLM arranca de 0 en cada
    # corrida y el tope real de gasto es este tamaño de lote (~$0.07 por 200).
    LLM_TECH_LABELING_BATCH: int = 200
    # Tope de reloj del lote dentro del cierre de la pasada (#581). El step de
    # cierre de scrape-daily tiene 20 min y el resto de pasos tarda ~5; con el
    # proveedor lento, 200 llamadas con reintentos se comían el step entero.
    # Lo que no cabe queda pendiente para la siguiente corrida.
    LLM_TECH_LABELING_BUDGET_S: int = 600
    # F2.6 — tope de tokens por guion de oferta técnica. Es un tope **por
    # respuesta**, no un presupuesto: el gasto acumulado lo gobierna el
    # `BudgetGuard` de `llm/budget.py`, atado al sujeto por la ruta.
    #
    # 2.500 da para una docena de criterios con sus puntos y sus citas. Subirlo
    # no mejora el guion: lo que produce un guion largo es un pliego con muchos
    # criterios, y por encima de doce la pantalla deja de leerse (por eso
    # `generar_guion` también corta ahí).
    LLM_GUION_MAX_TOKENS: int = 2500
    # Vuelca además las etiquetas seguras a ml_feedback (source='llm_batch'),
    # que es lo que saca la licitación de la cola humana de active learning
    # (su query es un anti-join contra esa tabla). Independiente del flag de
    # arriba: primero se valida la calidad de la señal, después se deja que
    # vacíe la cola. Esas filas NUNCA entrenan al modelo -- ver v80.
    LLM_TECH_FEEDBACK_ENABLED: bool = False
    # Por debajo de esta confianza la licitación se deja para revisión humana:
    # el objetivo es vaciar la cola de lo evidente, no de lo dudoso.
    LLM_TECH_FEEDBACK_MIN_CONF: float = 0.90

    # ── LLM: presupuesto de gasto + timeout (RFC llm-dependencia-gestionada) ──
    # Tope de gasto del proveedor LLM por ventana (USD). <= 0 desactiva el límite.
    LLM_BUDGET_USD_DAILY: float = 5.0
    LLM_BUDGET_USD_MONTHLY: float = 50.0
    # El tope global protege la factura; el tope por usuario evita que una sola
    # cuenta consuma la ventana diaria de todos (denegación de servicio por
    # agotamiento de presupuesto). <= 0 lo desactiva, igual que sus hermanos.
    LLM_BUDGET_USD_DAILY_PER_USER: float = 1.0
    # C2.9 — cubo por ORGANIZACIÓN, además del de usuario.
    #
    # El tope por usuario evita que una cuenta agote la ventana global,
    # pero no que una organización con veinte cuentas lo haga entre todas:
    # veinte por 1 USD son 20, cuatro veces el tope diario global. Sin este
    # cubo, el reparto entre clientes lo decide quién pregunta primero.
    #
    # 5,0 = el tope diario global: por defecto una sola organización puede
    # agotarlo, que es el comportamiento de hoy. Bajarlo es la decisión de
    # reparto, y se toma con datos de uso, no de antemano.
    LLM_BUDGET_USD_DAILY_PER_ORG: float = 5.0
    # monitor: superar el presupuesto solo alerta (métrica + warning), no corta.
    # enforce: /ask responde 429 sin llamar al proveedor. Default enforce: en
    # monitor los topes de arriba no son un límite de gasto, solo un indicador,
    # y la factura queda abierta. monitor sigue disponible para rodajes puntuales
    # (medir el consumo real antes de fijar un tope), pero es una elección
    # explícita y temporal, no el estado de reposo.
    LLM_BUDGET_MODE: Literal["monitor", "enforce"] = "enforce"
    # Timeout (s) esperando al LLM en /ask. Antes era env directo en ask.py;
    # el nombre del env var se mantiene, así que despliegues existentes siguen
    # funcionando sin cambios.
    ASK_LLM_TIMEOUT_SECONDS: float = 120.0
