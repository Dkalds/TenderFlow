"""Settings de la ingesta: descargas, allowlists de salida, conectores y cierre de la pasada.

Módulo hermano de ``config/settings.py`` (P3 «Los dos módulos-dios»): ``Settings``
hereda de esta clase, así que los nombres de las variables de entorno y el
acceso (``settings.REQUEST_TIMEOUT``) son los de siempre.

Sin ``model_config`` propio, por lo mismo que ``config/settings_resumen.py``.
"""

from __future__ import annotations

from typing import Self

from pydantic import SecretStr, field_validator, model_validator

from config.settings_entorno import EntornoSettings


class ScraperSettings(EntornoSettings):
    """Scraper, conectores (PSCP, PLACSP, TACRC) y pasos del cierre post-ingesta."""

    # ── Resiliencia ───────────────────────────────────────────────────────
    # Circuit breaker: backoff exponencial entre aperturas del circuito
    BREAKER_BASE_TIMEOUT: int = 60  # segundos — primer timeout tras apertura
    BREAKER_MAX_TIMEOUT: int = 1800  # segundos — techo del backoff (30 min)

    # ── Scraper ──────────────────────────────────────────────────────────
    REQUEST_TIMEOUT: int = 30
    REQUEST_DELAY_SECONDS: float = 1.5
    MAX_DOWNLOAD_SIZE_BYTES: int = 400 * 1024 * 1024
    MAX_XML_SIZE_BYTES: int = 150 * 1024 * 1024
    DAILY_MAX_PAGES: int = 50
    # Pasadas seguidas del carril diario con el cursor del ATOM de PLACSP
    # parado tras las que se ingiere el ZIP mensual del mes en curso
    # (`scheduler/respaldo_zip_placsp.py`). 6 pasadas de 4 h son un día, que es
    # lo que tarda el ZIP en regenerarse: caer antes reprocesaría el mismo
    # fichero. 0 apaga el respaldo.
    PLACSP_ATOM_PASADAS_SIN_AVANCE_ZIP: int = 6
    BACKFILL_MAX_WORKERS: int = 3
    # Límite de tamaño para un adjunto individual (pliego), plan Pliegos+RAG F7.
    # Mucho más chico que MAX_DOWNLOAD_SIZE_BYTES (pensado para ZIPs mensuales
    # con miles de entries) — un PDF de pliego legítimo rara vez supera 50 MB.
    MAX_DOCUMENT_SIZE_BYTES: int = 50 * 1024 * 1024
    MAX_DOCUMENT_PAGES: int = 250
    MAX_DOCUMENT_TEXT_CHARS: int = 2_000_000
    # In production PDF parsing runs in a disposable child process. A malformed
    # document cannot monopolize the scheduler process indefinitely.
    DOCUMENT_EXTRACTION_TIMEOUT_SECONDS: int = 30
    # Union de `dominios_documentos` del inventario de fuentes, en su orden
    # (`scraper/connectors/__init__.py`); `config/` no puede importar `scraper/`,
    # así que se copia a mano y `test_allowlist_de_documentos_por_defecto_sale_del_inventario`
    # exige que coincidan.
    DOCUMENT_ALLOWED_HOSTS: str = (
        "contrataciondelestado.es,*.contrataciondelestado.es,ted.europa.eu,contractaciopublica.cat,"
        # TACRC: PDF de la resolución vinculada (scraper/connectors/tacrc.py).
        "www.hacienda.gob.es,"
        # Pliegos de las plataformas agregadas en PLACSP (placsp_agregadas.py).
        "www.contratacion.euskadi.eus,contratos-publicos.comunidad.madrid"
    )
    WEBHOOK_ALLOWED_HOSTS: str = ""

    # ── Conectores autonómicos / TACRC (RFC 20260611-1, Fase 5) ─────────
    # Dataset Socrata de publicaciones de la PSCP en el portal de
    # transparencia de la Generalitat. El id ybgg-dgi6 ("Contractació
    # pública a Catalunya: publicacions a la PSCP") está verificado contra
    # el portal oficial; los NOMBRES DE CAMPO siguen sin validar contra la
    # API viva — correr `python scripts/probe_pscp.py --dataset ybgg-dgi6`
    # antes del primer backfill y ajustar _FIELD_CANDIDATES si difieren.
    PSCP_DOMAIN: str = "analisi.transparenciacatalunya.cat"
    PSCP_DATASET_ID: str = "ybgg-dgi6"
    # App token Socrata opcional (solo necesario si aparece rate limiting).
    PSCP_APP_TOKEN: SecretStr = SecretStr("")
    # Sindicaciones secundarias de PLACSP (revisión de D16). Vacías = fuente
    # APAGADA: el conector declara `disabled` y no descarga nada, como PSCP sin
    # dataset. Se encienden fijando la URL documentada en cada módulo
    # (`URL_SINDICACION_1143` en `scraper/connectors/placsp_menores.py`,
    # `URL_SINDICACION_1044` en `placsp_agregadas.py`, `URL_SINDICACION_1403`
    # en `placsp_consultas.py`) tras validarla con
    # `python -m scraper.connectors.<módulo> --check`. Se usa la URL como
    # interruptor —y no un booleano— porque así viaja por `vars.` en el
    # workflow igual que `PSCP_DATASET_ID`: una variable de repo sin definir
    # llega como cadena vacía, que para un booleano es un error de arranque.
    PLACSP_MENORES_ATOM_URL: str = ""
    # Encendida el 2026-11-04 (decisión del dueño sobre D16): la URL documentada
    # de `URL_SINDICACION_1044`, que `config/` no puede importar; un test exige
    # que coincidan. `off` la apaga (ver `ejecutar_sindicacion`).
    PLACSP_AGREGADAS_ATOM_URL: str = (
        "https://contrataciondelsectorpublico.gob.es/sindicacion/"
        "sindicacion_1044/PlataformasAgregadasSinMenores.atom"
    )
    PLACSP_CONSULTAS_ATOM_URL: str = ""
    # Índice de resoluciones TACRC (Ministerio de Hacienda).
    #
    # URL validada con `python -m scraper.connectors.tacrc --check` (2026-06-11):
    # - BuscadordeResoluciones.aspx → SharePoint JS-rendered, 0 resoluciones
    #   parseadas con lxml (sin headless browser). NO usar como default.
    # - Resoluciones-Pleno.aspx → HTML estático con 17 PDFs embebidos;
    #   parser extrae 17 resoluciones. VALIDADO ✓
    #
    # Resoluciones-Pleno cubre solo resoluciones del Pleno (doctrinales); las
    # resoluciones individuales de recurso quedan pendientes de otro índice.
    # Para cobertura completa, configurar TACRC_INDEX_URL por entorno.
    #
    # 2026-10: el conector lee también un listado JSON de la biblioteca de
    # SharePoint y una URL con `{anio}` que recorre año a año
    # (`URL_BIBLIOTECA_RESOLUCIONES` en `scraper/connectors/tacrc.py`, sin
    # verificar: `--check` antes). El valor por defecto NO cambia: en el plano
    # del worker, sin variable, manda este, y cambiarlo encendería el índice
    # completo sin decidirlo.
    TACRC_INDEX_URL: str = (
        "https://www.hacienda.gob.es/es-ES/Areas%20Tematicas/Contratacion/"
        "TACRC/Paginas/Resoluciones-Pleno.aspx"
    )
    # Primer año que recorre un índice por años sin cursor. El TACRC se crea
    # con la Ley 34/2010; un año sin carpeta responde 404 y se salta, así que
    # empezar antes de tiempo solo cuesta una petición.
    TACRC_PRIMER_ANIO: int = 2010

    # ── Job dedicado de watchlist_rules (plan Pliegos+RAG, C2a) ────────────
    # Default False: la pipeline canónica (scheduler/pipeline_runs.py::
    # _run_watchlist_notify) ya llama a check_rules_and_notify() tras cada
    # ingesta. Este job existe para el plano APScheduler/Docker (ADR-012) —
    # activarlo solo si ese plano es el dueño de la orquestación, para no
    # correr la evaluación de reglas dos veces (la idempotencia de
    # user_notifications limita el daño a not-doble-notificación, pero no
    # el trabajo duplicado de evaluar las reglas).
    WATCHLIST_RULES_JOB_ENABLED: bool = False

    # ── Maestro de órganos: resolución incremental en la pipeline (ADR-032) ─
    # Grafías nuevas de `organo_contratacion` que cada cierre intenta resolver
    # a `organo_id`, y presupuesto de reloj para no quedarse con el step. El
    # backlog histórico lo cubrió un backfill ya ejecutado, no la pipeline.
    ORGANOS_RESOLVE_MAX_GRAFIAS: int = 500
    ORGANOS_RESOLVE_BUDGET_S: int = 120

    @field_validator("REQUEST_TIMEOUT", mode="before")
    @classmethod
    def _validate_request_timeout(cls, v: object) -> int:
        val = int(str(v))
        if val <= 0:
            raise ValueError("REQUEST_TIMEOUT debe ser > 0")
        return val

    @model_validator(mode="after")
    def _validate_prod_egress_allowlists(self) -> Self:
        """Exige allowlists para salidas que procesan contenido no confiable."""
        if self.ENV in ("prod", "staging"):
            if not self.DOCUMENT_ALLOWED_HOSTS:
                raise ValueError("DOCUMENT_ALLOWED_HOSTS es obligatorio en producción")
            if "*" in {host.strip() for host in self.WEBHOOK_ALLOWED_HOSTS.split(",")}:
                raise ValueError("WEBHOOK_ALLOWED_HOSTS no puede contener el comodín global '*'")
        return self
