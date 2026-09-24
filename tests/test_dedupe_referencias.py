"""Dedupe por referencia explícita: TED frente a la plataforma del comprador.

El mismo contrato llegaba dos veces —de PLACSP (o PSCP) y de TED— y ninguno de
los dos detectores anteriores podía verlo: el expediente natural de una fila TED
es su ``publication-number``, y su título llevaba el prefijo «España \u2013 {CPV} \u2013 ».
``detect_duplicados_por_referencia`` empareja por lo que el propio aviso TED
publica del expediente original: el ``idEvl`` del deeplink de PLACSP y BT-22.

Los casos de abajo salen de datos reales medidos el 2026-09-24 (ver el bloque
de comentario de ``services/dedupe.py``): el ADIF que solo coincide en título,
los «01/2026» que comparten decenas de órganos, el «X - X» de Euskadi.

Todos corren sin Postgres: el repositorio se dobla, como en los tests del
detector de reemisiones (``tests/test_dedupe_publico.py``). El recorrido real
contra la base está en ``test_integration_*`` al final.
"""

from __future__ import annotations

import re
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

import services.dedupe as sd
from db.repositories import publico as publico_mod
from db.sql_fragments import exclude_duplicados_presentacion_sql
from services.dedupe import (
    ReferenciaCruzada,
    _elegir_canonica_por_referencia,
    _es_placsp,
    _organo_emparejable,
    id_evl_de_url,
)

_DEEPLINK = "https://contrataciondelestado.es/wps/poc?uri=deeplink:detalle_licitacion&idEvl="


def _placsp(id_externo: str, **campos: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id_externo": id_externo,
        "fuente": "placsp",
        "organo_contratacion": "Jefatura de Asuntos Económicos del Mando de Apoyo Logístico",
        "titulo": "Suministro de licencias de software de gestión documental",
        "cpv": "48000000",
        "url": f"{_DEEPLINK}CEGLc1%2Fkxg%2FE6P%2FuLemXRw%3D%3D",
        "fecha_publicacion": "2026-09-08",
        "primera_extraccion": "2026-09-08T10:00:00+00:00",
        "fecha_extraccion": "2026-09-24T10:00:00+00:00",
    }
    base.update(campos)
    return base


def _ted(id_externo: str = "ted:533989-2026", **campos: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id_externo": id_externo,
        "fuente": "ted",
        "organo_contratacion": "Jefatura de Asuntos Económicos del Mando de Apoyo Logístico",
        "titulo": "Suministro de licencias de software de gestión documental",
        "cpv": "48000000",
        "fecha_publicacion": "2026-09-12",
        "primera_extraccion": "2026-09-12T10:00:00+00:00",
        "fecha_extraccion": "2026-09-24T10:00:00+00:00",
    }
    base.update(campos)
    return base


def _indices(
    candidatas: list[dict[str, Any]],
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, list[dict[str, Any]]]]:
    """Los dos índices que construye el detector, a partir de las candidatas."""
    por_evl: dict[str, list[dict[str, Any]]] = {}
    por_expediente: dict[str, list[dict[str, Any]]] = {}
    for c in candidatas:
        if (evl := id_evl_de_url(c.get("url"))) is not None:
            por_evl.setdefault(evl, []).append(c)
        por_expediente.setdefault(sd.natural_expediente(c["id_externo"]), []).append(c)
    return por_evl, por_expediente


def _elegir(
    fila: dict[str, Any], ref: ReferenciaCruzada, candidatas: list[dict[str, Any]]
) -> tuple[str, str] | None:
    por_evl, por_expediente = _indices(candidatas)
    elegida = _elegir_canonica_por_referencia(
        fila, ref, por_id_evl=por_evl, por_expediente=por_expediente
    )
    return None if elegida is None else (elegida[0]["id_externo"], elegida[1])


# ---------------------------------------------------------------------------
# idEvl
# ---------------------------------------------------------------------------


def test_id_evl_se_decodifica_en_cualquier_capitalizacion_del_escape() -> None:
    """PLACSP escribe ``%2F`` y el aviso TED que lo copia a veces ``%2f``."""
    esperado = "CEGLc1/kxg/E6P/uLemXRw=="

    assert id_evl_de_url(f"{_DEEPLINK}CEGLc1%2Fkxg%2FE6P%2FuLemXRw%3D%3D") == esperado
    assert id_evl_de_url(f"{_DEEPLINK}CEGLc1%2fkxg%2fE6P%2fuLemXRw%3d%3d") == esperado
    assert id_evl_de_url(f"{_DEEPLINK}CEGLc1/kxg/E6P/uLemXRw==") == esperado


