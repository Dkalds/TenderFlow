"""Purga de PSCP: la base de datos acaba con lo que el conector admitiría hoy.

`scripts/purgar_pscp_sin_tecnologia.py` decide con la misma puerta que el
conector (`senal_tecnologica`). Estos tests fijan las dos mitades: la decisión
por fila (pura) y lo que el borrado hace y no hace contra Postgres — cascada,
referencias blandas, trabajo de usuario protegido y filas de otras fuentes
intactas.
"""

from __future__ import annotations

from typing import Any

from scripts.purgar_pscp_sin_tecnologia import (
    BORRAR,
    CONSERVAR,
    decidir,
    recorrer,
)

# ── La decisión por fila ────────────────────────────────────────────────────


def _fila(**campos: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id_externo": "pscp:X",
        "titulo": "",
        "cpv": None,
        "tecnologia": None,
        "raw_keywords": None,
        "analysis_universe": "pscp_observed",
    }
    return {**base, **campos}


def test_una_fila_sin_senal_se_borra() -> None:
    d = decidir(_fila(titulo="Servei de neteja de l'escola", cpv="90910000-9"))
    assert d.accion == BORRAR
    assert d.motivo == "sin_senal_tecnologica"


def test_una_fila_bien_etiquetada_no_se_toca() -> None:
    d = decidir(
        _fila(
            titulo="Manteniment SAP S/4HANA",
            cpv="72267000-4",
            tecnologia="SAP",
            raw_keywords="s/4hana,sap",
        )
    )
    assert d.accion == CONSERVAR
    assert not d.desactualizada


def test_la_fila_de_ti_sin_etiqueta_se_conserva_y_se_marca_desactualizada() -> None:
    """El caso que impide borrar por `tecnologia IS NULL`.

    Ingerida antes de que el diccionario tuviera términos en catalán, esta fila
    llegó sin etiqueta; con el diccionario de hoy es TI. No se reescribe aquí
    (`tecnologia` solo la escribe el upsert de ingesta): la reingesta la corrige.
    """
    d = decidir(_fila(titulo="Desenvolupament de programari de gestió", cpv="72212000-4"))
    assert d.accion == CONSERVAR
    assert d.desactualizada
    assert d.tecnologia == "DESARROLLO"
    assert d.raw_keywords == "desenvolupament de programari"


def test_la_fila_sin_universo_cuenta_como_desactualizada() -> None:
    """`analysis_universe` NULL cuenta como `technology_observed` en las lecturas."""
    d = decidir(
        _fila(
            titulo="Manteniment SAP S/4HANA",
            cpv="72267000-4",
            tecnologia="SAP",
            raw_keywords="s/4hana,sap",
            analysis_universe=None,
        )
    )
    assert d.accion == CONSERVAR
    assert d.desactualizada


def test_el_falso_positivo_etiquetado_se_borra() -> None:
    """Etiquetada «SALESFORCE» por un cable Lightning: la puerta de hoy la rechaza."""
    d = decidir(
        _fila(
            titulo="CABLE APPLE LIGHTNING USB-A 1m BLANC",
            cpv="32000000-3",
            tecnologia="SALESFORCE",
            raw_keywords="lightning",
        )
    )
    assert d.accion == BORRAR
    assert d.motivo == "keyword_ambigua_sin_cpv_ti"


# ── Contra Postgres ─────────────────────────────────────────────────────────


def _organizacion(nombre: str) -> int:
    from db.repositories.organizations import OrganizationRepository
    from db.users import create_user

    owner = create_user(
        email=f"{nombre}@example.test",
        password_hash="test-hash",  # pragma: allowlist secret -- literal de test
        display_name=nombre,
    )
    return int(OrganizationRepository().create_organization(nombre, owner)["id"])


