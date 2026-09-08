"""Mi baja frente al mercado (C6.5).

`bajas/referencia` responde «en este órgano, para este CPV, la baja ganadora
media es X %». Lo que no respondía nadie es la otra mitad: **«y la mía cuál
es»**. El dato está —`pursuits.offer_price_eur` y el presupuesto del
expediente— y no se cruzaban, así que al preparar una oferta el equipo veía el
mercado sin verse a sí mismo.

Aquí vive el criterio. El SQL de la referencia sigue en
`services/competitive/bajas.py`; el de las ofertas propias, en
`db/repositories/pursuits.py`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

#: Mínimo de ofertas propias por segmento para publicar una media.
#:
#: Cinco, como pide el ítem. Por debajo, la «media» es una anécdota con formato
#: de estadística: con dos ofertas, una atípica mueve el número siete puntos y
#: alguien ajusta su próxima oferta contra ese ruido. Se devuelve el segmento
#: igualmente, con `suficiente: false` y su `n`, porque saber que solo hay dos
#: es información — no saberlo es lo que engaña.
MIN_OFERTAS_POR_SEGMENTO = 5


@dataclass(frozen=True)
class SegmentoBaja:
    """Mi baja media en un segmento, junto a la del mercado."""

    segmento: str
    clave: str
    n: int
    baja_propia_pct: float | None
    baja_mercado_pct: float | None
    contratos_mercado: int
    suficiente: bool

    @property
    def delta_pct(self) -> float | None:
        """Cuánto más agresiva es mi oferta que la del mercado, en puntos.

        `None` cuando falta cualquiera de las dos: restar contra un hueco daría
        un número que parece una comparación y no lo es.
        """
        if self.baja_propia_pct is None or self.baja_mercado_pct is None:
            return None
        return round(self.baja_propia_pct - self.baja_mercado_pct, 2)

    def as_dict(self) -> dict[str, Any]:
        return {
            "segmento": self.segmento,
            "clave": self.clave,
            "n": self.n,
            "baja_propia_pct": self.baja_propia_pct,
            "baja_mercado_pct": self.baja_mercado_pct,
            "contratos_mercado": self.contratos_mercado,
            "suficiente": self.suficiente,
            "delta_pct": self.delta_pct,
        }


def baja_propia_pct(presupuesto: float | None, oferta: float | None) -> float | None:
    """`(presupuesto - oferta) / presupuesto * 100`, o `None` si no se puede.

    Se descarta el presupuesto no positivo (no hay baja sobre cero) y la oferta
    negativa. **No** se descarta la oferta por encima del presupuesto: una baja
    negativa es rara pero real —ofertas sobre presupuesto en contratos con
    revisión— y esconderla sesgaría la media hacia abajo.
    """
    if presupuesto is None or oferta is None:
        return None
    try:
        base = float(presupuesto)
        importe = float(oferta)
    except (TypeError, ValueError):
        return None
    if base <= 0 or importe < 0:
        return None
    return round((base - importe) / base * 100, 2)


def agrupar(
    ofertas: list[dict[str, Any]],
    referencias: dict[tuple[str, str], dict[str, Any]],
) -> list[SegmentoBaja]:
    """Agrupa mis ofertas por CPV4 y por órgano, y las cruza con el mercado.

    Args:
        ofertas: filas con `cpv`, `organo_contratacion`, `presupuesto` y
            `offer_price_eur`. El presupuesto debe venir ya en **base sin IVA**
            (C1.1): mezclar bases aquí reintroduciría en la baja propia la misma
            confusión que ADR-032 corrigió en la del mercado — una baja del 21 %
            que en realidad es el impuesto.
        referencias: `{(tipo, clave): fila de baja_de_referencia}`.

    Los dos ejes se calculan por separado y no combinados: «CPV 7220 en el
    Ayuntamiento de X» tendría casi siempre `n = 1`, y el ítem pide un número
    que se sostenga.
    """
    por_segmento: dict[tuple[str, str], list[float]] = {}
    for fila in ofertas:
        pct = baja_propia_pct(fila.get("presupuesto"), fila.get("offer_price_eur"))
        if pct is None:
            continue
        cpv = str(fila.get("cpv") or "")
        if len(cpv) >= 4:
            por_segmento.setdefault(("cpv4", cpv[:4]), []).append(pct)
        organo = str(fila.get("organo_contratacion") or "").strip()
        if organo:
            por_segmento.setdefault(("organo", organo), []).append(pct)

    salida: list[SegmentoBaja] = []
    for (tipo, clave), valores in sorted(por_segmento.items(), key=lambda kv: -len(kv[1])):
        referencia = referencias.get((tipo, clave)) or {}
        mercado = referencia.get("baja_media_pct")
        n = len(valores)
        salida.append(
            SegmentoBaja(
                segmento=tipo,
                clave=clave,
                n=n,
                baja_propia_pct=(round(sum(valores) / n, 2) if n else None),
                baja_mercado_pct=(float(mercado) if mercado is not None else None),
                contratos_mercado=int(referencia.get("contratos") or 0),
                suficiente=n >= MIN_OFERTAS_POR_SEGMENTO,
            )
        )
    return salida