def test_id_evl_conserva_el_mas_del_base64() -> None:
    """``+`` es un carácter del base64, no un espacio: ``unquote`` y no ``unquote_plus``."""
    assert id_evl_de_url(f"{_DEEPLINK}wRGD%2BGZ") == "wRGD+GZ"
    assert id_evl_de_url(f"{_DEEPLINK}wRGD+GZ") == "wRGD+GZ"


def test_id_evl_ignora_urls_sin_deeplink() -> None:
    assert id_evl_de_url("https://ted.europa.eu/es/notice/371218-2026/pdf") is None
    assert id_evl_de_url("https://contractaciopublica.cat/ca/perfils/detall/12628397") is None
    assert id_evl_de_url(f"{_DEEPLINK}") is None
    assert id_evl_de_url(None) is None
    # El nombre del parámetro no distingue mayúsculas; el fragmento no cuenta.
    assert id_evl_de_url("https://x.es/poc?IDEVL=abc%3D#frag") == "abc="


# ---------------------------------------------------------------------------
# Elección de la canónica
# ---------------------------------------------------------------------------


def test_el_id_evl_basta_aunque_el_organo_no_coincida() -> None:
    """``idEvl`` identifica el expediente de PLACSP sin ambigüedad."""
    fila = _ted(organo_contratacion="Ministerio de Defensa", titulo="Otro título")
    ref = ReferenciaCruzada(id_evl="CEGLc1/kxg/E6P/uLemXRw==")

    assert _elegir(fila, ref, [_placsp("2025/ETSAE0906/00006072E")]) == (
        "2025/ETSAE0906/00006072E",
        "idEvl:CEGLc1/kxg/E6P/uLemXRw==",
    )


def test_bt22_con_el_mismo_organo_empareja() -> None:
    """Dentro de un órgano el número de expediente no se repite."""
    ref = ReferenciaCruzada(expediente="2025/ETSAE0906/00006072E")
    canonica = _placsp("2025/ETSAE0906/00006072E", url=None)

    assert _elegir(_ted(titulo="Título que TED reescribió"), ref, [canonica]) == (
        "2025/ETSAE0906/00006072E",
        "expediente:2025/ETSAE0906/00006072E",
    )


def test_bt22_con_el_mismo_titulo_empareja_aunque_el_organo_se_escriba_distinto() -> None:
    """El único par verdadero con órgano distinto de la muestra real."""
    ref = ReferenciaCruzada(expediente="3.26/27506.0027")
    adif = _placsp(
        "3.26/27506.0027",
        organo_contratacion="ADIF - Presidencia",
        titulo="Servicio de mantenimiento de los sistemas de información de circulación",
        url=None,
    )
    fila = _ted(
        organo_contratacion="Administrador de Infraestructuras Ferroviarias",
        titulo="Servicio de mantenimiento de los sistemas de información de circulación",
    )

    assert _elegir(fila, ref, [adif]) is not None


def test_bt22_generico_de_otro_organo_no_empareja() -> None:
    """«01/2026» lo comparten decenas de órganos: BT-22 solo, sin más, es basura."""
    ref = ReferenciaCruzada(expediente="01/2026")
    tenerife = _placsp(
        "01/2026",
        organo_contratacion="Consejo de Administración de Spet, Turismo de Tenerife, S.A.",
        titulo="Servicio de promoción turística en ferias internacionales",
        url=None,
    )
    fila = _ted(
        organo_contratacion="Mesa del Senado",
        titulo="Suministro de licencias de ciberseguridad",
    )

    assert _elegir(fila, ref, [tenerife]) is None


def test_un_id_evl_distinto_no_se_rescata_por_bt22_de_otro_organo() -> None:
    """Cada discrepancia de ``idEvl`` medida era un falso positivo de BT-22."""
    ref = ReferenciaCruzada(expediente="01/2026", id_evl="OTRO/idEvl==")
    tenerife = _placsp(
        "01/2026",
        organo_contratacion="Consejo de Administración de Spet, Turismo de Tenerife, S.A.",
        titulo="Servicio de promoción turística en ferias internacionales",
    )

    assert _elegir(_ted(organo_contratacion="Mesa del Senado"), ref, [tenerife]) is None