def _sembrar(db_mod: Any) -> None:
    filas = [
        # (id, fuente, titulo, cpv, tecnologia, raw_keywords, universo)
        ("pscp:NETEJA", "pscp", "Servei de neteja de l'escola", "90910000-9", None, None, None),
        (
            "pscp:SAP",
            "pscp",
            "Manteniment SAP S/4HANA",
            "72267000-4",
            "SAP",
            "s/4hana,sap",
            "pscp_observed",
        ),
        (
            "pscp:PROGRAMARI",
            "pscp",
            "Desenvolupament de programari de gestió",
            "72212000-4",
            None,
            None,
            None,
        ),
        (
            "pscp:REACTIUS",
            "pscp",
            "Subministrament de reactius de laboratori",
            "33696500-0",
            None,
            None,
            "pscp_observed",
        ),
        (
            "pscp:CABLE",
            "pscp",
            "CABLE APPLE LIGHTNING USB-A 1m BLANC",
            "32000000-3",
            "SALESFORCE",
            "lightning",
            "pscp_observed",
        ),
        # Otra fuente, sin señal: la purga de PSCP no puede tocarla.
        ("placsp:NETEJA", "placsp", "Servicio de limpieza", "90910000-9", None, None, None),
    ]
    with db_mod.connect() as c:
        for id_ext, fuente, titulo, cpv, tec, kws, universo in filas:
            c.execute(
                "INSERT INTO licitaciones (id_externo, fuente, titulo, cpv, tecnologia, "
                "raw_keywords, analysis_universe, fecha_extraccion) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, '2026-09-01')",
                (id_ext, fuente, titulo, cpv, tec, kws, universo),
            )
        # Dependientes con FK en cascada. El score, además, dispara al COMMIT el
        # trigger diferido de v136, que intenta reescribir el resumen ML de una
        # licitación que ya no existe: tiene que no hacer nada, no fallar.
        c.execute(
            "INSERT INTO adjudicaciones (licitacion_id, nombre, fecha_extraccion) "
            "VALUES ('pscp:NETEJA', 'Neteges SL', '2026-09-01')"
        )
        c.execute(
            "INSERT INTO licitacion_tecnologia_score "
            "(licitacion_id, tecnologia, probabilidad, threshold_aplicado, computed_at) "
            "VALUES ('pscp:NETEJA', 'SAP', 0.91, 0.5, '2026-09-01T00:00:00+00:00')"
        )
        # Referencias blandas de la fila que se borra.
        c.execute(
            "INSERT INTO user_notifications (user_key, created_at, type, title, licitacion_id) "
            "VALUES ('uk', '2026-09-01', 'rule_match', 'Neteja', 'pscp:NETEJA')"
        )
        c.execute(
            "INSERT INTO follows (user_key, target_type, target_id, kind) "
            "VALUES ('uk', 'licitacion', 'pscp:NETEJA', 'descartar')"
        )
    # Trabajo de usuario sobre una fila sin señal: se conserva.
    org = _organizacion("purga")
    with db_mod.connect() as c:
        c.execute(
            "INSERT INTO pursuits (organization_id, licitacion_id, status, created_at, "
            " updated_at) VALUES (%s, 'pscp:REACTIUS', 'identified', '2026-09-01', '2026-09-01')",
            (org,),
        )


def _estado(db_mod: Any) -> dict[str, tuple[Any, ...]]:
    with db_mod.connect() as c:
        filas = c.execute(
            "SELECT id_externo, tecnologia, raw_keywords, analysis_universe FROM licitaciones"
        ).fetchall()
    return {str(f[0]): tuple(f[1:]) for f in filas}


def _cuenta(db_mod: Any, sql: str) -> int:
    with db_mod.connect() as c:
        return int(c.execute(sql).fetchone()[0])


