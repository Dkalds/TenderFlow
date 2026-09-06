"""F6.1 — de qué mercado hablamos: perfil personal, organización, o nada.

El ámbito estaba partido en dos sitios sin que nadie declarara cuál manda.
CPVs, importe y keywords vivían en el perfil **personal**
(``api/routes/me.py``); las tecnologías, en la organización
(``OrganizationSettings.tecnologias``). Consecuencia práctica: cada miembro
nuevo tenía que reconfigurar a mano lo que su equipo ya había decidido, y
quien no lo hacía veía el mercado entero — el Radar puntuando obras públicas
para una consultora de SAP.

La regla, escrita una vez
-------------------------
**Perfil personal → organización → global**, campo a campo. Un campo que el
usuario ha fijado gana; si no lo ha fijado, gana el de la organización; si
tampoco, no hay restricción. No es «el perfil personal completo o el de la
organización completo»: alguien puede querer el rango de importe del equipo y
sus propios CPVs, y obligarle a elegir entre los dos bloques enteros le hace
copiar a mano lo que no quería cambiar.

Qué significa vacío
-------------------
**Sin restricción**, nunca «ninguno». Es la única lectura segura: si una lista
vacía significara «no quiero nada», guardar la configuración sin tocar un
campo vaciaría el Radar en silencio, y el usuario no tendría forma de
distinguir «no hay licitaciones» de «me he cortado el mercado sin querer».

El Radar declara qué capa está aplicando (``nivel``) para que la cabecera
pueda decir «ámbito: tu perfil» o «ámbito: organización», como ya hace con el
alcance.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from shared.dto import OrganizationSettings

__all__ = ["AmbitoMercado", "NivelAmbito", "resolver_ambito"]

#: Qué capa aportó el valor de un campo. ``mixto`` es un ámbito donde unos
#: campos vienen del perfil y otros de la organización, que es el caso normal
#: en cuanto alguien personaliza una cosa.
NivelAmbito = Literal["personal", "organizacion", "mixto", "global"]


@dataclass(frozen=True, slots=True)
class AmbitoMercado:
    """El ámbito efectivo, con la procedencia de cada campo."""

    tecnologias: list[str] = field(default_factory=list)
    cpvs: list[str] = field(default_factory=list)
    ccaas: list[str] = field(default_factory=list)
    importe_min: float | None = None
    importe_max: float | None = None
    tipos_organo: list[str] = field(default_factory=list)
    procedimientos_excluidos: list[str] = field(default_factory=list)
    #: ``{campo: "personal" | "organizacion"}`` sólo para los campos con valor.
    #: Es lo que permite a la UI explicar de dónde sale cada restricción sin
    #: que el backend tenga que mandar las dos capas enteras.
    procedencia: dict[str, str] = field(default_factory=dict)

    @property
    def nivel(self) -> NivelAmbito:
        """La capa que domina, para la cabecera del Radar."""
        capas = set(self.procedencia.values())
        if not capas:
            return "global"
        if capas == {"personal"}:
            return "personal"
        if capas == {"organizacion"}:
            return "organizacion"
        return "mixto"

    @property
    def vacio(self) -> bool:
        """``True`` si no hay ninguna restricción activa."""
        return not self.procedencia


def _primera_lista(
    campo: str,
    personal: Any,
    organizacion: Any,
    procedencia: dict[str, str],
) -> list[str]:
    """La lista del perfil si tiene algo; si no, la de la organización."""
    if isinstance(personal, list) and personal:
        procedencia[campo] = "personal"
        return [str(v) for v in personal]
    if isinstance(organizacion, list) and organizacion:
        procedencia[campo] = "organizacion"
        return [str(v) for v in organizacion]
    return []


def _primer_numero(
    campo: str,
    personal: Any,
    organizacion: Any,
    procedencia: dict[str, str],
) -> float | None:
    """El número del perfil si está fijado; si no, el de la organización.

    ``None`` y ``0`` no son lo mismo: un ``importe_min`` de 0 es una decisión
    («me valen todos») y tiene que ganar sobre el de la organización, así que
    la comprobación es contra ``None`` y no contra la falsedad del valor.
    """
    if personal is not None:
        procedencia[campo] = "personal"
        return float(personal)
    if organizacion is not None:
        procedencia[campo] = "organizacion"
        return float(organizacion)
    return None


def resolver_ambito(
    perfil: dict[str, Any] | None,
    ajustes: OrganizationSettings | None,
) -> AmbitoMercado:
    """Combina las dos capas campo a campo y devuelve el ámbito efectivo.

    ``perfil`` es la fila de ``user_profiles`` tal como la devuelve el
    repositorio (o ``None`` si el usuario no tiene). ``ajustes`` es la
    configuración de la organización (o ``None`` fuera de una).

    Las tecnologías sólo existen en la organización y los procedimientos
    excluidos y tipos de órgano también: el perfil personal no los tiene, así
    que para ellos la precedencia es trivial. Se resuelven por el mismo camino
    para que el día que el perfil los incorpore no haya que acordarse de nada.
    """
    p = perfil or {}
    org = ajustes or OrganizationSettings()
    procedencia: dict[str, str] = {}

    return AmbitoMercado(
        tecnologias=_primera_lista(
            "tecnologias", p.get("tecnologias"), org.tecnologias, procedencia
        ),
        cpvs=_primera_lista("cpvs", p.get("cpvs"), org.cpvs, procedencia),
        ccaas=_primera_lista("ccaas", p.get("ccaas"), org.ccaas, procedencia),
        importe_min=_primer_numero(
            "importe_min", p.get("importe_min"), org.importe_min, procedencia
        ),
        importe_max=_primer_numero(
            "importe_max", p.get("importe_max"), org.importe_max, procedencia
        ),
        tipos_organo=_primera_lista(
            "tipos_organo", p.get("tipos_organo"), org.tipos_organo, procedencia
        ),
        procedimientos_excluidos=_primera_lista(
            "procedimientos_excluidos",
            p.get("procedimientos_excluidos"),
            org.procedimientos_excluidos,
            procedencia,
        ),
        procedencia=procedencia,
    )
