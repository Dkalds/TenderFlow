"""Seguimiento unificado (`follows`, v130 / ADR-031), contra Postgres.

Qué se fija aquí
----------------
1. **Que la tabla existe con la forma del ADR** y que la enumeración cerrada de
   `target_type` la sostiene la base, no sólo el DTO: un tipo inventado tiene
   que reventar en el `CHECK` aunque alguien escriba SQL a mano.
2. **La escritura doble.** Marcar un favorito, seguir una empresa o descartar
   en el radar deja fila en `follows`; quitarlos la retira. Es lo que hace
   medible la paridad — sin esto, `follows` se queda en la foto del backfill y
   diverge desde el primer día.
3. **Que la escritura doble no puede tumbar la operación principal.** Si
   `follows` falla, el favorito se guarda igual. Mientras la tabla sea una
   copia, esa es la prioridad correcta y conviene que esté escrita.
4. **Lo que `follows` añade y antes no existía:** seguir un órgano y un CPV, y
   la pregunta inversa «¿quién sigue esto?» (ADR-031 §D).
5. **El script de paridad da cero** con la escritura doble puesta. Es la
   condición que ADR-031 §B pone para mover una lectura, ejercitada aquí con
   datos de prueba antes de ejecutarla contra producción.
6. **Que los descartes caducados dejan de contar** sin borrarse: `hasta` es lo
   único que el backfill trae de `radar_dismissals` porque define el puntero,
   no lo decora.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import patch

import pytest


def _usuario(db_mod: Any, correo: str) -> tuple[int, int, str]:
    """`(user_id, organization_id, user_key)` de un usuario nuevo."""
    from db.repositories.organizations import OrganizationRepository
    from db.users import create_user
    from shared.identity import user_key_from_email

    user_id = create_user(email=correo, password_hash="x")  # pragma: allowlist secret
    org_id = int(OrganizationRepository().ensure_personal_organization(user_id)["id"])
    return user_id, org_id, user_key_from_email(correo, user_id)


def _licitacion(db_mod: Any, id_externo: str) -> None:
    with db_mod.connect() as c:
        c.execute(
            "INSERT INTO licitaciones (id_externo, titulo, fecha_extraccion) "
            "VALUES (%s, %s, %s) ON CONFLICT (id_externo) DO NOTHING",
            (id_externo, "Expediente de prueba", "2026-09-01T00:00:00+00:00"),
        )


# ── 1. Forma de la tabla ────────────────────────────────────────────────────


def test_la_enumeracion_de_target_type_la_sostiene_la_base(tmp_db: Any) -> None:
    """El `CHECK` de v130, no sólo el patrón del DTO.

    Importa que sean dos: el DTO protege la API y el `CHECK` protege todo lo
    demás —un script, un backfill, una consola psql—. Con sólo el DTO, la
    primera fila con `target_type='organo '` (con espacio) entraría y nadie la
    vería hasta que una lectura la ignorase en silencio.
    """
    db_mod, _ = tmp_db
    with pytest.raises(Exception, match=r"check|constraint|violat"):
        with db_mod.connect() as c:
            c.execute(
                "INSERT INTO follows (user_key, target_type, target_id) VALUES (%s, %s, %s)",
                ("k", "planeta", "X"),
            )


def test_seguir_y_descartar_lo_mismo_conviven(tmp_db: Any) -> None:
    """El `UNIQUE` lleva `kind`, y es deliberado.

    Descartar en el radar y tener en favoritos el mismo expediente son dos
    gestos distintos del usuario. Un `UNIQUE` sin `kind` haría que el segundo
    pisara al primero.
    """
    db_mod, _ = tmp_db
    from db.repositories import follows as repo

    user_id, org_id, user_key = _usuario(db_mod, "dos-signos@example.test")
    a = repo.registrar(
        user_key=user_key,
        user_id=user_id,
        organization_id=org_id,
        target_type="licitacion",
        target_id="LIC-DOS",
    )
    b = repo.registrar(
        user_key=user_key,
        user_id=user_id,
        organization_id=org_id,
        target_type="licitacion",
        target_id="LIC-DOS",
        kind="descartar",
    )
    assert a is not None and b is not None and a["id"] != b["id"]


def test_registrar_es_idempotente_y_mueve_la_caducidad(tmp_db: Any) -> None:
    """Volver a posponer algo ya pospuesto tiene que mover `hasta`."""
    db_mod, _ = tmp_db
    from db.repositories import follows as repo

    user_id, org_id, user_key = _usuario(db_mod, "posponer@example.test")
    semana = (datetime.now(UTC) + timedelta(days=7)).isoformat()
    mes = (datetime.now(UTC) + timedelta(days=30)).isoformat()

    primero = repo.registrar(
        user_key=user_key,
        user_id=user_id,
        organization_id=org_id,
        target_type="licitacion",
        target_id="LIC-POSP",
        kind="descartar",
        hasta=semana,
    )
    segundo = repo.registrar(
        user_key=user_key,
        user_id=user_id,
        organization_id=org_id,
        target_type="licitacion",
        target_id="LIC-POSP",
        kind="descartar",
        hasta=mes,
    )
    assert primero is not None and segundo is not None
    assert primero["id"] == segundo["id"]  # una sola fila
    assert segundo["hasta"] != primero["hasta"]  # con la última decisión


# ── 2. Escritura doble desde las tres tablas de origen ──────────────────────


def test_el_favorito_deja_fila_en_follows(tmp_db: Any) -> None:
    db_mod, _ = tmp_db
    from db.repositories import follows as repo
    from db.repositories.watchlist import WatchlistRepository

    user_id, org_id, user_key = _usuario(db_mod, "favorito@example.test")
    _licitacion(db_mod, "LIC-FAV")

    WatchlistRepository().add_item(user_key, user_id, "LIC-FAV", org_id, "private")
    seguidos = repo.listar(user_key=user_key, user_id=user_id, organization_id=org_id)
    assert [(f["target_type"], f["target_id"]) for f in seguidos] == [("licitacion", "LIC-FAV")]

    WatchlistRepository().remove_item(user_key, "LIC-FAV", org_id, user_id)
    assert repo.listar(user_key=user_key, user_id=user_id, organization_id=org_id) == []


def test_la_empresa_seguida_deja_fila_en_follows(tmp_db: Any) -> None:
    db_mod, _ = tmp_db
    from db.repositories import follows as repo
    from db.watchlist_empresas import WatchlistEmpresaEntry, add_entry, remove_entry

    user_id, org_id, user_key = _usuario(db_mod, "empresa@example.test")
    with db_mod.connect() as c:
        fila = c.execute(
            "INSERT INTO empresas (nombre_canonico, created_at, updated_at) "
            "VALUES (%s, %s, %s) RETURNING empresa_id",
            ("ACME SL", "2026-09-01T00:00:00+00:00", "2026-09-01T00:00:00+00:00"),
        ).fetchone()
    empresa_id = int(fila[0])

    add_entry(
        WatchlistEmpresaEntry(
            user_key=user_key,
            user_id=user_id,
            empresa_id=empresa_id,
            organization_id=org_id,
        )
    )
    seguidas = repo.listar(
        user_key=user_key, user_id=user_id, organization_id=org_id, target_type="empresa"
    )
    # `target_id` es texto aunque la empresa sea un entero: el objetivo es
    # polimórfico y por eso no puede llevar clave foránea (ADR-031 §Riesgo).
    assert [f["target_id"] for f in seguidas] == [str(empresa_id)]

    remove_entry(user_key, empresa_id, org_id, user_id=user_id)
    assert (
        repo.listar(
            user_key=user_key, user_id=user_id, organization_id=org_id, target_type="empresa"
        )
        == []
    )


def test_el_descarte_del_radar_deja_fila_con_signo_negativo(tmp_db: Any) -> None:
    db_mod, _ = tmp_db
    from db import radar_dismissals
    from db.repositories import follows as repo

    user_id, org_id, user_key = _usuario(db_mod, "descarte@example.test")
    _licitacion(db_mod, "LIC-DESC")

    radar_dismissals.add(
        user_key, "LIC-DESC", organization_id=org_id, user_id=user_id, score=70, banda="alta"
    )

    # No aparece entre lo seguido...
    assert repo.listar(user_key=user_key, user_id=user_id, organization_id=org_id) == []
    # ...sino entre lo descartado. Descartar es seguir con signo negativo.
    descartes = repo.listar(
        user_key=user_key, user_id=user_id, organization_id=org_id, kind="descartar"
    )
    assert [f["target_id"] for f in descartes] == ["LIC-DESC"]

    radar_dismissals.remove(user_key, "LIC-DESC", user_id=user_id)
    assert (
        repo.listar(user_key=user_key, user_id=user_id, organization_id=org_id, kind="descartar")
        == []
    )


# ── 3. La copia no puede tumbar al original ─────────────────────────────────


def test_si_follows_falla_el_favorito_se_guarda_igual(tmp_db: Any) -> None:
    """La prioridad, mientras `follows` sea una copia, es el dato del usuario."""
    db_mod, _ = tmp_db
    from db.repositories.watchlist import WatchlistRepository

    user_id, org_id, user_key = _usuario(db_mod, "resiliente@example.test")
    _licitacion(db_mod, "LIC-RESIL")

    with patch("db.repositories.follows.connect", side_effect=RuntimeError("follows caída")):
        item = WatchlistRepository().add_item(user_key, user_id, "LIC-RESIL", org_id, "private")

    assert item["id_externo"] == "LIC-RESIL"
    with db_mod.connect_read() as c:
        assert c.execute("SELECT COUNT(*) FROM follows").fetchone()[0] == 0


# ── 4. Lo que antes no existía ──────────────────────────────────────────────


def test_seguir_un_organo_y_un_cpv(tmp_db: Any) -> None:
    """Los dos objetivos que el producto pedía y no existían.

    No existían porque cada uno habría necesitado su propia tabla, sus
    endpoints y su control en la interfaz. Aquí son dos filas.
    """
    db_mod, _ = tmp_db
    from db.repositories import follows as repo

    user_id, org_id, user_key = _usuario(db_mod, "organo@example.test")
    for tipo, objetivo in (("organo", "E05068001"), ("cpv", "72000000")):
        assert (
            repo.registrar(
                user_key=user_key,
                user_id=user_id,
                organization_id=org_id,
                target_type=tipo,
                target_id=objetivo,
            )
            is not None
        )

    tipos = {
        f["target_type"]
        for f in repo.listar(user_key=user_key, user_id=user_id, organization_id=org_id)
    }
    assert tipos == {"organo", "cpv"}


def test_quien_sigue_esto(tmp_db: Any) -> None:
    """ADR-031 §D: la pregunta del despachador, en una consulta y no en tres."""
    db_mod, _ = tmp_db
    from db.repositories import follows as repo

    a_id, a_org, a_key = _usuario(db_mod, "sigue-a@example.test")
    b_id, b_org, b_key = _usuario(db_mod, "sigue-b@example.test")
    for uid, org, key in ((a_id, a_org, a_key), (b_id, b_org, b_key)):
        repo.registrar(
            user_key=key,
            user_id=uid,
            organization_id=org,
            target_type="organo",
            target_id="E05068001",
        )

    seguidores = repo.seguidores("organo", "E05068001")
    assert {s["user_key"] for s in seguidores} == {a_key, b_key}
    # Cruza organizaciones a propósito: el despachador corre fuera de una
    # petición y tiene que avisar a todo el mundo, no a un tenant.
    assert {s["organization_id"] for s in seguidores} == {a_org, b_org}


# ── 5. Paridad ──────────────────────────────────────────────────────────────


def test_el_script_de_paridad_da_cero_con_la_escritura_doble(tmp_db: Any) -> None:
    """La condición de ADR-031 §B, ejercitada con datos de prueba.

    Aquí siempre da cero porque la escritura doble acaba de crear las filas.
    El valor del test no es ese cero: es que el script sepa proyectar cada
    tabla igual que el backfill de v130, que es lo que se rompe cuando alguien
    cambia una de las dos y no la otra.
    """
    db_mod, _ = tmp_db
    from db.repositories.watchlist import WatchlistRepository
    from scripts.check_follows_paridad import medir

    user_id, org_id, user_key = _usuario(db_mod, "paridad@example.test")
    _licitacion(db_mod, "LIC-PAR")
    WatchlistRepository().add_item(user_key, user_id, "LIC-PAR", org_id, "private")

    diferencias = {d.tabla: d for d in medir()}
    favoritos = diferencias["watchlist_items"]
    assert favoritos.filas_origen == 1
    assert favoritos.faltan == 0 and favoritos.sobran == 0
    assert all(d.ok for d in diferencias.values())


def test_la_paridad_detecta_una_fila_sin_reflejar(tmp_db: Any) -> None:
    """Un favorito escrito sin pasar por la escritura doble es lo que el
    script tiene que ver: es la forma exacta que tendría un backfill a medias."""
    db_mod, _ = tmp_db
    from scripts.check_follows_paridad import medir

    user_id, org_id, user_key = _usuario(db_mod, "hueco@example.test")
    _licitacion(db_mod, "LIC-HUECO")
    with db_mod.connect() as c:
        c.execute(
            "INSERT INTO watchlist_items (user_key, user_id, id_externo, created_at, "
            " organization_id, visibility) VALUES (%s, %s, %s, %s, %s, %s)",
            (user_key, user_id, "LIC-HUECO", "2026-09-01T00:00:00+00:00", org_id, "private"),
        )

    favoritos = {d.tabla: d for d in medir()}["watchlist_items"]
    assert favoritos.faltan == 1
    assert favoritos.ok is False
    assert favoritos.ejemplos_faltan == [f"{user_key}→LIC-HUECO"]


# ── 6. Caducidad ────────────────────────────────────────────────────────────


def test_un_descarte_caducado_deja_de_contar_sin_borrarse(tmp_db: Any) -> None:
    db_mod, _ = tmp_db
    from db.repositories import follows as repo

    user_id, org_id, user_key = _usuario(db_mod, "caducado@example.test")
    ayer = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    repo.registrar(
        user_key=user_key,
        user_id=user_id,
        organization_id=org_id,
        target_type="licitacion",
        target_id="LIC-VENCIDO",
        kind="descartar",
        hasta=ayer,
    )

    vigentes = repo.listar(
        user_key=user_key, user_id=user_id, organization_id=org_id, kind="descartar"
    )
    assert vigentes == []

    # La fila sigue ahí: hace falta para poder decir «lo descartaste el día X».
    todos = repo.listar(
        user_key=user_key,
        user_id=user_id,
        organization_id=org_id,
        kind="descartar",
        vigentes=False,
    )
    assert [f["target_id"] for f in todos] == ["LIC-VENCIDO"]
    # Y tampoco se lo lleva `seguidores`, que es lo que mira el despachador.
    assert repo.seguidores("licitacion", "LIC-VENCIDO", kind="descartar") == []
