"""Relleno de ``licitaciones.organo_ref_fuente`` del histórico PLACSP, desde los ZIP mensuales.

Fase 2 del RFC ``docs/rfc/2026-10-24-rfc-identidad-placsp-organo-expediente.md``.
La re-key (``v164_identidad_placsp_rekey``) construye la clave nueva
``placsp:<órgano>:<expediente>`` con ``organo_ref_fuente``, y aborta si alguna
fila de la familia no lo tiene. La ingesta lo escribe desde la fase A, pero solo
en lo que vuelve a pasar por ella; el resto sale de aquí.

La CLI es ``scripts/rellenar_organo_ref_placsp.py``; aquí vive la lógica, que
la ingesta y los tests pueden importar::

  python scripts/rellenar_organo_ref_placsp.py                  # plan: cuenta, no escribe
  python scripts/rellenar_organo_ref_placsp.py --aplicar        # escribe mes a mes
  python scripts/rellenar_organo_ref_placsp.py --solo-meses     # qué ZIP haría falta leer
  python scripts/rellenar_organo_ref_placsp.py --desde 2025-01 --hasta 2026-10 --aplicar
  python scripts/rellenar_organo_ref_placsp.py --respaldo-por-nombre --aplicar

Cómo cruza
----------
1. **Por ``idEvl``** (la llave del RFC). Está en ``licitaciones.url`` en el
   99,9 % de las filas y es 1:1 con la entrada Atom, así que identifica sin
   ambigüedad al **ocupante actual** de una clave pisada: su ``url`` es la del
   último que escribió. Cada entrada del ZIP da su ``idEvl`` (del
   ``atom:link``) y su órgano (``scraper.codice_parser.organo_de_entry``, el
   mismo nodo y orden de esquemas que el conector).
2. **Por (expediente, órgano plegado)** para las filas sin ``idEvl`` (21 en
   producción): la entrada cuyo ``ContractFolderID`` es el expediente de la
   fila y cuyo nombre de órgano coincide. Solo si todas las entradas que casan
   dan el mismo órgano.
3. **Por nombre del órgano**, opt-in (``--respaldo-por-nombre``): el
   ``organo_ref_fuente`` que ya tienen, por unanimidad, las demás filas con el
   mismo ``organo_contratacion`` (``db.repositories.identidad.organo_ref_por_nombre``).
   Para lo que no está en ningún ZIP leído.

Qué meses lee
-------------
Por defecto, los que las filas pendientes dicen: el de su ``fuente`` si es
``bulk_YYYYMM`` (el ZIP que la trajo), el de ``fecha_actualizacion_fuente`` y el
de ``fecha_publicacion``. Un expediente aparece en el ZIP de cada mes en que se
actualizó, y el ``idEvl`` es el mismo en todos. ``--desde``/``--hasta`` fuerzan
un rango.

Idempotente y reanudable
------------------------
Solo escribe filas con la columna vacía
(``db.repositories.identidad.rellenar_organo_ref_fuente``), y con ``--aplicar``
escribe al terminar cada mes: si se corta, lo hecho se queda, y la siguiente
ejecución recalcula los meses desde las filas que **siguen** pendientes. Un
``idEvl`` que dos meses dieran con órganos distintos no se escribe: se cuenta
como conflicto (es la puerta G2 del RFC) y se decide a mano.

Puerta de la re-key: ``python scripts/inventario_pisadas_placsp.py`` imprime
las filas que siguen sin órgano, por fuente; tiene que decir «ninguna». Las que
no se resuelvan se deciden una a una (RFC, fase 2): sin datos de usuario se
borran y la reingesta las trae con su clave; con datos de usuario, a mano.

Necesita ``DATABASE_URL`` (y red para descargar los ZIP; se borran al leerlos
salvo ``--conservar-zip``).
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field

from db.repositories.identidad import (
    FilaSinOrgano,
    filas_placsp_sin_organo_ref,
    organo_ref_por_nombre,
    rellenar_organo_ref_fuente,
)
from observability import get_logger
from services.dedupe import id_evl_de_url

log = get_logger(__name__)

_MES_RE = re.compile(r"^(\d{4})-(\d{2})")
#: ``bulk_YYYYMM`` y ``placsp_watched_company_awards_bulk_YYYYMM``.
_BULK_RE = re.compile(r"(?:^|_)bulk_(\d{4})(\d{2})$")
_RANGO_RE = re.compile(r"^(\d{4})-(\d{2})$")

#: Prefijos con que la clave vieja de cada fuente envolvía el expediente.
#: PLACSP (``placsp``/``bulk_*``) no llevaba ninguno.
_PREFIJO_VIEJO_POR_FUENTE = ("placsp_watched_company_awards", "placsp_agregadas")

Mes = tuple[int, int]


def plegar(nombre: str | None) -> str:
    """Nombre de órgano comparable: minúsculas y espacios colapsados."""
    return " ".join((nombre or "").lower().split())


def expediente_de_fila(id_externo: str, fuente: str) -> str:
    """El ``ContractFolderID`` que guarda la clave vieja de una fila.

    PLACSP lo guardaba tal cual (con sus ``:`` si los tiene); empresas vigiladas
    y agregadas, detrás de ``<fuente>:``. No es ``expediente_natural``: esa corta
    por el primer ``:`` y partiría «RSC: 2019-00078».
    """
    for prefijo in _PREFIJO_VIEJO_POR_FUENTE:
        if fuente.startswith(prefijo) and id_externo.startswith(f"{fuente}:"):
            return id_externo[len(fuente) + 1 :]
    return id_externo


def _mes_de(texto: str | None) -> Mes | None:
    m = _MES_RE.match(texto or "")
    if m is None or not 1 <= int(m.group(2)) <= 12:
        return None
    return int(m.group(1)), int(m.group(2))


def meses_de_fila(fila: FilaSinOrgano) -> list[Mes]:
    """Los ZIP donde está la entrada de la fila, del más probable al menos."""
    candidatos: list[Mes | None] = []
    bulk = _BULK_RE.search(fila["fuente"])
    if bulk is not None:
        candidatos.append(_mes_de(f"{bulk.group(1)}-{bulk.group(2)}"))
    candidatos.append(_mes_de(fila["fecha_actualizacion_fuente"]))
    candidatos.append(_mes_de(fila["fecha_publicacion"]))
    vistos: list[Mes] = []
    for mes in candidatos:
        if mes is not None and mes not in vistos:
            vistos.append(mes)
    return vistos


def meses_entre(desde: str, hasta: str) -> list[Mes]:
    """Los meses ``YYYY-MM`` de ``desde`` a ``hasta``, ambos incluidos."""
    inicio, fin = _rango(desde), _rango(hasta)
    if inicio > fin:
        raise ValueError(f"--desde ({desde}) es posterior a --hasta ({hasta})")
    meses: list[Mes] = []
    year, month = inicio
    while (year, month) <= fin:
        meses.append((year, month))
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return meses


def _rango(texto: str) -> Mes:
    m = _RANGO_RE.match(texto)
    if not m or not 1 <= int(m.group(2)) <= 12:
        raise ValueError(f"mes inválido: {texto!r} (se espera YYYY-MM)")
    return int(m.group(1)), int(m.group(2))


@dataclass
class Cruce:
    """Las filas pendientes, indexadas por las dos llaves del cruce."""

    por_evl: dict[str, list[str]] = field(default_factory=dict)
    #: (expediente, órgano plegado) → ids, solo de filas sin ``idEvl``.
    por_expediente: dict[tuple[str, str], list[str]] = field(default_factory=dict)
    #: id → órgano asignado por ``idEvl`` (lo que se escribe).
    asignado: dict[str, str] = field(default_factory=dict)
    #: id → órganos vistos por (expediente, nombre); se decide al final.
    candidatos_expediente: dict[str, set[str]] = field(default_factory=dict)
    conflictos: set[str] = field(default_factory=set)
    entradas_sin_organo: int = 0
    por_esquema: Counter[str] = field(default_factory=Counter)

    @classmethod
    def desde_filas(cls, filas: Iterable[FilaSinOrgano]) -> Cruce:
        cruce = cls()
        for fila in filas:
            evl = id_evl_de_url(fila["url"])
            if evl:
                cruce.por_evl.setdefault(evl, []).append(fila["id_externo"])
            else:
                clave = (
                    expediente_de_fila(fila["id_externo"], fila["fuente"]),
                    plegar(fila["organo_contratacion"]),
                )
                cruce.por_expediente.setdefault(clave, []).append(fila["id_externo"])
        return cruce

    def considerar(self, entry: object) -> list[tuple[str, str]]:
        """Las asignaciones nuevas por ``idEvl`` que da una entrada del ZIP (elemento lxml)."""
        from scraper.codice_parser import _text, organo_de_entry

        evl = id_evl_de_url(_text(entry, "./atom:link/@href"))
        ids_evl = self.por_evl.get(evl, []) if evl else []
        expediente = _text(entry, "./cacext:ContractFolderStatus/cbc:ContractFolderID")
        nombre = plegar(
            _text(
                entry,
                "./cacext:ContractFolderStatus/cacext:LocatedContractingParty"
                "/cac:Party/cac:PartyName/cbc:Name",
            )
        )
        ids_expediente = self.por_expediente.get((expediente or "", nombre), [])
        if not ids_evl and not ids_expediente:
            return []

        organo = organo_de_entry(entry)
        if organo is None:
            self.entradas_sin_organo += 1
            return []

        nuevas: list[tuple[str, str]] = []
        for id_externo in ids_evl:
            previo = self.asignado.get(id_externo)
            if previo is None:
                self.asignado[id_externo] = organo.valor
                self.por_esquema[organo.esquema] += 1
                nuevas.append((id_externo, organo.valor))
            elif previo != organo.valor:
                self.conflictos.add(id_externo)
        for id_externo in ids_expediente:
            self.candidatos_expediente.setdefault(id_externo, set()).add(organo.valor)
        return nuevas

    def por_expediente_inequivocos(self) -> list[tuple[str, str]]:
        """Las filas sin ``idEvl`` a las que todas sus entradas dan el mismo órgano."""
        salida: list[tuple[str, str]] = []
        for id_externo, organos in sorted(self.candidatos_expediente.items()):
            if id_externo in self.asignado:
                continue
            if len(organos) == 1:
                salida.append((id_externo, next(iter(organos))))
            else:
                self.conflictos.add(id_externo)
        return salida


def _entries_del_mes(year: int, month: int, *, conservar: bool) -> Iterator[object]:
    from scraper.bulk_downloader import download_month, iter_xml_files
    from scraper.connectors.placsp import _iter_atom_entries

    zip_path = download_month(year, month)
    if zip_path is None:
        log.warning("relleno_organo_mes_no_publicado", year=year, month=month)
        return
    try:
        for _nombre, contenido in iter_xml_files(zip_path):
            for entry, _ in _iter_atom_entries(contenido):
                yield entry
    finally:
        if not conservar:
            zip_path.unlink(missing_ok=True)


@dataclass
class ResumenRelleno:
    pendientes: int = 0
    meses: list[Mes] = field(default_factory=list)
    por_evl: int = 0
    por_expediente: int = 0
    por_nombre: int = 0
    escritas: int = 0
    conflictos: int = 0
    entradas_sin_organo: int = 0
    sin_resolver: int = 0
    por_esquema: dict[str, int] = field(default_factory=dict)


def rellenar(
    *,
    aplicar: bool,
    meses: list[Mes] | None = None,
    respaldo_por_nombre: bool = False,
    conservar_zip: bool = False,
    solo_meses: bool = False,
) -> ResumenRelleno:
    """Cruza las filas sin órgano con los ZIP y, con ``aplicar``, las rellena."""
    filas = filas_placsp_sin_organo_ref()
    resumen = ResumenRelleno(pendientes=len(filas))
    if meses is None:
        meses = sorted({mes for fila in filas for mes in meses_de_fila(fila)})
    resumen.meses = meses
    log.info("relleno_organo_inicio", pendientes=len(filas), meses=len(meses), aplicar=aplicar)
    if not filas or solo_meses:
        return resumen

    cruce = Cruce.desde_filas(filas)
    for year, month in meses:
        del_mes: list[tuple[str, str]] = []
        for entry in _entries_del_mes(year, month, conservar=conservar_zip):
            del_mes.extend(cruce.considerar(entry))
        escritas = rellenar_organo_ref_fuente(del_mes) if aplicar else 0
        resumen.por_evl += len(del_mes)
        resumen.escritas += escritas
        log.info(
            "relleno_organo_mes",
            year=year,
            month=month,
            asignadas=len(del_mes),
            escritas=escritas,
            aplicar=aplicar,
        )

    por_expediente = cruce.por_expediente_inequivocos()
    resumen.por_expediente = len(por_expediente)
    if aplicar:
        resumen.escritas += rellenar_organo_ref_fuente(por_expediente)

    resueltas = set(cruce.asignado) | {i for i, _ in por_expediente}
    if respaldo_por_nombre:
        # Sin aplicar, las filas que el cruce resolvería siguen vacías en la
        # base: se descuentan para no contarlas dos veces.
        por_nombre = [
            (i, o)
            for i, o in organo_ref_por_nombre().items()
            if i not in resueltas and i not in cruce.conflictos
        ]
        resumen.por_nombre = len(por_nombre)
        resueltas |= {i for i, _ in por_nombre}
        if aplicar:
            resumen.escritas += rellenar_organo_ref_fuente(por_nombre)

    resumen.conflictos = len(cruce.conflictos)
    resumen.entradas_sin_organo = cruce.entradas_sin_organo
    resumen.por_esquema = dict(cruce.por_esquema)
    resumen.sin_resolver = len({f["id_externo"] for f in filas} - resueltas)
    return resumen