def test_ted_nunca_es_la_canonica() -> None:
    """Aunque otra fila TED comparta referencia, no representa al contrato.

    El caso real: el aviso de licitación y el de adjudicación de TED copian el
    mismo deeplink de PLACSP. La consulta ya excluye TED, pero la regla es de
    dominio y se comprueba también aquí.
    """
    ref = ReferenciaCruzada(id_evl="CEGLc1/kxg/E6P/uLemXRw==")
    otra_ted = _ted("ted:111-2026", url=f"{_DEEPLINK}CEGLc1%2Fkxg%2FE6P%2FuLemXRw%3D%3D")

    assert _elegir(_ted("ted:222-2026"), ref, [otra_ted]) is None
    # Y la propia fila tampoco puede ser su canónica.
    propia = _ted("ted:222-2026", url=f"{_DEEPLINK}CEGLc1%2Fkxg%2FE6P%2FuLemXRw%3D%3D")
    propia["fuente"] = "placsp"
    assert _elegir(_ted("ted:222-2026"), ref, [propia]) is None


def test_placsp_gana_a_pscp_y_el_bulk_cuenta_como_placsp() -> None:
    """PLACSP entra con dos etiquetas; ``_rango_canonico`` solo reconocía una."""
    ref = ReferenciaCruzada(expediente="EXP-7")
    pscp = _placsp("pscp:EXP-7", fuente="pscp", url=None, fecha_publicacion="2020-01-01")
    bulk = _placsp("EXP-7", fuente="bulk_202609", url=None, fecha_publicacion="2026-09-01")

    assert _elegir(_ted(), ref, [pscp, bulk]) == ("EXP-7", "expediente:EXP-7")
    assert _elegir(_ted(), ref, [bulk, pscp]) == ("EXP-7", "expediente:EXP-7")
    assert _es_placsp("placsp") and _es_placsp("bulk_202609")
    assert not _es_placsp("pscp") and not _es_placsp("ted") and not _es_placsp(None)


def test_la_eleccion_no_depende_del_orden_de_las_candidatas() -> None:
    ref = ReferenciaCruzada(expediente="EXP-9")
    a = _placsp("pscp:EXP-9", fuente="pscp", url=None, fecha_publicacion="2026-02-01")
    b = _placsp("galicia_rss:EXP-9", fuente="galicia_rss", url=None, fecha_publicacion="2026-01-01")

    assert _elegir(_ted(), ref, [a, b]) == _elegir(_ted(), ref, [b, a])
    assert _elegir(_ted(), ref, [a, b]) == ("galicia_rss:EXP-9", "expediente:EXP-9")


def test_el_comprador_repetido_de_euskadi_se_colapsa() -> None:
    """Los avisos que vienen de la plataforma vasca traen «X - X»."""
    assert _organo_emparejable("Bomberos Forales de Álava - Bomberos Forales de Álava") == (
        _organo_emparejable("Bomberos Forales de Álava")
    )
    # Un guion que separa dos cosas distintas no se toca.
    assert _organo_emparejable("ADIF - Presidencia") != _organo_emparejable("ADIF")
    assert _organo_emparejable(None) is None


# ---------------------------------------------------------------------------
# El detector con el repositorio doblado
# ---------------------------------------------------------------------------


def _correr(
    filas_ted: list[dict[str, Any]],
    candidatas: list[dict[str, Any]],
    referencias: dict[str, ReferenciaCruzada],
) -> tuple[sd.DedupeResult, list[Any], MagicMock]:
    marcas: list[Any] = []
    with (
        patch.object(sd.dedupe_repo, "filas_por_id", return_value=filas_ted) as filas_por_id,
        patch.object(
            sd.dedupe_repo, "iter_candidatas_por_referencia", return_value=iter(candidatas)
        ) as candidatas_mock,
        patch.object(sd.dedupe_repo, "marcar_duplicados_por_referencia", side_effect=marcas.extend),
    ):
        resultado = sd.detect_duplicados_por_referencia(fuente="ted", referencias=referencias)
    filas_por_id.assert_called_once()
    return resultado, marcas, candidatas_mock


def test_el_detector_marca_confirmed_la_fila_ted_contra_la_de_placsp() -> None:
    """``confirmed``: la retira también de la cuota de mercado, que la contaba doble."""
    fila = _ted()
    ref = ReferenciaCruzada(
        expediente="2025/ETSAE0906/00006072E", id_evl="CEGLc1/kxg/E6P/uLemXRw=="
    )

    resultado, marcas, _ = _correr(
        [fila], [_placsp("2025/ETSAE0906/00006072E")], {fila["id_externo"]: ref}
    )

    assert marcas == [
        (
            "ted:533989-2026",
            "2025/ETSAE0906/00006072E",
            "idEvl:CEGLc1/kxg/E6P/uLemXRw==",
            1.0,
            "confirmed",
        )
    ]
    assert (resultado.evaluadas, resultado.confirmados, resultado.pendientes) == (1, 1, 0)


