"""Referencias de solvencia técnica propuestas desde las adjudicaciones públicas.

El art. 90.1.a) LCSP acredita la solvencia técnica con «los principales
servicios o trabajos realizados […] en el curso de, como máximo, los tres
últimos años». Una organización que ha declarado sus NIF ya tiene esa lista en
el corpus: son sus adjudicaciones. Aquí se proponen para que la persona las
añada con un clic en vez de teclearlas; nunca se guardan solas, porque lo
adjudicado no es lo ejecutado (un acuerdo marco publica su valor máximo) y
solo la organización sabe qué contratos puede certificar.
"""

from __future__ import annotations

from datetime import date

from db.repositories.competencia_esperada import adjudicaciones_propias_desde
from db.repositories.organization_nifs import OrganizationNifRepository
from services.classification import tecnologia_label
from shared.dto import OrganizationReferencia

_nif_repo = OrganizationNifRepository()

#: Los tres años del art. 90.1.a) se cuentan aquí desde la adjudicación: la
#: fecha de ejecución no se publica.
_ANIOS = 3
_LIMITE = 10


def proponer(
    filas: list[dict[str, object]], declaradas: list[OrganizationReferencia]
) -> list[OrganizationReferencia]:
    """Las filas que aún no están declaradas, como referencias. Pura."""
    ya = {r.expediente_id for r in declaradas if r.expediente_id}
    propuestas: list[OrganizationReferencia] = []
    for fila in filas:
        if str(fila["licitacion_id"]) in ya:
            continue
        importe = fila.get("importe_adjudicado")
        propuestas.append(
            OrganizationReferencia(
                organo=str(fila["organo"])[:300],
                importe_eur=float(importe)
                if isinstance(importe, int | float) and importe >= 0
                else None,
                anio=int(str(fila["fecha_adjudicacion"])[:4]),
                # El nombre y no el código (`DATOS_IA`): es lo que la persona lee y
                # lo que la afinidad del Radar busca como palabra en los títulos.
                tecnologia=tecnologia_label(str(fila["tecnologia"]))
                if fila.get("tecnologia")
                else None,
                expediente_id=str(fila["licitacion_id"]),
            )
        )
    return propuestas[:_LIMITE]


def referencias_sugeridas(
    organization_id: int, declaradas: list[OrganizationReferencia], hoy: date
) -> list[OrganizationReferencia]:
    """Lo que la organización ganó en los últimos tres años y no ha declarado.

    Vacío sin NIF declarados: sin identidad fiscal no hay forma de saber qué
    adjudicaciones son suyas.
    """
    nifs = _nif_repo.nifs(organization_id)
    if not nifs:
        return []
    filas = adjudicaciones_propias_desde(
        empresa_ids=_nif_repo.empresa_ids(organization_id),
        nifs=nifs,
        # Se compara como texto ISO, así que un 29 de febrero sin año bisiesto vale igual.
        desde=f"{hoy.year - _ANIOS:04d}{hoy.isoformat()[4:]}",
        # Se piden de más: las ya declaradas se descartan después.
        limite=_LIMITE + len(declaradas),
    )
    return proponer([dict(fila) for fila in filas], declaradas)