def test_el_dry_run_mide_y_no_toca_nada(tmp_db: Any) -> None:
    db_mod, _ = tmp_db
    _sembrar(db_mod)
    antes = _estado(db_mod)

    balance = recorrer(aplicar=False, lote_lectura=100, lote_borrado=100, ejemplos=3)

    assert _estado(db_mod) == antes
    assert balance.leidas == 5  # solo PSCP
    assert balance.acciones == {BORRAR: 3, CONSERVAR: 2}
    assert balance.desactualizadas == 1
    assert balance.motivos_borrado == {"sin_senal_tecnologica": 2, "keyword_ambigua_sin_cpv_ti": 1}
    assert balance.protegidas == 1


def test_la_purga_deja_solo_lo_que_el_conector_admitiria(tmp_db: Any) -> None:
    """Lotes de 2 y borrados de 1: el recorrido por clave sobrevive a sus propios borrados."""
    db_mod, _ = tmp_db
    _sembrar(db_mod)

    balance = recorrer(aplicar=True, lote_lectura=2, lote_borrado=1, ejemplos=3)
    estado = _estado(db_mod)

    # Borradas: la de limpieza y el falso positivo etiquetado.
    assert "pscp:NETEJA" not in estado
    assert "pscp:CABLE" not in estado
    # Intactas: la TI sin etiqueta (la reetiqueta la reingesta, no la purga), la
    # bien etiquetada, la protegida y la de otra fuente.
    assert estado["pscp:PROGRAMARI"] == (None, None, None)
    assert estado["pscp:SAP"] == ("SAP", "s/4hana,sap", "pscp_observed")
    assert "pscp:REACTIUS" in estado
    assert "placsp:NETEJA" in estado

    assert balance.borradas["licitaciones"] == 2
    assert balance.borradas["user_notifications"] == 1
    assert balance.borradas["follows_descartes"] == 1
    assert balance.desactualizadas == 1
    assert balance.protegidas == 1
    # La cascada y las referencias blandas se fueron con la fila.
    assert _cuenta(db_mod, "SELECT COUNT(*) FROM adjudicaciones") == 0
    assert _cuenta(db_mod, "SELECT COUNT(*) FROM licitacion_tecnologia_score") == 0
    assert _cuenta(db_mod, "SELECT COUNT(*) FROM user_notifications") == 0
    assert _cuenta(db_mod, "SELECT COUNT(*) FROM follows") == 0
    assert _cuenta(db_mod, "SELECT COUNT(*) FROM pursuits") == 1


def test_la_purga_es_reanudable(tmp_db: Any) -> None:
    """Una segunda pasada no encuentra nada que hacer."""
    db_mod, _ = tmp_db
    _sembrar(db_mod)
    recorrer(aplicar=True, lote_lectura=100, lote_borrado=100, ejemplos=0)
    antes = _estado(db_mod)

    segunda = recorrer(aplicar=True, lote_lectura=100, lote_borrado=100, ejemplos=0)

    assert _estado(db_mod) == antes
    assert segunda.borradas["licitaciones"] == 0
    # La protegida sigue sin pasar la puerta y sigue sin borrarse.
    assert segunda.acciones[BORRAR] == 1
    assert segunda.protegidas == 1


def test_purgar_no_borra_filas_de_otra_fuente(tmp_db: Any) -> None:
    """El filtro por `fuente` del DELETE es un seguro contra ids equivocados."""
    from db.repositories.purga_licitaciones import purgar

    db_mod, _ = tmp_db
    _sembrar(db_mod)
    with db_mod.connect() as c:
        c.execute(
            "INSERT INTO user_notifications (user_key, created_at, type, title, licitacion_id) "
            "VALUES ('uk', '2026-09-01', 'rule_match', 'Limpieza', 'placsp:NETEJA')"
        )

    resumen = purgar(["placsp:NETEJA"], fuente="pscp")

    assert resumen["licitaciones"] == 0
    assert "placsp:NETEJA" in _estado(db_mod)
    # Ni lo que cuelga de ella: la notificación de la fila ajena sigue ahí.
    assert (
        _cuenta(
            db_mod,
            "SELECT COUNT(*) FROM user_notifications WHERE licitacion_id = 'placsp:NETEJA'",
        )
        == 1
    )
