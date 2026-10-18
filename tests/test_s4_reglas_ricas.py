"""Reglas de watchlist con los seis criterios de S4.4.

Integración (``tmp_db``). Tres cosas que hay que garantizar y que no se ven
mirando el código:

1. **Paridad**: la vista previa y el detalle de una regla dan el mismo total.
   Divergieron una vez porque cada uno construía su propio predicado.
2. **Regresión**: una regla escrita antes de esta revisión devuelve exactamente
   lo mismo. ``None`` en un criterio nuevo significa «no filtra», y el test lo
   fija con una fixture de datos concreta.
3. **Universo**: ``banda_min`` puntúa sobre el mismo conjunto que el Radar
   (``AggregateRepository.scoring_candidates``): abiertas y en plazo.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from services.watchlist_rules import (
    WatchlistRule,
    count_matches,
    count_matches_bounded,
    list_matches,
)

_HOY = datetime.now(UTC).date()
_MANANA = (_HOY + timedelta(days=1)).isoformat()
_EN_UN_MES = (_HOY + timedelta(days=30)).isoformat()
_AYER = (_HOY - timedelta(days=1)).isoformat()


def _sembrar(filas: list[dict[str, object]]) -> None:
    from db.database import connect

    columnas = (
        "id_externo",
        "titulo",
        "descripcion",
        "organo_contratacion",
        "importe",
        "cpv",
        "ccaa",
        "estado",
        "tecnologia",
        "procedimiento",
        "tipo_contrato",
        "fecha_publicacion",
        "fecha_limite",
        "fecha_extraccion",
    )
    marcadores = ", ".join(["%s"] * len(columnas))
    with connect() as c:
        for fila in filas:
            c.execute(
                f"INSERT INTO licitaciones ({', '.join(columnas)}) VALUES ({marcadores})",  # noqa: S608
                tuple(fila.get(col) for col in columnas),
            )


@pytest.fixture()
def duenya(tmp_db) -> tuple[int, int]:
    """Usuario y organización personal reales. Devuelve ``(user_id, org_id)``.

    ``watchlist_rules.organization_id`` tiene FK contra ``organizations`` desde
    la revisión v64, así que el ``organization_id=1`` literal que usaban estos
    tests solo pasaba porque la suite nunca había corrido contra Postgres. La
    FK es correcta y se queda: una regla apunta a una organización que existe o
    no apunta a ninguna — un id colgado dejaría filas que ninguna consulta con
    scope organizativo puede volver a encontrar, y que ningún borrado de equipo
    limpia (la FK es ``ON DELETE CASCADE``).
    """
    from db.repositories.organizations import OrganizationRepository
    from db.users import create_user

    user_id = create_user(
        email="s4-reglas@example.test",
        password_hash="test-hash",  # pragma: allowlist secret
        display_name="Dueña de las reglas",
    )
    return user_id, int(OrganizationRepository().ensure_personal_organization(user_id)["id"])


@pytest.fixture()
def corpus(tmp_db):
    """Cuatro expedientes que separan cada criterio de los demás."""
    _sembrar(
        [
            {
                "id_externo": "S4-SAP-MADRID",
                "titulo": "Mantenimiento SAP para el ayuntamiento",
                "descripcion": "Soporte funcional",
                "organo_contratacion": "Ayuntamiento de Alcañiz",
                "importe": 200000.0,
                "cpv": "72000000",
                "ccaa": "Madrid",
                "estado": "PUB",
                "tecnologia": "SAP,SALESFORCE",
                "procedimiento": "01",
                "tipo_contrato": "Serveis",
                "fecha_publicacion": _AYER,
                "fecha_limite": _EN_UN_MES,
                "fecha_extraccion": _AYER,
            },
            {
                "id_externo": "S4-SAP-CERRADA",
                "titulo": "Mantenimiento SAP ya adjudicado",
                "descripcion": "Soporte funcional",
                "organo_contratacion": "Ayuntamiento de Alcaniz",
                "importe": 300000.0,
                "cpv": "72000000",
                "ccaa": "Madrid",
                "estado": "ADJ",
                "tecnologia": "SAP",
                "procedimiento": "1",
                "tipo_contrato": "services",
                "fecha_publicacion": _AYER,
                "fecha_limite": _EN_UN_MES,
                "fecha_extraccion": _AYER,
            },
            {
                "id_externo": "S4-SAP-SIN-PLAZO",
                "titulo": "Mantenimiento SAP con el plazo vencido",
                "descripcion": "Soporte funcional",
                "organo_contratacion": "Diputación de Teruel",
                "importe": 150000.0,
                "cpv": "72000000",
                "ccaa": "Aragon",
                "estado": "PUB",
                "tecnologia": "SAP",
                "procedimiento": "3",
                "tipo_contrato": "02",
                "fecha_publicacion": _AYER,
                "fecha_limite": _AYER,
                "fecha_extraccion": _AYER,
            },
            {
                "id_externo": "S4-OTRA-TECNOLOGIA",
                "titulo": "Suministro de ordenadores",
                "descripcion": "Equipamiento",
                "organo_contratacion": "Ayuntamiento de Alcañiz",
                "importe": 90000.0,
                "cpv": "30200000",
                "ccaa": "Madrid",
                "estado": "PUB",
                "tecnologia": "OTROS",
                "procedimiento": "1",
                "tipo_contrato": "Subministraments",
                "fecha_publicacion": _AYER,
                "fecha_limite": _MANANA,
                "fecha_extraccion": _AYER,
            },
        ]
    )
    return tmp_db


def _ids(rule: WatchlistRule) -> set[str]:
    return {m["id_externo"] for m in list_matches(rule, limit=50)}


# ── Regresión: las reglas de antes no cambian ────────────────────────────────


def test_una_regla_antigua_devuelve_exactamente_lo_mismo(corpus):
    """Sin los criterios nuevos, el predicado es el de siempre.

    Es el criterio de regresión de S4.4: los seis campos por defecto valen
    ``None`` y ``None`` no filtra.
    """
    regla = WatchlistRule(keyword="SAP", ccaa="Madrid")
    assert _ids(regla) == {"S4-SAP-MADRID", "S4-SAP-CERRADA"}
    assert count_matches(regla) == 2


def test_los_criterios_nuevos_a_none_no_estrechan_nada(corpus):
    con_nulos = WatchlistRule(
        keyword="SAP",
        ccaa="Madrid",
        tecnologia=None,
        organo=None,
        procedimiento=None,
        tipo_contrato=None,
        banda_min=None,
        plazo_min_dias=None,
    )
    assert count_matches(con_nulos) == count_matches(WatchlistRule(keyword="SAP", ccaa="Madrid"))


# ── Paridad preview / matches ────────────────────────────────────────────────


@pytest.mark.parametrize(
    "regla",
    [
        WatchlistRule(keyword="SAP"),
        WatchlistRule(tecnologia="SAP"),
        WatchlistRule(organo="Ayuntamiento de Alcañiz"),
        WatchlistRule(procedimiento="1"),
        WatchlistRule(tipo_contrato="2"),
        WatchlistRule(plazo_min_dias=10),
        WatchlistRule(keyword="SAP", tecnologia="SAP", procedimiento="1"),
    ],
)
def test_preview_y_matches_dan_el_mismo_total(corpus, regla):
    """La vista previa (``POST /preview``) y el detalle (``GET /{id}/matches``)
    llaman los dos a ``count_matches``: la paridad es por construcción y este
    test la fija para que siga siéndolo."""
    total = count_matches(regla)
    assert total == count_matches(regla)
    assert len(list_matches(regla, limit=1000)) == total


def test_el_conteo_acotado_del_badge_coincide_con_el_exacto_cuando_cabe(corpus):
    """Por debajo del techo, «al menos tantas» y «exactamente tantas» son lo
    mismo; si divergen es que las dos rutas construyen predicados distintos."""
    reglas = [WatchlistRule(keyword="SAP"), WatchlistRule(tecnologia="SAP")]
    assert count_matches_bounded(reglas) == [count_matches(r) for r in reglas]


# ── Cada criterio, por separado ──────────────────────────────────────────────


def test_tecnologia_explota_el_csv_y_no_compara_por_igualdad(corpus):
    """``licitaciones.tecnologia`` guarda ``"SAP,SALESFORCE"``: con igualdad,
    filtrar por SALESFORCE escondía justo los expedientes multi-tecnología."""
    assert _ids(WatchlistRule(tecnologia="SALESFORCE")) == {"S4-SAP-MADRID"}
    assert "S4-SAP-MADRID" in _ids(WatchlistRule(tecnologia="SAP"))


def test_organo_casa_pese_a_la_tilde_y_a_la_caja(corpus):
    """Los dos lados se pliegan: «Alcañiz» y «Alcaniz» son el mismo órgano."""
    ids = _ids(WatchlistRule(organo="AYUNTAMIENTO DE ALCAÑIZ"))
    assert {"S4-SAP-MADRID", "S4-SAP-CERRADA", "S4-OTRA-TECNOLOGIA"} == ids


def test_procedimiento_y_tipo_de_contrato_filtran(corpus):
    assert _ids(WatchlistRule(procedimiento="3")) == {"S4-SAP-SIN-PLAZO"}
    assert _ids(WatchlistRule(tipo_contrato="1")) == {"S4-OTRA-TECNOLOGIA"}


def test_el_tipo_de_contrato_casa_con_el_codigo_y_con_la_etiqueta_de_cada_fuente(corpus):
    """La columna guarda lo que publica cada fuente: «Serveis» (PSCP),
    «services» (TED) o el código CODICE con o sin cero. Por igualdad, una regla
    «servicios» no casaba con ninguna fila de producción."""
    servicios = {"S4-SAP-MADRID", "S4-SAP-CERRADA", "S4-SAP-SIN-PLAZO"}
    assert _ids(WatchlistRule(tipo_contrato="2")) == servicios
    assert _ids(WatchlistRule(tipo_contrato="02")) == servicios
    assert _ids(WatchlistRule(tipo_contrato="3")) == set()


def test_una_regla_con_la_palabra_de_antes_se_guarda_como_codigo(corpus):
    """El selector antiguo enviaba «servicios»: la regla la recibe como ``2``
    y casa con las mismas filas que la creada con el código."""
    regla = WatchlistRule(tipo_contrato="servicios")
    assert regla.tipo_contrato == "2"
    assert _ids(regla) == _ids(WatchlistRule(tipo_contrato="2"))
    assert WatchlistRule(tipo_contrato="Suministros").tipo_contrato == "1"
    assert WatchlistRule(tipo_contrato="  ").tipo_contrato is None


def test_el_procedimiento_es_el_codigo_sin_ceros(corpus):
    """La columna guarda el código CODICE (``01`` o ``1``), no la palabra: una
    regla «abierto» no casaba con nada y la alerta no avisaba nunca."""
    abiertos = {"S4-SAP-MADRID", "S4-SAP-CERRADA", "S4-OTRA-TECNOLOGIA"}
    assert _ids(WatchlistRule(procedimiento="1")) == abiertos
    assert _ids(WatchlistRule(procedimiento="01")) == abiertos


def test_el_organo_casa_por_palabras_como_en_el_investigador(corpus):
    """Lo que se escribe no es el nombre exacto de la fuente: «Diputación
    Provincial de Teruel» es la «Diputación de Teruel», y el órgano de una
    regla creada desde el Investigador casa con las mismas filas."""
    assert _ids(WatchlistRule(organo="Diputación Provincial de Teruel")) == {"S4-SAP-SIN-PLAZO"}
    assert _ids(WatchlistRule(organo="Ajuntament d'Alcañiz")) == {
        "S4-SAP-MADRID",
        "S4-SAP-CERRADA",
        "S4-OTRA-TECNOLOGIA",
    }
    assert _ids(WatchlistRule(organo="Ayuntamiento de Teruel")) == set()


def test_plazo_min_dias_descarta_lo_que_vence_antes(corpus):
    """Una regla para quien no puede preparar una oferta en menos de N días."""
    ids = _ids(WatchlistRule(plazo_min_dias=10))
    assert "S4-SAP-MADRID" in ids
    assert "S4-OTRA-TECNOLOGIA" not in ids, "vence mañana"
    assert "S4-SAP-SIN-PLAZO" not in ids, "el plazo ya venció"


def test_banda_min_acota_al_universo_puntuable_del_radar(corpus):
    """Criterio de S4.4: el mismo universo que ``scoring_candidates``.

    Un expediente adjudicado o con el plazo vencido no es una oportunidad, así
    que no tiene banda; puntuarlo daría una que en el Radar no existe.
    """
    ids = _ids(WatchlistRule(keyword="SAP", banda_min="Descarte"))
    assert "S4-SAP-CERRADA" not in ids, "estado terminal"
    assert "S4-SAP-SIN-PLAZO" not in ids, "plazo vencido"
    assert ids <= {"S4-SAP-MADRID"}


def test_banda_min_alta_no_devuelve_mas_que_banda_min_baja(corpus):
    """El orden de las bandas es monótono: exigir más nunca amplía el conjunto."""
    baja = _ids(WatchlistRule(keyword="SAP", banda_min="Descarte"))
    alta = _ids(WatchlistRule(keyword="SAP", banda_min="Caliente"))
    assert alta <= baja


def test_banda_min_mantiene_la_paridad_de_totales(corpus):
    regla = WatchlistRule(keyword="SAP", banda_min="Descarte")
    assert count_matches(regla) == len(list_matches(regla, limit=1000))


# ── Persistencia ─────────────────────────────────────────────────────────────


def test_los_seis_criterios_sobreviven_al_crud(corpus, duenya):
    from services.watchlist_rules import create_rule, list_rules, update_rule

    user_id, org_id = duenya
    regla = WatchlistRule(
        nombre="SAP abierto en Alcañiz",
        keyword="SAP",
        tecnologia="SAP",
        organo="Ayuntamiento de Alcañiz",
        procedimiento="1",
        tipo_contrato="servicios",
        banda_min="Tibia",
        plazo_min_dias=15,
    )
    rule_id = create_rule("uk-s4", regla, user_id=user_id, organization_id=org_id)
    guardada = next(r for r in list_rules("uk-s4", org_id) if r.id == rule_id)
    assert guardada.tecnologia == "SAP"
    assert guardada.organo == "Ayuntamiento de Alcañiz"
    assert guardada.procedimiento == "1"
    assert guardada.tipo_contrato == "2", "se guarda el código, no la palabra"
    assert guardada.banda_min == "Tibia"
    assert guardada.plazo_min_dias == 15

    assert update_rule("uk-s4", rule_id, regla.model_copy(update={"plazo_min_dias": 5}), org_id)
    reeditada = next(r for r in list_rules("uk-s4", org_id) if r.id == rule_id)
    assert reeditada.plazo_min_dias == 5


def test_organo_norm_se_persiste_plegado(corpus, duenya):
    """La normalización se guarda: aplicarla en cada consulta sobre la columna
    de la tabla grande impediría usar índice."""
    from db.database import connect_read
    from services.watchlist_rules import create_rule

    user_id, org_id = duenya
    rule_id = create_rule(
        "uk-s4-norm",
        WatchlistRule(organo="Ayuntamiento de Alcañiz, S.A."),
        user_id=user_id,
        organization_id=org_id,
    )
    with connect_read() as c:
        fila = c.execute(
            "SELECT organo, organo_norm FROM watchlist_rules WHERE id = %s", (rule_id,)
        ).fetchone()
    assert fila[0] == "Ayuntamiento de Alcañiz, S.A."
    assert fila[1] and fila[1] == fila[1].lower()
    assert "ñ" not in fila[1]