def test_el_detector_pide_solo_las_referencias_de_la_pasada() -> None:
    """El índice se acota a lo que puede emparejar, como en los otros dos detectores."""
    refs = {
        "ted:1": ReferenciaCruzada(expediente="EXP-B", id_evl="evl/2=="),
        "ted:2": ReferenciaCruzada(expediente="EXP-A"),
    }

    _, _, candidatas_mock = _correr([], [], refs)

    candidatas_mock.assert_called_once_with("ted", ["EXP-A", "EXP-B"], ["evl/2=="])


def test_sin_referencias_el_detector_no_toca_la_base() -> None:
    with (
        patch.object(sd.dedupe_repo, "filas_por_id") as filas_por_id,
        patch.object(sd.dedupe_repo, "iter_candidatas_por_referencia") as candidatas,
        patch.object(sd.dedupe_repo, "marcar_duplicados_por_referencia") as marcar,
    ):
        resultado = sd.detect_duplicados_por_referencia(
            fuente="ted", referencias={"ted:1": ReferenciaCruzada()}
        )

    assert resultado.evaluadas == 0
    filas_por_id.assert_not_called()
    candidatas.assert_not_called()
    marcar.assert_not_called()


def test_una_fila_ted_sin_gemela_se_evalua_y_no_se_marca() -> None:
    fila = _ted()

    resultado, marcas, _ = _correr(
        [fila], [], {fila["id_externo"]: ReferenciaCruzada(expediente="SIN-GEMELA")}
    )

    assert marcas == []
    assert (resultado.evaluadas, resultado.confirmados) == (1, 0)


# ---------------------------------------------------------------------------
# El SQL del repositorio, capturado en la frontera
# ---------------------------------------------------------------------------


def _normalizar(sql: str) -> str:
    return re.sub(r"\s+", " ", sql).strip()


def _capturar_candidatas(expedientes: list[str], id_evls: list[str]) -> tuple[str, list[Any]]:
    from db.repositories import dedupe as dedupe_repo

    capturado: dict[str, Any] = {}

    def _execute(sql: str, params: Any = None) -> MagicMock:
        capturado["sql"] = sql
        capturado["params"] = list(params) if params is not None else []
        cursor = MagicMock()
        cursor.description = [("id_externo",)]
        cursor.fetchall.return_value = []
        return cursor

    ctx = MagicMock()
    ctx.__enter__.return_value.execute.side_effect = _execute
    with patch("db.repositories.dedupe.connect_read", return_value=ctx):
        assert list(dedupe_repo.iter_candidatas_por_referencia("ted", expedientes, id_evls)) == []
    return capturado["sql"], capturado["params"]


@pytest.mark.parametrize(
    ("expedientes", "id_evls"),
    [(["EXP-1"], ["evl=="]), (["EXP-1"], []), ([], ["evl=="])],
)
def test_las_candidatas_siguen_visibles_y_los_placeholders_cuadran(
    expedientes: list[str], id_evls: list[str]
) -> None:
    """La canónica tiene que quedarse publicada y sin marca de duplicado.

    Si no, esconder la fila TED podía llevarse el contrato entero —la gemela no
    se publica— o cerrar un ciclo de dos filas escondiéndose mutuamente.
    """
    sql, params = _capturar_candidatas(expedientes, id_evls)
    normalizado = _normalizar(sql)

    assert _normalizar(publico_mod._publicable_sql("l")) in normalizado
    assert exclude_duplicados_presentacion_sql("l.id_externo") in normalizado
    assert "l.fuente <> %s" in normalizado
    assert params[0] == "ted"
    assert sql.count("%s") == len(params)
    # Un `%` literal sin duplicar rompería psycopg: los escapes van con chr(37).
    assert "%" not in sql.replace("%s", "")


def test_sin_nada_que_buscar_las_candidatas_no_tocan_la_base() -> None:
    from db.repositories import dedupe as dedupe_repo

    with patch("db.repositories.dedupe.connect_read") as conectar:
        assert list(dedupe_repo.iter_candidatas_por_referencia("ted", [], [])) == []

    conectar.assert_not_called()


