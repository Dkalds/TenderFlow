"""Buscador oficial de contratación de Euskadi, paginado (C4.3).

Qué reemplaza, y por qué
------------------------
Hasta 2026-09 esta fuente era ``EuskadiRssConnector``, sobre el RSS de
Euskadi.eus. **No ingería nada.** Medido el 2026-09-06 contra el feed en vivo:
50 avisos, **0** con ``natural_id``. El extractor de id de ``regional_rss``
sólo reconoce ``?N=`` en el enlace o un ``ID:`` en el texto, y los enlaces de
Euskadi son rutas de contenido::

    https://www.euskadi.eus/contenidos/anuncio_contratacion/expjaso739623/es_doc/index.html

Sin id, ``fetch`` descarta el aviso antes de llegar a ``parse``. Producción lo
confirma: ``licitaciones`` no tiene **ninguna** fila con ``fuente='euskadi_rss'``.
El conector corría a diario en ``scrape-daily.yml``, terminaba en ``success``
con ``fetched=0``, y el chequeo de frescura no puede distinguir eso de «no
había nada nuevo».

El test que debía cubrirlo (``tests/test_connectors_regional_rss.py``) usaba un
enlace **inventado** —``https://www.euskadi.eus/x?N=100``— que sí trae ``?N=``.
Por eso el fallo sobrevivió a la suite: la fixture describía un feed que no
existe. Las de aquí se graban de la fuente real.

El contrato de la fuente
------------------------
Euskadi no publica en PLACSP (medido: 0 coincidencias de ``Euskadi``/``Eusko``/
``Gobierno Vasco``/``Osakidetza`` en una página de 235 entradas del feed 643,
frente a 17 con señal gallega). Su canal propio es el buscador R01, que sirve
la misma búsqueda en varias presentaciones. La presentación **XML** entrega los
campos estructurados —no la prosa del RSS, que ``regional_rss`` tenía que
recortar con expresiones regulares sobre ``<b>Etiqueta:</b> valor``— y pagina::

    GET https://www.euskadi.eus/r01htSearchResultWAR/r01hPresentationXML.jsp
        ?r01kSrchSrcId=contenidos.inter
        &r01kTgtPg=<n>&r01kPgCmd=<n>          # las DOS: r01kTgtPg sola no pagina
        &r01kLang=es
        &r01kQry=tC:euskadi;tT:anuncio_contratacion;m:documentLanguage.EQ.es;pp:r01PageSize.<n>

La respuesta trae ``<totalNumberOfResults>`` y un ``<navBar>`` con
``currentPage`` y ``totalNumberOfPages``, así que el recorrido tiene final
conocido en vez de «pedir hasta que venga vacío».

``r01kPgCmd`` no es decorativo: sin él el servidor devuelve **siempre la página
1** con HTTP 200 — un paginador silenciosamente roto, que es la clase de fallo
que este módulo ya sufrió una vez.

Orden y cursor
--------------
El resultado viene **de más nuevo a más viejo** y no sólo dentro de la página:
medido el 2026-09-06, la página 1 abre en 2026-09-06 y la 100 en 2026-08-18,
sin saltos hacia arriba. Eso permite un cursor por fecha de publicación: se
recorren páginas mientras traigan algo igual o más nuevo que el cursor y se
para en la primera enteramente más vieja.

Al ser newest-first, este conector **no** declara
``cursor_advances_incrementally``: su ``new_cursor()`` ya es el máximo global en
el primer lote, y avanzarlo por lote perdería para siempre los avisos viejos
aún sin procesar si el run se corta (``scraper/connectors/base.py``).

Cuántos avisos son tecnología
-----------------------------
Medido sobre 500 avisos reales (10 páginas de 50, 2026-09-06): **2**, un 0,4 %
—soporte de licencias Oracle de una diputación y licencias de SQL Server para
DonostiaTIK—. Es el orden de magnitud esperable: el filtro tecnológico corta
toda la contratación pública contra un diccionario de producto. Sobre los
697.986 resultados del buscador son unos ~2.800 históricos, y del flujo diario
(~100 avisos) sale una coincidencia cada pocos días. Justifica el conector; no
justifica presentarlo como censo de mercado.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

import requests
from lxml import etree

from db.upsert import Licitacion
from scraper.connectors.base import ParsedTender, RawNotice
from scraper.connectors.regional_rss import parser_seguro
from scraper.filters import matches_technology
from services.classification import normalizar_estado

if TYPE_CHECKING:
    from collections.abc import Iterator

#: Presentación XML del buscador oficial. El war es ``r01htSearchResultWAR``
#: (con ``t``), que es el que resuelve la paginación; ``r01hSearchResultWar``
#: sirve la misma búsqueda pero ignora ``r01kTgtPg``.
BASE_URL = "https://www.euskadi.eus/r01htSearchResultWAR/r01hPresentationXML.jsp"

#: Búsqueda: anuncios de contratación de euskadi.eus, en castellano.
QUERY_BASE = "tC:euskadi;tT:anuncio_contratacion;m:documentLanguage.EQ.es"

#: Página del anuncio en el portal, construida desde ``contentName``. Es la URL
#: que ve una persona, y la que resuelve al expediente.
FICHA_URL = "https://www.euskadi.eus/contenidos/anuncio_contratacion/{}/es_doc/index.html"

_HOST_PERMITIDO = "www.euskadi.eus"
_TIMEOUT = 45
_MAX_PAGINA_BYTES = 8 * 1024 * 1024
#: Tamaño de página. 50 es el equilibrio medido: la página pesa ~1,5 MB y una
#: pasada diaria cabe en pocas peticiones.
PAGE_SIZE = 50
#: Tope del run incremental: 20 páginas ≈ 1.000 avisos ≈ diez días de flujo.
#: El tope existe para que un cursor corrupto no dispare 14.000 peticiones.
MAX_PAGINAS = 20
#: Primer run, sin cursor. Mismo criterio conservador que el bootstrap de
#: PLACSP: traer una ventana reciente, no el histórico entero.
MAX_PAGINAS_BOOTSTRAP = 5

#: ``Sun Sep 06 00:00:00 CEST 2026`` — ``java.util.Date.toString()``.
_FECHA_JAVA_RE = re.compile(r"^\w{3} (\w{3}) (\d{2}) [\d:]+ \S+ (\d{4})$")
#: ``05/10/2026 23:59`` y ``06/09/2026``.
_FECHA_ES_RE = re.compile(r"^(\d{2})/(\d{2})/(\d{4})(?:\s+(\d{1,2}):(\d{2}))?")
_MESES_EN = {
    m: i
    for i, m in enumerate(
        ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"), 1
    )
}
#: ``S4833001C - EUSTAT - Instituto Vasco de Estadística``: NIF y nombre.
_NIF_PREFIJO_RE = re.compile(r"^[A-Z]\d{7}[A-Z0-9]\s*-\s*", re.IGNORECASE)

#: ``contratacion_estado_tramitacion`` → estado canónico (``shared/estados.py``).
#: Los dos códigos observados, verificados contra la ficha pública del propio
#: anuncio: ``AL`` renderiza «Estado de la tramitación: Abierto / Plazo de
#: presentación» y ``AD``, «Adjudicación». Un código nuevo **no** se adivina:
#: pasa por ``normalizar_estado``, que lo conserva en crudo para que se vea.
ESTADOS_FUENTE: dict[str, str] = {"AL": "PUB", "AD": "ADJ"}

#: Universo de análisis. El literal dice ``rss`` porque es el que quedó
#: **congelado dentro de migraciones ya aplicadas** (``v98``, ``v99``, ``v102``
#: lo llevan escrito en el cuerpo de sus vistas materializadas, que es
#: append-only) y en ``db/sql_fragments.py::UNIVERSOS_TECNOLOGICOS``. Renombrarlo
#: exigiría reconstruir tres vistas materializadas para ganar exactitud en un
#: identificador: nombra el origen de las filas, no el mecanismo de hoy.
ANALYSIS_UNIVERSE = "euskadi_rss_recent_technology_observed"


def _texto(item: etree._Element, campo: str) -> str | None:
    """Valor de un campo del ``<item>``, ya sin CDATA ni espacios de sobra.

    Busca en todo el subárbol y no sólo entre los hijos directos: los campos
    ``contratacion_*`` cuelgan de ``<documentMetaData>``, mientras que
    ``contentName`` sí es hijo del ``<item>``. Con ``find(campo)`` el conector
    leía el id y **todo lo demás en blanco**, que es un fallo mudo: la fila se
    persistiría sin título, sin fecha y sin órgano.
    """
    el = item.find(f".//{campo}")
    if el is None or el.text is None:
        return None
    return " ".join(el.text.split()) or None


def _fecha(valor: str | None) -> str | None:
    """ISO ``YYYY-MM-DD[THH:MM]`` desde los dos formatos que publica la fuente.

    Devuelve ``None`` ante cualquier otro: una fecha mal interpretada es peor
    que una ausente — ``fecha_limite`` decide si un expediente sale como
    abierto.
    """
    if not valor:
        return None
    java = _FECHA_JAVA_RE.match(valor)
    if java:
        mes = _MESES_EN.get(java.group(1))
        return f"{java.group(3)}-{mes:02d}-{java.group(2)}" if mes else None
    es = _FECHA_ES_RE.match(valor)
    if not es:
        return None
    dia, mes_es, anio, hora, minuto = es.groups()
    if not 1 <= int(mes_es) <= 12:
        return None
    fecha = f"{anio}-{mes_es}-{dia}"
    return f"{fecha}T{int(hora):02d}:{minuto}:00" if hora else fecha


def _entidad(valor: str | None) -> str | None:
    """Nombre de la entidad, sin el NIF que la fuente antepone.

    ``S4833001C - EUSTAT - Instituto Vasco de Estadística`` → ``EUSTAT -
    Instituto Vasco de Estadística``. El NIF se quita y no se guarda en
    ``organo_dir3``: ese campo es para códigos DIR3 (C1.2), y un NIF ahí sería
    un identificador de otro registro con el mismo nombre de columna.
    """
    if not valor:
        return None
    return _NIF_PREFIJO_RE.sub("", valor).strip() or None


class EuskadiApiConnector:
    """Conector paginado sobre el buscador oficial de Euskadi."""

    source_id = "euskadi"
    ccaa = "País Vasco"

    def __init__(
        self,
        *,
        base_url: str | None = None,
        session: requests.Session | None = None,
        page_size: int = PAGE_SIZE,
        max_paginas: int | None = None,
    ) -> None:
        self._base_url = base_url or BASE_URL
        self._session = session or requests.Session()
        self._page_size = max(1, page_size)
        self._max_paginas = max_paginas
        self._max_visto: str | None = None
        #: Diagnóstico del último ``fetch``: lo imprime el CLI y lo mira quien
        #: quiera saber si el recorrido se cortó por cursor o por tope.
        self.paginas_leidas = 0
        self.total_declarado: int | None = None

    # ── fetch ────────────────────────────────────────────────────────────
    def fetch(self, cursor: dict[str, Any] | None) -> Iterator[RawNotice]:
        previo = str((cursor or {}).get("last_seen_updated") or "")
        tope = self._max_paginas or (MAX_PAGINAS if previo else MAX_PAGINAS_BOOTSTRAP)
        pagina = 1
        while pagina <= tope:
            raiz = self._descargar(pagina)
            self.paginas_leidas = pagina
            total_paginas = self._total_paginas(raiz)
            items = raiz.findall(".//item")
            if not items:
                return
            alguno_nuevo = False
            for item in items:
                nombre = _texto(item, "contentName")
                if not nombre:
                    continue
                publicado = _fecha(_texto(item, "contratacion_fecha_de_publicacion_documento"))
                # `<` y no `<=`: los avisos del mismo día que el cursor se
                # vuelven a emitir. El upsert es idempotente (ADR-009) y el
                # cursor tiene precisión de día, así que la alternativa es
                # perder lo publicado más tarde en la jornada del corte.
                if publicado and previo and publicado < previo:
                    continue
                alguno_nuevo = True
                if publicado and (self._max_visto is None or publicado > self._max_visto):
                    self._max_visto = publicado
                yield RawNotice(
                    natural_id=nombre,
                    payload={
                        "content_name": nombre,
                        "expediente": _texto(item, "contratacion_expediente"),
                        "titulo": _texto(item, "contratacion_titulo_contrato"),
                        "objeto": _texto(item, "contratacion_objeto_contrato"),
                        "organo": _texto(item, "contratacion_organo_contratacion"),
                        "entidad": _texto(item, "contratacion_entidad_impulsora"),
                        "poder_adjudicador": _texto(item, "contratacion_poder_adjudicador_titulo"),
                        "estado": _texto(item, "contratacion_estado_tramitacion"),
                        "contrato_menor": _texto(item, "contratacion_contrato_menor"),
                        "publicado": publicado,
                        "fecha_limite": _fecha(
                            _texto(item, "contratacion_fecha_limite_presentacion")
                        ),
                    },
                )
            # Página entera por debajo del cursor: al venir ordenado de más
            # nuevo a más viejo, lo que queda detrás también lo está.
            if previo and not alguno_nuevo:
                return
            if total_paginas is not None and pagina >= total_paginas:
                return
            pagina += 1

    def _descargar(self, pagina: int) -> etree._Element:
        if urlparse(self._base_url).hostname != _HOST_PERMITIDO:
            raise ValueError(f"URL fuera del dominio oficial de Euskadi: {self._base_url}")
        respuesta = self._session.get(
            self._base_url,
            params={
                "r01kSrchSrcId": "contenidos.inter",
                # Las dos, y con el mismo valor: `r01kTgtPg` dice a qué página
                # ir y `r01kPgCmd` es la orden de paginar. Sin la segunda el
                # servidor responde 200 con la página 1.
                "r01kTgtPg": str(pagina),
                "r01kPgCmd": str(pagina),
                "r01kLang": "es",
                "r01kQry": f"{QUERY_BASE};pp:r01PageSize.{self._page_size}",
                "r01kSearchResultsHeader": "1",
            },
            timeout=_TIMEOUT,
        )
        respuesta.raise_for_status()
        contenido = respuesta.content
        if len(contenido) > _MAX_PAGINA_BYTES:
            raise ValueError("La página del buscador supera el límite seguro de 8 MiB.")
        return etree.fromstring(contenido, parser=parser_seguro())

    def _total_paginas(self, raiz: etree._Element) -> int | None:
        """``totalNumberOfPages`` del ``<navBar>``, si la respuesta lo trae."""
        nav = raiz.find(".//navBar")
        if nav is None:
            return None
        if self.total_declarado is None:
            total = nav.get("totalNumberOfResults")
            self.total_declarado = int(total) if total and total.isdigit() else None
        paginas = nav.get("totalNumberOfPages")
        return int(paginas) if paginas and paginas.isdigit() else None

    # ── parse ────────────────────────────────────────────────────────────
    def parse(self, raw: RawNotice) -> ParsedTender | None:
        payload = raw.payload
        titulo = str(payload.get("titulo") or payload.get("objeto") or "").strip()
        if not titulo:
            return None
        objeto = str(payload.get("objeto") or "")
        _, coincidencias = matches_technology(f"{titulo} {objeto}", None)
        if not coincidencias:
            return None

        tecnologias = sorted(coincidencias)
        keywords = sorted({k for valores in coincidencias.values() for k in valores})
        publicado = payload.get("publicado")
        estado_fuente = str(payload.get("estado") or "")
        lic = Licitacion(
            id_externo=f"{self.source_id}:{raw.natural_id}",
            titulo=titulo[:500],
            # Sólo si aporta algo: en la mayoría de los avisos el objeto y el
            # título son el mismo texto, y duplicarlo ensucia la ficha y el FTS.
            descripcion=objeto if objeto and objeto != titulo else None,
            organo_contratacion=_entidad(payload.get("entidad"))
            or (str(payload.get("organo")) if payload.get("organo") else None),
            # El buscador no publica importe. `importe_tipo=None` es
            # deliberado y significa «la fuente no publicó importe» (C1.1,
            # ADR-032), que no es lo mismo que `desconocido`.
            estado=ESTADOS_FUENTE.get(estado_fuente) or normalizar_estado(estado_fuente),
            fecha_publicacion=publicado[:10] if isinstance(publicado, str) else None,
            fecha_limite=(str(payload["fecha_limite"]) if payload.get("fecha_limite") else None),
            url=FICHA_URL.format(payload.get("content_name")),
            raw_keywords=",".join(keywords) or None,
            tecnologia=",".join(tecnologias) or None,
            ccaa=self.ccaa,
            inclusion_reason="euskadi_api_technology_match",
            analysis_universe=ANALYSIS_UNIVERSE,
            fecha_actualizacion_fuente=publicado if isinstance(publicado, str) else None,
            fuente=self.source_id,
        )
        return ParsedTender(licitacion=lic)

    def new_cursor(self) -> dict[str, Any] | None:
        return {"last_seen_updated": self._max_visto} if self._max_visto else None


def main(argv: list[str] | None = None) -> int:
    """Ejecuta la ingesta incremental del buscador oficial de Euskadi."""
    import argparse

    parser = argparse.ArgumentParser(description="Ingesta del buscador oficial de Euskadi")
    parser.add_argument("--url", help="URL alternativa del buscador, para diagnostico")
    parser.add_argument(
        "--paginas",
        type=int,
        default=None,
        help="Tope de paginas de esta pasada (por defecto: 20 incremental, 5 en el primer run)",
    )
    parser.add_argument("--page-size", type=int, default=PAGE_SIZE)
    args = parser.parse_args(argv)

    from db.database import close_pool, init_db
    from scraper.connectors.base import run_connector

    conector = EuskadiApiConnector(
        base_url=args.url, page_size=args.page_size, max_paginas=args.paginas
    )
    init_db()
    try:
        result = run_connector(conector)
    finally:
        close_pool()
    print(
        f"Euskadi: {result.fetched} avisos · {result.nuevas} nuevas · "
        f"{result.actualizadas} actualizadas · {result.descartadas} descartadas · "
        f"{result.errores} errores · {conector.paginas_leidas} paginas "
        f"(la fuente declara {conector.total_declarado or '?'} resultados)"
    )
    return 0 if result.errores == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
