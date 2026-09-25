"""F1.5 (cuentas objetivo) y F1.6 (etiquetas de organización).

**Cuentas.** Mercado → Órganos era un corte analítico sin acción: enseñaba
cuánto licita un órgano y no dejaba hacer nada al respecto. Un comercial que
trabaja cuentas —no expedientes— no tenía dónde decir «este cliente me
interesa aunque hoy no publique nada», así que esa lista vivía en su cabeza o
en una hoja aparte, y con ella se iba cuando se iba él.

Una cuenta es el **único** «seguir un órgano» con efectos: avisos de
publicación nueva y de vencimiento (``services/avisos_outbox.py``) y el cruce
de las alertas de competidores (``SegmentoRepository``). Por eso el botón
«Seguir» del panel de órgano de Mercado escribe aquí, igual que el formulario
de /cuentas. ``follows`` admite ``target_type='organo'`` (ADR-031 §A), pero es
de ámbito **personal** y nada lo lee: seguir por ahí no avisaría a nadie, y la
cuenta es una decisión de equipo (ADR-030 §D) que no se puede ir con quien la
creó. Cuando ``follows`` absorba esta tabla (T1), tendrá que saber guardar un
seguimiento de organización.

Una cuenta es un **cliente con uno o varios órganos** (v142), no un órgano:
el Ayuntamiento de Madrid contrata a través de seis y ninguno se llama así.
Un órgano pertenece a una sola cuenta de cada organización; si pudiera estar
en dos, cada publicación suya avisaría dos veces a cada miembro. Hay dos
altas: la de un clic (``organo``: si el órgano ya es de una cuenta, esa
cuenta; ver ``CuentasRepository.follow``) y la de un cliente con varios
órganos (``organos``), que es todo o nada.

La ficha y el resumen enseñan lo que la cuenta tiene hoy —publicaciones,
contratos que vencen con su adjudicatario, oportunidades del equipo— y
declaran en cada bloque su universo y su ventana (ADR-014): el universo
analítico del producto, sin las fuentes regionales que publican el censo
completo de su comunidad, que el criterio de F1.5 prohíbe sumar como censo.

**Etiquetas (D38).** Libres por organización, hasta treinta, con color,
aplicables a favoritos, oportunidades y cuentas. El límite no es decorativo:
por encima de treinta, una taxonomía libre deja de organizar y empieza a
esconder, y el selector se vuelve una lista que hay que leer entera.

Permisos
--------
Crear una cuenta o una etiqueta es escritura de organización: un ``viewer`` no
puede. Se resuelve con ``resolve_organization(..., write=True)``, el mismo
control que el resto de escrituras de equipo, en vez de una comprobación de
rol propia — que sería un segundo sitio donde equivocarse.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from db.repositories.cuentas import (
    CuentasRepository,
    EtiquetasRepository,
    NombreOcupadoError,
    OrganoOcupadoError,
    clave_de_organo,
)
from observability.logging import get_logger
from services.organizations import alcance_resuelto
from shared.dto import (
    AmbitoCifra,
    BloqueOportunidadesCuenta,
    BloquePublicacionesCuenta,
    BloqueVencimientosCuenta,
    CuentaObjetivo,
    CuentaResumen,
    CuentasResumen,
    Etiqueta,
    EtiquetaAplicada,
    FichaCuenta,
    ObjetoEtiquetable,
    OportunidadCuenta,
    OrganoCandidato,
    PublicacionCuenta,
    VencimientoCuenta,
)

log = get_logger(__name__)

_cuentas = CuentasRepository()
_etiquetas = EtiquetasRepository()

#: Tope de etiquetas por organización (D38).
MAX_ETIQUETAS = 30

#: Ventana de «publicaciones recientes» de la ficha.
DIAS_PUBLICACIONES = 90
#: Ventana de vencimientos de la ficha y del resumen. Doce meses y no los seis
#: del aviso: el aviso dice «acaba de entrar», la ficha deja preparar el año.
MESES_VENCIMIENTO = 12
#: Filas por bloque de la ficha; el total de cada bloque va aparte.
FILAS_POR_BLOQUE = 20
#: Mínimo del buscador de órganos, el mismo que la paleta
#: (``services.busqueda_global.MIN_LONGITUD``): con menos, casa media tabla.
MIN_BUSQUEDA_ORGANO = 3
MAX_CANDIDATOS = 20

_UNIVERSO_LICITACIONES = (
    "Licitaciones tecnológicas de los órganos de la cuenta, sin duplicados "
    "confirmados. No suma las fuentes regionales que publican el censo completo "
    "de su comunidad."
)
_UNIVERSO_CONTRATOS = (
    "Contratos adjudicados de los órganos de la cuenta, en el mismo universo que "
    "las licitaciones. Un contrato con varios adjudicatarios cuenta una vez."
)
_UNIVERSO_OPORTUNIDADES = (
    "Oportunidades de tu organización sobre expedientes de los órganos de la cuenta."
)

AMBITO_ABIERTAS = AmbitoCifra(
    universo=_UNIVERSO_LICITACIONES,
    ventana="Plazo de ofertas abierto hoy y expediente no cerrado.",
)
AMBITO_ULTIMA_PUBLICACION = AmbitoCifra(
    universo=_UNIVERSO_LICITACIONES,
    ventana="Día en que se vio por primera vez el expediente más reciente.",
)
AMBITO_VENCEN = AmbitoCifra(
    universo=_UNIVERSO_CONTRATOS,
    ventana=(
        f"Fecha de fin entre hoy y dentro de {MESES_VENCIMIENTO} meses. La mayoría "
        "se estima con la duración del contrato."
    ),
)
AMBITO_OPORTUNIDADES_ACTIVAS = AmbitoCifra(
    universo=_UNIVERSO_OPORTUNIDADES,
    ventana="Las que no están ganadas, perdidas ni retiradas.",
)
AMBITO_PUBLICACIONES = AmbitoCifra(
    universo=_UNIVERSO_LICITACIONES,
    ventana=f"Vistas por primera vez en los últimos {DIAS_PUBLICACIONES} días.",
)
AMBITO_OPORTUNIDADES = AmbitoCifra(
    universo=_UNIVERSO_OPORTUNIDADES,
    ventana="Todas: primero las activas, por la próxima acción que antes vence.",
)

__all__ = [
    "MAX_ETIQUETAS",
    "CuentaNombreOcupadoError",
    "EtiquetaLimiteError",
    "OrganoEnOtraCuentaError",
    "UltimoOrganoError",
    "anadir_organos",
    "aplicar_etiqueta",
    "buscar_organos",
    "crear_cuenta",
    "crear_etiqueta",
    "dejar_de_seguir",
    "dejar_de_seguir_organo",
    "editar_cuenta",
    "etiquetas_de",
    "ficha_cuenta",
    "listar_cuentas",
    "listar_etiquetas",
    "quitar_etiqueta",
    "quitar_organo",
    "resumen_cuentas",
    "seguir_organo",
]


class EtiquetaLimiteError(Exception):
    """La organización llegó al tope de etiquetas de D38."""


class OrganoEnOtraCuentaError(Exception):
    """Algún órgano pedido ya es de otra cuenta de la organización.

    El mensaje nombra la cuenta: «ya está en X» es lo que el usuario necesita
    para decidir si quería añadirlo allí.
    """


class CuentaNombreOcupadoError(Exception):
    """Otra cuenta de la organización ya se llama así."""


class UltimoOrganoError(Exception):
    """Se pidió quitar el único órgano de una cuenta."""


def _sin_repetidos(organos: Sequence[str]) -> list[str]:
    """Los órganos sin repetir clave, en el orden en que llegaron.

    Dos grafías del mismo órgano en una selección chocarían entre sí en la
    unicidad, y la escritura lo diría como si otra cuenta lo tuviera.
    """
    vistos: set[str] = set()
    unicos: list[str] = []
    for organo in organos:
        limpio = organo.strip()
        clave = clave_de_organo(limpio)
        if limpio and clave not in vistos:
            vistos.add(clave)
            unicos.append(limpio)
    return unicos


def _nota(nota: str | None) -> str | None:
    """Una nota en blanco es no tener nota."""
    if nota is None:
        return None
    return nota.strip() or None


def _error_de_ocupados(
    organization_id: int, organos: Sequence[str], *, salvo_cuenta: int | None = None
) -> OrganoEnOtraCuentaError | None:
    """El error que nombra las cuentas que ya tienen alguno de ``organos``."""
    claves = {clave_de_organo(o): o for o in organos}
    ocupados = _cuentas.organos_ocupados(organization_id, list(claves))
    ajenos = {
        clave: duena
        for clave, duena in ocupados.items()
        if salvo_cuenta is None or duena["cuenta_id"] != salvo_cuenta
    }
    if not ajenos:
        return None
    detalle = "; ".join(
        f"«{claves[clave]}» ya está en la cuenta «{duena['cuenta_nombre']}»"
        for clave, duena in sorted(ajenos.items())
    )
    return OrganoEnOtraCuentaError(f"{detalle}. Un órgano sólo puede estar en una cuenta.")


def listar_cuentas(
    user_id: int, *, organization_id: int | None = None, organo: str | None = None
) -> list[CuentaObjetivo]:
    """Las cuentas de la organización; con ``organo``, sólo la que lo contiene.

    El filtro por órgano es la pregunta del botón «Seguir» de Mercado —«¿este
    órgano ya es de una cuenta?»— y devuelve cero o una: un órgano es de una
    sola cuenta por organización. Se contesta aquí y no comparando la lista en
    el cliente porque la identidad del órgano es su nombre plegado, y el
    plegado vive en ``db/``.
    """
    with alcance_resuelto(user_id, organization_id) as (resuelta, _):
        if organo is not None:
            fila = _cuentas.get_by_organo(resuelta, organo)
            return [CuentaObjetivo.model_validate(fila)] if fila else []
        return [CuentaObjetivo.model_validate(f) for f in _cuentas.list_for_organization(resuelta)]


def seguir_organo(
    user_id: int,
    *,
    organo: str,
    nota: str | None = None,
    organization_id: int | None = None,
) -> CuentaObjetivo:
    """Sigue un órgano como cuenta objetivo. Idempotente."""
    with alcance_resuelto(user_id, organization_id, write=True) as (resuelta, _):
        fila = _cuentas.follow(
            organization_id=resuelta, organo_nombre=organo, user_id=user_id, nota=_nota(nota)
        )
        log.info("organo_seguido", organization_id=resuelta)
        return CuentaObjetivo.model_validate(fila)


def crear_cuenta(
    user_id: int,
    *,
    organo: str | None = None,
    organos: Sequence[str] | None = None,
    nombre: str | None = None,
    nota: str | None = None,
    organization_id: int | None = None,
) -> CuentaObjetivo:
    """Alta de una cuenta: el clic de siempre o un cliente con varios órganos.

    Con sólo ``organo`` es :func:`seguir_organo`, idempotente. Con ``organos``
    —o con un ``nombre``, que es decir «esta cuenta es un cliente»— crea una
    cuenta nueva con todos, todo o nada: si alguno ya es de otra cuenta, o si
    otra ya se llama así, no crea nada y el error lo nombra.
    """
    if organo is not None and nombre is None:
        return seguir_organo(user_id, organo=organo, nota=nota, organization_id=organization_id)
    seleccion = _sin_repetidos(list(organos or []) + ([organo] if organo else []))
    if not seleccion:
        raise ValueError("Una cuenta necesita al menos un órgano.")
    nombre_final = (nombre or seleccion[0]).strip()
    with alcance_resuelto(user_id, organization_id, write=True) as (resuelta, _):
        error = _error_de_ocupados(resuelta, seleccion)
        if error is not None:
            raise error
        try:
            fila = _cuentas.crear(
                organization_id=resuelta,
                nombre=nombre_final,
                organos=seleccion,
                user_id=user_id,
                nota=_nota(nota),
            )
        except OrganoOcupadoError as exc:
            # Otra alta se llevó un órgano entre la comprobación y la escritura.
            carrera = _error_de_ocupados(resuelta, seleccion)
            raise carrera or OrganoEnOtraCuentaError(str(exc)) from exc
        if fila is None:
            raise CuentaNombreOcupadoError(
                f"Ya hay una cuenta llamada «{nombre_final}». Añade los órganos a esa "
                "cuenta desde su ficha o elige otro nombre."
            )
        log.info("cuenta_creada", organization_id=resuelta, organos=len(seleccion))
        return CuentaObjetivo.model_validate(fila)


def editar_cuenta(
    user_id: int,
    cuenta_id: int,
    *,
    nombre: str | None = None,
    nota: str | None = None,
    cambiar_nota: bool = False,
    organization_id: int | None = None,
) -> CuentaObjetivo | None:
    """Renombra la cuenta y/o cambia su nota. ``None`` si no es de la organización."""
    with alcance_resuelto(user_id, organization_id, write=True) as (resuelta, _):
        try:
            fila = _cuentas.actualizar(
                organization_id=resuelta,
                cuenta_id=cuenta_id,
                nombre=nombre,
                nota=_nota(nota),
                cambiar_nota=cambiar_nota,
            )
        except NombreOcupadoError as exc:
            raise CuentaNombreOcupadoError(
                f"Ya hay otra cuenta llamada «{(nombre or '').strip()}»."
            ) from exc
        return CuentaObjetivo.model_validate(fila) if fila else None


def anadir_organos(
    user_id: int,
    cuenta_id: int,
    *,
    organos: Sequence[str],
    organization_id: int | None = None,
) -> CuentaObjetivo | None:
    """Añade órganos a una cuenta, todo o nada. ``None`` si la cuenta no existe."""
    seleccion = _sin_repetidos(organos)
    with alcance_resuelto(user_id, organization_id, write=True) as (resuelta, _):
        error = _error_de_ocupados(resuelta, seleccion, salvo_cuenta=cuenta_id)
        if error is not None:
            raise error
        try:
            fila = _cuentas.anadir_organos(
                organization_id=resuelta, cuenta_id=cuenta_id, organos=seleccion, user_id=user_id
            )
        except OrganoOcupadoError as exc:
            carrera = _error_de_ocupados(resuelta, seleccion, salvo_cuenta=cuenta_id)
            raise carrera or OrganoEnOtraCuentaError(str(exc)) from exc
        return CuentaObjetivo.model_validate(fila) if fila else None


def quitar_organo(
    user_id: int,
    cuenta_id: int,
    cuenta_organo_id: int,
    *,
    organization_id: int | None = None,
) -> CuentaObjetivo | None:
    """Quita un órgano de la cuenta. ``None`` si la cuenta o el órgano no son de
    la organización; :class:`UltimoOrganoError` si es el único que tiene."""
    with alcance_resuelto(user_id, organization_id, write=True) as (resuelta, _):
        resultado = _cuentas.quitar_organo(
            organization_id=resuelta, cuenta_id=cuenta_id, cuenta_organo_id=cuenta_organo_id
        )
        if resultado == "ultimo":
            raise UltimoOrganoError(
                "Es el único órgano de la cuenta y una cuenta necesita al menos uno. "
                "Si ya no te interesa, deja de seguir la cuenta."
            )
        if resultado == "no_existe":
            return None
        fila = _cuentas.get(resuelta, cuenta_id)
        return CuentaObjetivo.model_validate(fila) if fila else None


def dejar_de_seguir(user_id: int, cuenta_id: int, *, organization_id: int | None = None) -> bool:
    """Borra la cuenta, sus órganos y sus etiquetas (ver ``CuentasRepository.unfollow``)."""
    with alcance_resuelto(user_id, organization_id, write=True) as (resuelta, _):
        return _cuentas.unfollow(resuelta, cuenta_id)


def dejar_de_seguir_organo(
    user_id: int, organo: str, *, organization_id: int | None = None
) -> bool:
    """La inversa de :func:`seguir_organo`: el clic de Mercado que quita la estrella.

    Quita el órgano de su cuenta y, si era el único, la cuenta entera. ``False``
    si ninguna cuenta de la organización tenía ese órgano. El cliente no puede
    decidir cuál de los órganos de la cuenta es el del botón sin plegar
    nombres, y el plegado vive en ``db/``: por eso la baja va por nombre.
    """
    with alcance_resuelto(user_id, organization_id, write=True) as (resuelta, _):
        resultado = _cuentas.dejar_organo(organization_id=resuelta, organo_nombre=organo)
    if resultado != "no_seguido":
        log.info("organo_dejado", organization_id=resuelta, resultado=resultado)
    return resultado != "no_seguido"


def resumen_cuentas(user_id: int, *, organization_id: int | None = None) -> CuentasResumen:
    """Los cuatro números de cada cuenta, con una fila también para las que
    están a cero: la ausencia de publicaciones es un dato, no un hueco."""
    with alcance_resuelto(user_id, organization_id) as (resuelta, _):
        cuentas = _cuentas.list_for_organization(resuelta)
        agregados = {
            int(f["cuenta_id"]): f
            for f in _cuentas.resumen(resuelta, meses_vencimiento=MESES_VENCIMIENTO)
        }
    filas = [
        CuentaResumen(
            cuenta_id=int(cuenta["id"]),
            abiertas=int(agregados.get(int(cuenta["id"]), {}).get("abiertas", 0)),
            ultima_publicacion=agregados.get(int(cuenta["id"]), {}).get("ultima_publicacion"),
            vencen=int(agregados.get(int(cuenta["id"]), {}).get("vencen", 0)),
            oportunidades_activas=int(
                agregados.get(int(cuenta["id"]), {}).get("oportunidades_activas", 0)
            ),
        )
        for cuenta in cuentas
    ]
    return CuentasResumen(
        filas=filas,
        ambito_abiertas=AMBITO_ABIERTAS,
        ambito_ultima_publicacion=AMBITO_ULTIMA_PUBLICACION,
        ambito_vencen=AMBITO_VENCEN,
        ambito_oportunidades=AMBITO_OPORTUNIDADES_ACTIVAS,
    )


def ficha_cuenta(
    user_id: int, cuenta_id: int, *, organization_id: int | None = None
) -> FichaCuenta | None:
    """La ficha de la cuenta. ``None`` si no es de la organización."""
    with alcance_resuelto(user_id, organization_id) as (resuelta, _):
        cuenta = _cuentas.get(resuelta, cuenta_id)
        if cuenta is None:
            return None
        n_publicaciones, publicaciones = _cuentas.publicaciones_de_cuenta(
            resuelta, cuenta_id, dias=DIAS_PUBLICACIONES, limit=FILAS_POR_BLOQUE
        )
        n_contratos, vencimientos = _cuentas.vencimientos_de_cuenta(
            resuelta, cuenta_id, meses=MESES_VENCIMIENTO, limit=FILAS_POR_BLOQUE
        )
        oportunidades = _cuentas.oportunidades_de_cuenta(
            resuelta, cuenta_id, limit=FILAS_POR_BLOQUE
        )
    items_oportunidades = [OportunidadCuenta.model_validate(o) for o in oportunidades]
    return FichaCuenta(
        cuenta=CuentaObjetivo.model_validate(cuenta),
        publicaciones=BloquePublicacionesCuenta(
            ambito=AMBITO_PUBLICACIONES,
            total=n_publicaciones,
            items=[PublicacionCuenta.model_validate(p) for p in publicaciones],
        ),
        vencimientos=BloqueVencimientosCuenta(
            ambito=AMBITO_VENCEN,
            total=n_contratos,
            items=[VencimientoCuenta.model_validate(v) for v in vencimientos],
        ),
        oportunidades=BloqueOportunidadesCuenta(
            ambito=AMBITO_OPORTUNIDADES,
            activas=sum(1 for o in items_oportunidades if o.activa),
            items=items_oportunidades,
        ),
    )


def buscar_organos(
    user_id: int, q: str, *, organization_id: int | None = None, limite: int = MAX_CANDIDATOS
) -> list[OrganoCandidato]:
    """Órganos para el alta de una cuenta, y de qué cuenta es cada uno ya.

    Con menos de :data:`MIN_BUSQUEDA_ORGANO` caracteres devuelve lista vacía y
    no un error: el campo pregunta en cada tecla.
    """
    termino = q.strip()
    if len(termino) < MIN_BUSQUEDA_ORGANO:
        return []
    with alcance_resuelto(user_id, organization_id) as (resuelta, _):
        filas = _cuentas.buscar_organos(resuelta, termino, max(1, min(limite, MAX_CANDIDATOS)))
    return [OrganoCandidato.model_validate(f) for f in filas]


def listar_etiquetas(user_id: int, *, organization_id: int | None = None) -> list[Etiqueta]:
    with alcance_resuelto(user_id, organization_id) as (resuelta, _):
        return [Etiqueta.model_validate(f) for f in _etiquetas.list_for_organization(resuelta)]


def crear_etiqueta(
    user_id: int, *, nombre: str, color: str, organization_id: int | None = None
) -> tuple[Etiqueta, bool]:
    """``(etiqueta, creada)``. ``creada=False`` si ya existía con ese nombre.

    Devolver la existente en vez de un error es lo correcto para el caso real:
    dos personas etiquetando a la vez «Q4» quieren la misma etiqueta, no un
    conflicto que una de las dos tenga que resolver.
    """
    with alcance_resuelto(user_id, organization_id, write=True) as (resuelta, _):
        # Primero se busca, después se cuenta. Al revés —que es como estaba— una
        # organización con el cupo lleno recibía 409 «llegaste al máximo» al pedir
        # una etiqueta **que ya tenía**: el cupo se aplicaba a una operación que no
        # iba a crear nada. El límite sólo gobierna las altas de verdad.
        existente = _etiquetas.get_by_nombre(resuelta, nombre)
        if existente is not None:
            return Etiqueta.model_validate(existente), False

        if _etiquetas.count(resuelta) >= MAX_ETIQUETAS:
            raise EtiquetaLimiteError(
                f"La organización ya tiene {MAX_ETIQUETAS} etiquetas, que es el máximo. "
                "Borra alguna antes de crear otra."
            )
        fila = _etiquetas.create(
            organization_id=resuelta, nombre=nombre, color=color, user_id=user_id
        )
        if fila is not None:
            return Etiqueta.model_validate(fila), True

        # `create` sólo devuelve vacío por conflicto, así que otra petición ganó la
        # carrera entre el `get_by_nombre` de arriba y este INSERT: la etiqueta
        # existe y es la que el llamante quería. Tampoco aquí es un 409.
        concurrente = _etiquetas.get_by_nombre(resuelta, nombre)
        if concurrente is not None:
            return Etiqueta.model_validate(concurrente), False
        raise EtiquetaLimiteError("No se pudo crear ni recuperar la etiqueta.")


def borrar_etiqueta(user_id: int, etiqueta_id: int, *, organization_id: int | None = None) -> bool:
    with alcance_resuelto(user_id, organization_id, write=True) as (resuelta, _):
        return _etiquetas.delete(resuelta, etiqueta_id)


def aplicar_etiqueta(
    user_id: int,
    *,
    etiqueta_id: int,
    objeto_tipo: ObjetoEtiquetable,
    objeto_id: str,
    organization_id: int | None = None,
) -> bool:
    """Aplica una etiqueta. ``False`` si la etiqueta no es de la organización."""
    with alcance_resuelto(user_id, organization_id, write=True) as (resuelta, _):
        aplicada = _etiquetas.aplicar(
            organization_id=resuelta,
            etiqueta_id=etiqueta_id,
            objeto_tipo=objeto_tipo,
            objeto_id=objeto_id,
            user_id=user_id,
        )
        if aplicada:
            log.info("etiqueta_aplicada", objeto=objeto_tipo)
        return aplicada


def quitar_etiqueta(
    user_id: int,
    *,
    etiqueta_id: int,
    objeto_tipo: ObjetoEtiquetable,
    objeto_id: str,
    organization_id: int | None = None,
) -> bool:
    with alcance_resuelto(user_id, organization_id, write=True) as (resuelta, _):
        return _etiquetas.quitar(
            organization_id=resuelta,
            etiqueta_id=etiqueta_id,
            objeto_tipo=objeto_tipo,
            objeto_id=objeto_id,
        )


def etiquetas_de(
    user_id: int,
    *,
    objeto_tipo: ObjetoEtiquetable,
    objeto_ids: list[str],
    organization_id: int | None = None,
) -> dict[str, list[EtiquetaAplicada]]:
    """Las etiquetas de varios objetos, para pintar una lista de una vez."""
    with alcance_resuelto(user_id, organization_id) as (resuelta, _):
        crudo: dict[str, list[dict[str, Any]]] = _etiquetas.por_objeto(
            resuelta, objeto_tipo, objeto_ids
        )
        return {
            objeto: [EtiquetaAplicada.model_validate(e) for e in etiquetas]
            for objeto, etiquetas in crudo.items()
        }


# ── F6.4: plantillas de organización ────────────────────────────────────────


def aplicar_plantillas(organization_id: int, user_id: int) -> int:
    """Copia las plantillas de la organización a un miembro recién activado.

    Devuelve cuántas copias creó; **0 si ya se le habían aplicado**.

    La idempotencia la da la clave única de ``plantillas_aplicadas`` y no una
    comprobación previa: entre un ``SELECT`` y un ``INSERT`` caben dos
    activaciones simultáneas de la misma membresía, y el resultado serían las
    reglas duplicadas que F6.4 dice explícitamente que no puede haber.

    Se copian **contenidos, no referencias**: el miembro puede borrar lo suyo
    sin tocar la plantilla y editarlo sin que cambie para los demás. Con
    referencias pasaría lo contrario, que es justo lo que F6.4 descarta.

    Un fallo copiando una plantilla no aborta las demás: es mejor que el
    miembro entre con tres de sus cuatro reglas que con ninguna, y el log deja
    cuál falló.
    """
    from db.repositories.cartera import PlantillasRepository

    repo = PlantillasRepository()
    if not repo.reservar_aplicacion(organization_id, user_id):
        log.info("plantillas_ya_aplicadas", organization_id=organization_id)
        return 0

    copias = 0
    for plantilla in repo.list_for_organization(organization_id):
        tipo = str(plantilla.get("tipo") or "")
        contenido = plantilla.get("contenido") or {}
        try:
            if tipo == "etiqueta":
                # Las etiquetas son de la organización, no del miembro: no se
                # copian, ya las tiene. Se cuenta para que el número refleje lo
                # que la plantilla cubre.
                copias += 1
            elif tipo in ("regla", "vista"):
                _copiar_para_miembro(tipo, contenido, organization_id, user_id)
                copias += 1
        except Exception as exc:
            log.warning(
                "plantilla_no_copiada",
                tipo=tipo,
                organization_id=organization_id,
                error=str(exc)[:200],
            )

    repo.registrar_copias(organization_id, user_id, copias)
    log.info("plantillas_aplicadas", organization_id=organization_id, copias=copias)
    return copias


def _copiar_para_miembro(
    tipo: str, contenido: dict[str, Any], organization_id: int, user_id: int
) -> None:
    """Materializa una plantilla como objeto propio del miembro.

    Está separado del bucle para que el `try` de arriba envuelva una unidad
    entera: media plantilla copiada sería peor que ninguna.
    """
    from db.users import get_user_by_id
    from shared.identity import user_key_from_email

    usuario = get_user_by_id(user_id)
    email = str((usuario or {}).get("email") or "")
    if not email:
        raise ValueError("El miembro no tiene email: no hay clave de usuario a la que copiar.")
    user_key = user_key_from_email(email, user_id)

    if tipo == "regla":
        from services.watchlist_rules import WatchlistRule, create_rule

        create_rule(
            user_key,
            WatchlistRule(**contenido),
            user_id=user_id,
            organization_id=organization_id,
            # `private`: la copia es **del miembro**, no de la organización.
            # Con `organization` la vería todo el equipo y editarla se la
            # cambiaría a los demás, que es lo contrario de lo que F6.4 pide.
            visibility="private",
        )
    elif tipo == "vista":
        from services.saved_filters import save_filter

        save_filter(
            user_key,
            str(contenido.get("nombre") or "Vista del equipo"),
            json.dumps(contenido.get("criterio") or {}, ensure_ascii=False),
            organization_id,
            user_id=user_id,
        )
