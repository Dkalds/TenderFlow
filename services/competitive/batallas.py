"""F3.2 (batallas directas) y F3.5 (cortes nuevos del perfil de competidor).

**Batallas.** El perfil de una empresa cuenta lo que esa empresa gana. No sabe
nada de nosotros, así que no responde la pregunta que un comercial se hace
delante de un rival: *¿cuántas veces nos hemos cruzado, y cómo acabó?* Este
módulo cruza nuestras oportunidades presentadas con las adjudicaciones
observadas y devuelve el historial de esos cruces.

Lo que se puede afirmar sin el NIF propio
------------------------------------------
Sin saber cuál es nuestra empresa en el maestro (v2 S2.1), el producto puede
afirmar **«nosotros perdimos»** —lo dice nuestro propio cierre— pero no
**«ellos ganaron contra nosotros»**, que exige comprobar que el adjudicatario
es ese rival y no un tercero. Las dos cosas se distinguen en la respuesta
(``resultado``) en vez de presentarse como una: acusar a un competidor de
haber ganado algo que ganó otro es un error que un comercial detecta en la
primera reunión, y con él se va la confianza en el resto de la pantalla.

**Cortes de F3.5.** Bajas y adjudicaciones por procedimiento (`v85`) y por
tramo de importe. Con `n` por celda y sin publicar las que no llegan al
mínimo: el mismo criterio que el resto del producto.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "MIN_POR_CELDA",
    "TRAMOS_IMPORTE",
    "Batalla",
    "BatallasContraMi",
    "CeldaCorte",
    "batallas_de_usuario",
    "construir_batallas",
    "corte_por_procedimiento",
    "corte_por_tramo",
    "tramo_de",
]

#: Cierres mínimos por celda de un corte. El mismo cinco que F3.1 y F4.2.
MIN_POR_CELDA = 5

#: Tramos de importe, en euros. Los cortes son los que separan regímenes reales
#: de la LCSP —contrato menor, simplificado abreviado, simplificado, sujeto a
#: regulación armonizada—, no potencias de diez: un tramo que no corresponde a
#: ninguna frontera legal no explica nada de por qué compite quien compite.
TRAMOS_IMPORTE: tuple[tuple[str, float, float | None], ...] = (
    ("< 15k", 0.0, 15_000.0),
    ("15k-60k", 15_000.0, 60_000.0),
    ("60k-140k", 60_000.0, 140_000.0),
    ("140k-1M", 140_000.0, 1_000_000.0),
    ("> 1M", 1_000_000.0, None),
)

ResultadoBatalla = Literal["perdimos", "ganamos", "ellos_ganaron", "sin_resolver"]


class Batalla(BaseModel):
    """Un expediente en el que coincidimos con el competidor."""

    model_config = ConfigDict(extra="forbid")

    licitacion_id: str
    titulo: str | None = None
    organo_contratacion: str | None = None
    fecha: str | None = None
    importe: float | None = None
    #: Qué se puede afirmar de este cruce. `ellos_ganaron` sólo cuando el
    #: adjudicatario observado **es** el competidor; si no, `perdimos` a secas.
    resultado: ResultadoBatalla
    #: Nuestra baja ofertada, si la registramos. `None` = no se registró, y la
    #: fila lo dice en vez de dejar la columna en blanco.
    nuestra_baja: float | None = None
    #: La baja con la que se adjudicó, si se observó.
    baja_ganadora: float | None = None


class BatallasContraMi(BaseModel):
    """El historial de cruces con un competidor."""

    model_config = ConfigDict(extra="forbid")

    empresa_key: str
    batallas: list[Batalla] = Field(default_factory=list)
    #: Cruces encontrados. Es el `n` de la pantalla.
    n: int = Field(default=0, ge=0)
    #: Ventana consultada, declarada (ADR-014).
    ventana: str = "últimos 24 meses"
    #: `True` cuando el producto no sabe cuál es la propia empresa y por tanto
    #: no puede afirmar «ellos ganaron». La UI lo dice; sin eso, un historial
    #: lleno de «perdimos» parecería un rival invencible.
    sin_nif_propio: bool = False


def _baja(importe: float | None, adjudicado: float | None) -> float | None:
    """Baja en tanto por uno, o ``None`` si falta alguno de los dos."""
    if importe is None or adjudicado is None or importe <= 0:
        return None
    return round(1 - (adjudicado / importe), 4)


def construir_batallas(
    empresa_key: str,
    cruces: list[dict[str, Any]],
    *,
    nif_propio: str | None = None,
) -> BatallasContraMi:
    """Convierte los cruces en el historial contra un competidor.

    ``cruces`` son filas con nuestra oportunidad y la adjudicación observada
    del mismo expediente. ``nif_propio`` es el de nuestra organización cuando
    se conoce (v2 S2.1): con él se puede distinguir «ganamos nosotros» de
    «ganó un tercero»; sin él, no.

    Sólo entran los cruces con ``offer_price_eur``: sin nuestro precio no hay
    batalla que contar, sólo dos empresas en el mismo expediente. Las filas
    sin él **se cuentan** en `n` y se devuelven con `nuestra_baja=None`, para
    que la pantalla pueda decir «de estos doce cruces, en cinco no registramos
    el precio» en vez de esconderlos.
    """
    batallas: list[Batalla] = []
    for fila in cruces:
        importe = fila.get("importe")
        nuestro_precio = fila.get("offer_price_eur")
        adjudicado = fila.get("importe_adjudicado")
        outcome = str(fila.get("outcome") or "")
        adjudicatario = str(fila.get("adjudicatario_key") or "")

        if outcome == "won":
            resultado: ResultadoBatalla = "ganamos"
        elif outcome != "lost":
            resultado = "sin_resolver"
        elif adjudicatario and adjudicatario == empresa_key:
            # Sólo aquí se puede afirmar que ganaron ellos: el adjudicatario
            # observado es este competidor, no un tercero.
            resultado = "ellos_ganaron"
        else:
            resultado = "perdimos"

        batallas.append(
            Batalla(
                licitacion_id=str(fila.get("licitacion_id") or ""),
                titulo=fila.get("titulo"),
                organo_contratacion=fila.get("organo_contratacion"),
                fecha=str(fila.get("fecha_adjudicacion") or "") or None,
                importe=float(importe) if importe is not None else None,
                resultado=resultado,
                nuestra_baja=_baja(importe, nuestro_precio),
                baja_ganadora=_baja(importe, adjudicado),
            )
        )

    return BatallasContraMi(
        empresa_key=empresa_key,
        batallas=batallas,
        n=len(batallas),
        sin_nif_propio=nif_propio is None,
    )


# ── F3.5 ────────────────────────────────────────────────────────────────────


class CeldaCorte(BaseModel):
    """Una celda de un corte del perfil de competidor."""

    model_config = ConfigDict(extra="forbid")

    clave: str
    n: int = Field(ge=0)
    #: `None` por debajo del mínimo. La celda no se omite: que un competidor
    #: tenga dos adjudicaciones por negociado también dice algo.
    baja_media: float | None = None
    importe_total: float | None = None


def tramo_de(importe: Any) -> str | None:
    """El tramo de un importe, o ``None`` si no hay importe."""
    try:
        valor = float(importe)
    except (TypeError, ValueError):
        return None
    for etiqueta, minimo, maximo in TRAMOS_IMPORTE:
        if valor >= minimo and (maximo is None or valor < maximo):
            return etiqueta
    return None


def _agrupar(filas: list[dict[str, Any]], clave_de: Any, *, minimo: int) -> list[CeldaCorte]:
    acumulado: dict[str, dict[str, float]] = {}
    for fila in filas:
        clave = clave_de(fila)
        if clave is None:
            continue
        celda = acumulado.setdefault(
            clave, {"n": 0.0, "bajas": 0.0, "con_baja": 0.0, "importe": 0.0}
        )
        celda["n"] += 1
        baja = _baja(fila.get("importe"), fila.get("importe_adjudicado"))
        if baja is not None:
            celda["bajas"] += baja
            celda["con_baja"] += 1
        try:
            celda["importe"] += float(fila.get("importe_adjudicado") or 0)
        except (TypeError, ValueError):
            pass

    cortes = [
        CeldaCorte(
            clave=clave,
            n=int(datos["n"]),
            baja_media=(
                round(datos["bajas"] / datos["con_baja"], 4)
                if datos["n"] >= minimo and datos["con_baja"] > 0
                else None
            ),
            importe_total=round(datos["importe"], 2) if datos["n"] >= minimo else None,
        )
        for clave, datos in acumulado.items()
    ]
    cortes.sort(key=lambda c: (-c.n, c.clave))
    return cortes


def corte_por_procedimiento(
    filas: list[dict[str, Any]], *, minimo: int = MIN_POR_CELDA
) -> list[CeldaCorte]:
    """Bajas y adjudicaciones por tipo de procedimiento (`v85`).

    La etiqueta se resuelve con el catálogo de F1.7, no con el código crudo:
    un perfil de competidor que enseñe «procedimiento 9» no lo lee nadie.
    """
    from shared.procedimientos import etiqueta_procedimiento

    return _agrupar(
        filas,
        lambda f: etiqueta_procedimiento(f.get("procedimiento"), vacio="") or None,
        minimo=minimo,
    )


def corte_por_tramo(
    filas: list[dict[str, Any]], *, minimo: int = MIN_POR_CELDA
) -> list[CeldaCorte]:
    """Bajas y adjudicaciones por tramo de importe."""
    return _agrupar(filas, lambda f: tramo_de(f.get("importe")), minimo=minimo)


def batallas_de_usuario(
    user_id: int,
    empresa_key: str,
    *,
    organization_id: int | None = None,
    meses: int = 24,
) -> BatallasContraMi:
    """El historial de cruces con un competidor, con el ámbito ya resuelto.

    La resolución de organización vive aquí y no en la ruta: `api/` no importa
    `resolve_organization` directamente (lo audita
    `test_organization_sql_isolation`), porque cada ruta que lo hiciera sería
    otro sitio donde equivocarse con el ámbito — y éste consulta el pipeline de
    un equipo.
    """
    from datetime import UTC, datetime, timedelta

    from db.repositories.pursuits import PursuitRepository
    from services.organizations import resolve_organization

    resuelta, _rol = resolve_organization(user_id, organization_id)
    desde = (datetime.now(UTC) - timedelta(days=30 * meses)).isoformat()
    cruces = PursuitRepository().cruces_con_competidor(resuelta, empresa_key, desde_iso=desde)
    resultado = construir_batallas(empresa_key, cruces)
    return resultado.model_copy(update={"ventana": f"últimos {meses} meses"})