def test_el_marcado_solo_promueve_lo_pendiente_sin_resolver() -> None:
    """Lo que un humano resolvió —``confirmed`` o ``rejected``— no se reescribe."""
    from db.repositories import dedupe as dedupe_repo

    ctx = MagicMock()
    with patch("db.repositories.dedupe.connect", return_value=ctx):
        dedupe_repo.marcar_duplicados_por_referencia([("ted:1", "EXP-1", "k", 1.0, "confirmed")])

    sql = _normalizar(ctx.__enter__.return_value.executemany.call_args.args[0])
    assert "ON CONFLICT(licitacion_id) DO UPDATE" in sql
    assert "WHERE licitaciones_duplicados.status = 'pending'" in sql
    assert "licitaciones_duplicados.resolved_at IS NULL" in sql


# ---------------------------------------------------------------------------
# Enganche en el runner de conectores
# ---------------------------------------------------------------------------


def _post_ingestion(**kwargs: Any) -> MagicMock:
    from scraper.connectors.base import _post_ingestion as post

    with (
        patch("services.entity_resolution.resolve_all_unlinked"),
        patch("services.dedupe.detect_duplicates"),
        patch("services.dedupe.detect_duplicados_por_referencia") as por_referencia,
        patch("services.contract_events.derive_new_events"),
        patch("shared.cache_signal.signal_cache_invalidation"),
    ):
        post("ted", **kwargs)
    return por_referencia


def test_el_runner_pasa_las_referencias_al_detector() -> None:
    refs = {"ted:1": ReferenciaCruzada(expediente="EXP-1")}

    por_referencia = _post_ingestion(referencias=refs)

    por_referencia.assert_called_once_with(fuente="ted", referencias=refs)


def test_sin_referencias_el_runner_no_llama_al_detector() -> None:
    assert _post_ingestion().call_count == 0
    assert _post_ingestion(referencias={}).call_count == 0


def test_un_conector_sin_referencias_o_que_falla_al_darlas_no_rompe_nada() -> None:
    from scraper.connectors.base import _referencias_de

    class _SinMetodo:
        source_id = "fake"

    class _QueFalla:
        source_id = "fake"

        def referencias_cruzadas(self) -> dict[str, ReferenciaCruzada]:
            raise RuntimeError("roto")

    assert _referencias_de(_SinMetodo()) == {}
    assert _referencias_de(_QueFalla()) == {}


# ---------------------------------------------------------------------------
# Recorrido real contra Postgres
# ---------------------------------------------------------------------------


@pytest.fixture()
def db(tmp_db):
    db_mod, _ = tmp_db
    return db_mod


def _insertar(c: Any, fila: dict[str, Any], *, importe: float | None = 120000.0) -> None:
    c.execute(
        "INSERT INTO licitaciones (id_externo, titulo, organo_contratacion, cpv, importe, url, "
        " fecha_publicacion, fuente, fecha_extraccion) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (
            fila["id_externo"],
            fila["titulo"],
            fila["organo_contratacion"],
            fila["cpv"],
            importe,
            fila.get("url"),
            fila["fecha_publicacion"],
            fila["fuente"],
            fila["fecha_extraccion"],
        ),
    )


def _marca(c: Any, licitacion_id: str) -> tuple[Any, ...] | None:
    fila = c.execute(
        "SELECT canonical_id, status FROM licitaciones_duplicados WHERE licitacion_id = %s",
        (licitacion_id,),
    ).fetchone()
    return tuple(fila) if fila else None


def test_integration_ted_queda_fuera_de_la_metrica_y_la_canonica_es_placsp(db) -> None:
    from db.database import connect, connect_read
    from services.dedupe import detect_duplicados_por_referencia, exclude_duplicados_sql

    placsp = _placsp("2025/ETSAE0906/00006072E")
    ted = _ted(url=placsp["url"])
    with connect() as c:
        _insertar(c, placsp)
        _insertar(c, ted)

    resultado = detect_duplicados_por_referencia(
        fuente="ted",
        referencias={ted["id_externo"]: ReferenciaCruzada(id_evl="CEGLc1/kxg/E6P/uLemXRw==")},
    )

    assert resultado.confirmados == 1
    with connect_read() as c:
        assert _marca(c, ted["id_externo"]) == ("2025/ETSAE0906/00006072E", "confirmed")
        sql = f"SELECT id_externo FROM licitaciones l WHERE {exclude_duplicados_sql()}"  # noqa: S608
        assert {r[0] for r in c.execute(sql).fetchall()} == {"2025/ETSAE0906/00006072E"}

    # Idempotente: reejecutar no reescribe ni duplica nada.
    detect_duplicados_por_referencia(
        fuente="ted",
        referencias={ted["id_externo"]: ReferenciaCruzada(id_evl="CEGLc1/kxg/E6P/uLemXRw==")},
    )
    with connect_read() as c:
        assert c.execute("SELECT COUNT(*) FROM licitaciones_duplicados").fetchone()[0] == 1


