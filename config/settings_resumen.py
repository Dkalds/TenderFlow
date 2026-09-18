"""Settings del resumen IA pre-generado por el job nocturno de pliegos.

Primer módulo hermano de `config/settings.py` (P3 «Los dos módulos-dios»): un
setting **nuevo** va a un módulo por dominio en vez de sumar líneas a la clase
plana. `Settings` hereda de esta clase, así que los nombres de las variables de
entorno y el acceso (`settings.RESUMEN_PREGEN_ENABLED`) son los de siempre.

Sin `model_config` propio a propósito: el de `Settings` (`.env`, `extra=ignore`)
es el que manda al instanciar, y declararlo aquí abriría la puerta a que los dos
diverjan.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings


class ResumenPregenSettings(BaseSettings):
    """Fase opcional de `scheduler/jobs/documentos_embeddings.py`."""

    # Calienta el caché del resumen IA (`POST /licitaciones/{id}/resumen`) para
    # las licitaciones que se van a abrir: oportunidades abiertas y favoritas,
    # banda `Caliente` del score y publicadas hoy. Off por defecto, mismo
    # criterio que PLIEGO_FACTS_ENABLED: genera gasto LLM y se activa de forma
    # explícita. Además exige caché compartida (REDIS_URL): escribir el resumen
    # en la memoria de un proceso que termina al acabar el job es pagar por
    # nada, y la fase se salta sola en ese caso.
    RESUMEN_PREGEN_ENABLED: bool = False
    # Resúmenes generados como máximo por corrida. Cada uno es una llamada LLM
    # de hasta 1.500 tokens de salida; el BudgetGuard corta antes si se agota.
    RESUMEN_PREGEN_BATCH: int = 20
    # Tiene que ser el modelo que pide la UI: el modelo forma parte de la clave
    # de caché, así que pre-generar con otro no calienta nada. Mantener
    # sincronizado con `ResumenRequest.model` (`api/routes/ask.py`) y con
    # `llm.client.DEFAULT_MODEL`.
    RESUMEN_PREGEN_MODEL: str = "deepseek-ai/deepseek-v4-flash-0731"