def test_integration_el_escape_en_minusculas_tambien_empareja(db) -> None:
    """El prefiltro SQL deshace ``%2f``/``%3d`` igual que ``unquote`` en Python."""
    from db.database import connect, connect_read
    from services.dedupe import detect_duplicados_por_referencia

    placsp = _placsp("EXP-MIN", url=f"{_DEEPLINK}CEGLc1%2fkxg%2fE6P%2fuLemXRw%3d%3d")
    ted = _ted()
    with connect() as c:
        _insertar(c, placsp)
        _insertar(c, ted)

    detect_duplicados_por_referencia(
        fuente="ted",
        referencias={ted["id_externo"]: ReferenciaCruzada(id_evl="CEGLc1/kxg/E6P/uLemXRw==")},
    )

    with connect_read() as c:
        assert _marca(c, ted["id_externo"]) == ("EXP-MIN", "confirmed")


def test_integration_no_se_esconde_ted_tras_una_gemela_que_no_se_publica(db) -> None:
    """Sin importe ni descripción la gemela no supera el umbral de sustancia."""
    from db.database import connect, connect_read
    from services.dedupe import detect_duplicados_por_referencia

    placsp = _placsp("EXP-POBRE")
    ted = _ted()
    with connect() as c:
        _insertar(c, placsp, importe=None)
        _insertar(c, ted)

    detect_duplicados_por_referencia(
        fuente="ted", referencias={ted["id_externo"]: ReferenciaCruzada(expediente="EXP-POBRE")}
    )

    with connect_read() as c:
        assert _marca(c, ted["id_externo"]) is None


def test_integration_una_gemela_ya_escondida_no_puede_ser_canonica(db) -> None:
    """Si la gemela ya está marcada, las dos quedarían escondidas: ciclo."""
    from db.database import connect, connect_read
    from services.dedupe import detect_duplicados_por_referencia

    placsp = _placsp("EXP-CICLO")
    ted = _ted()
    with connect() as c:
        _insertar(c, placsp)
        _insertar(c, ted)
        c.execute(
            "INSERT INTO licitaciones_duplicados (licitacion_id, canonical_id, clave_match, "
            " confianza, status) VALUES (%s, %s, 'republicacion', 0.8, 'pending')",
            ("EXP-CICLO", ted["id_externo"]),
        )

    detect_duplicados_por_referencia(
        fuente="ted", referencias={ted["id_externo"]: ReferenciaCruzada(expediente="EXP-CICLO")}
    )

    with connect_read() as c:
        assert _marca(c, ted["id_externo"]) is None


def test_integration_promueve_la_marca_pendiente_y_respeta_la_rechazada(db) -> None:
    from db.database import connect, connect_read
    from services.dedupe import detect_duplicados_por_referencia, resolve_pending

    placsp = _placsp("EXP-P")
    ted_pendiente = _ted("ted:1-2026")
    ted_rechazada = _ted("ted:2-2026")
    otra_ted = _ted("ted:0-2026", fecha_publicacion="2026-09-01")
    with connect() as c:
        for fila in (placsp, ted_pendiente, ted_rechazada, otra_ted):
            _insertar(c, fila)
        for dup in ("ted:1-2026", "ted:2-2026"):
            c.execute(
                "INSERT INTO licitaciones_duplicados (licitacion_id, canonical_id, clave_match, "
                " confianza, status) VALUES (%s, 'ted:0-2026', 'republicacion', 0.8, 'pending')",
                (dup,),
            )
    assert resolve_pending("ted:2-2026", accept=False, resolved_by="revisor")

    ref = ReferenciaCruzada(expediente="EXP-P")
    detect_duplicados_por_referencia(
        fuente="ted", referencias={"ted:1-2026": ref, "ted:2-2026": ref}
    )

    with connect_read() as c:
        assert _marca(c, "ted:1-2026") == ("EXP-P", "confirmed")
        assert _marca(c, "ted:2-2026") == ("ted:0-2026", "rejected")
