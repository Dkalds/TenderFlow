---
tags: [plan, producto, funcionalidades, multi-agente]
---

# Plan de funcionalidades 2026-09, tercera parte — el ciclo de vida de la organización

Quinto plan de la serie de septiembre y tercero centrado en funcionalidades.
[v2](2026-09-plan-arquitectura-v2.md) y el
[complementario](2026-09-plan-arquitectura-v2-complementario.md) miran la
arquitectura; el [plan de funcionalidades](2026-09-plan-funcionalidades.md)
recorre el día del usuario y la
[segunda parte](2026-09-plan-funcionalidades-oferta-y-equipo.md) la vida de la
oferta. Los cuatro dan por hecho algo que no lo es: que la organización ya
está dentro, configurada, con historia cargada y con alguien mirando los
números. Este plan cubre ese eje del tiempo: **llegar** (acceso y alta),
**arrancar** (primer valor e historial), **crecer** (adopción y confianza en
el dato) y **dirigir** (objetivos, previsión y consumo).

Redactado el 2026-09-06 sobre el mismo árbol (rama
`claude/app-architecture-review-d3vcog`, base `master` = `17169ce`). Cada
funcionalidad dice qué hay hoy, con referencia, y de qué ítem de los planes
anteriores depende. No repite nada que allí esté planificado: lo cita por su
identificador (S, T, C, F, H) y no lo redefine.

**Estado: PROPUESTO el 2026-09-06.** Nada de este documento está implementado.
Mismo contrato de ejecución que sus hermanos: un stream por rama y por
agente, este documento como única fuente de alcance y criterios, y los gates
de AGENTS.md §6 marcados **[§6]** salvo lo que D55 pre-autoriza.

## 0. Alcance y método

**Qué cubre.** Veintidós funcionalidades en cuatro grupos (J1–J4), uno por
etapa: llegar, arrancar, crecer y dirigir. Mismo esqueleto que los dos planes
de funcionalidades anteriores: para quién es, qué hace, qué hay hoy
(verificado), de qué depende, esfuerzo, gate, criterios de aceptación
observables y métrica de adopción en el catálogo de
`web/src/lib/analytics.ts`, con la regla de ese fichero: dimensiones
categóricas de cardinalidad baja, nunca identificadores ni texto del usuario.

**Qué queda fuera.** El backup y el restore drill, por decisión del
mantenedor; todo lo que los cuatro planes anteriores ya planifican (en
particular los estados vacíos de C7.3, el glosario de F1.8, las plantillas
para nuevos miembros de F6.4 y los ajustes en un sitio de C7.5); y lo listado
en §6. No añade espacios de consola.

**Prioridad.** Misma escala: **P0** cierra una promesa del producto, **P1**
quita un daño diario, **P2** quita fricción acumulada. Aquí «promesa» incluye
la que hace la propia página pública: «la respuesta llega por correo».

**Convenciones.** Esfuerzo **S** / **M** / **L** como en v2. Las cifras llevan
fecha y se vuelven a medir. Un criterio de aceptación que no se pueda
comprobar no entra. Los identificadores de este plan empiezan por J; las
decisiones continúan en D48.

### Por qué estas y no otras

A los cuatro patrones de los planes anteriores (dato que existe y no llega,
decisión que se captura y no se explota, pregunta sin respuesta, dato que la
fuente publica y la plataforma no lee) este plan añade el quinto:

5. **La organización cambia de estado y el producto la trata siempre igual.**
   El primer día no hay perfil, ni historial, ni equipo; el producto enseña
   catorce espacios y un Radar neutral. A los tres meses hay veinte
   oportunidades cerradas y nadie las convierte en objetivo, previsión ni
   coste. Lo que sirve en cada etapa es distinto, y hoy nada lo distingue.

Y la misma regla de selección: la plataforma calcula, contrasta, recuerda y
enseña; redactar, decidir y firmar siguen siendo de las personas.

## 1. Hechos verificados (2026-09-06)

### Llegar

1. **El formulario público pide poco y bien.** Campos `email`,
   `consentimiento`, `empresa`, `origen` y `mensaje`, más el señuelo
   `website`; se parsea a mano, sin `Form()` ni `python-multipart`
   (`api/routes/publico_solicitudes.py:246-290`,
   `web/src/app/(publico)/_components/formulario-solicitud.tsx:64-115`). El
   operador recibe aviso agrupado en ventanas de quince minutos
   (`services/solicitudes_acceso.py:173-220`). No pide NIF, tecnologías ni
   territorio.
2. **Conceder el acceso ya está en el producto.** La tarjeta de Ops →
   Administración tiene tres botones: conceder email y avisar, conceder
   dominio, descartar
   (`web/src/app/(dashboard)/ops/_components/solicitudes-acceso-card.tsx:254-290`);
   el `PATCH` persiste la concesión en `access_grants`, marca la solicitud
   atendida y solo después avisa
   (`api/routes/admin_solicitudes.py:60-69`, `:137-152`, `:190`;
   `db/access_grants.py:98-112`; RFC 242, `status: approved`). No crea ni el
   usuario ni la organización: el usuario nace en el callback OAuth
   (`api/routes/auth.py:969-977`).
3. **El registro con contraseña ignora las concesiones.** `/register` solo
   mira el interruptor global `ALLOW_SELF_REGISTRATION`, apagado por defecto
   (`api/routes/auth.py:447-451`, `config/settings.py:391`); quien recibe una
   concesión y no tiene cuenta Google no tiene forma de entrar.
4. **La organización llega tarde y a mano.** La organización personal se
   crea perezosamente en la primera resolución de ámbito
   (`services/organizations.py:37-39`); crear otra es un formulario en Equipo
   (`web/src/app/(dashboard)/equipo/page.tsx:299-303`); incorporar a alguien
   exige que ya tenga cuenta (`services/organizations.py:132-136`); no existe
   unirse por dominio ni solicitud de unión (cero coincidencias), y la lista
   de dominios permitidos solo gobierna el login
   (`shared/auth_core.py:363-372`).
5. **Todo el mundo aterriza en Resumen.** Destino fijo en tres sitios
   (`web/src/lib/safe-redirect.ts:2`, `web/src/app/login/page.tsx:161`,
   `api/routes/auth.py:993`); las membresías no tienen puesto ni espacio de
   inicio (`OrganizationMembershipOut`, `shared/dto.py:602-614`).

### Arrancar

6. **Hay una banda de primeros pasos, no un asistente.** Tres pasos (perfil,
   regla, oportunidad) derivados del estado del servidor
   (`web/src/components/onboarding/pasos.ts:57-82`,
   `use-estado-onboarding.ts:53-77`), descarte en `localStorage`
   (`descarte.ts:24`), montada solo en Resumen
   (`web/src/app/(dashboard)/resumen/page.tsx:77`). Por diseño no es un tour
   (`primeros-pasos.tsx:27-28`); no hay biblioteca de tours.
7. **El perfil se rellena en blanco.** `UserProfileBody` trae pesos,
   keywords, CPV e importes (`api/routes/me.py:339-353`); la organización
   solo tecnologías; el diccionario tiene trece familias
   (`config/keywords.py:100-266`); no hay plantillas ni presets (cero
   coincidencias); vacío significa «todas»
   (`web/src/app/(dashboard)/mi-perfil/page.tsx:242-252`).
8. **No se puede previsualizar un ámbito.** `GET /analytics/scoring` acepta
   `min_score`, `limit`, `band`, `tecnologia`, `ids` y `exclude_dismissed`
   (`api/routes/analytics.py:210-230`) y puntúa siempre con el perfil
   guardado; la única vista previa es la de reglas (F5.5).
9. **No hay importación.** El único endpoint masivo es de lectura
   (`POST /licitaciones/bulk-get`, `api/routes/licitaciones.py:993`);
   `pursuits.licitacion_id` es `NOT NULL` con FK `RESTRICT`
   (`v61_organizations_pursuits.py:141-147`) y única por organización
   (`:202-206`), así que una oferta antigua sin expediente en la base no
   cabe en `pursuits`. Los ayudantes de normalización existen
   (`services/dedupe.py:106`, `:112`, `:133`).
10. **Estados vacíos sin acción.** Cincuenta y nueve usos de `EmptyState`,
    dos con botón (ambos «Abrir el Radar»,
    `mi-pipeline/_components/agenda-view.tsx:332-338`,
    `embudo-view.tsx:96-97`); ninguno en Resumen, Radar, Detalle, Mi
    Watchlist, Mi perfil, Equipo ni Oportunidades. Lo cubre C7.3.
11. **La ayuda es una tecla.** Solo el panel de atajos, abierto con `?`
    (`web/src/components/keyboard-help.tsx:59`,
    `web/src/hooks/use-keyboard-shortcuts.ts:64`); ningún enlace desde la
    consola a `/metodologia` (cero coincidencias), cuyas secciones son
    scoring, referencia de precio, contexto competitivo y trazabilidad
    (`web/src/app/(publico)/metodologia/page.tsx:12-45`).
12. **Nadie puede decir «esto no funciona» desde dentro.** El único
    `/feedback` es de relevancia ML (`api/routes/feedback.py:20`, `:252`); el
    error de cliente se registra sin más (`api/routes/security.py:4`); el
    contacto es un `mailto` en la portada y el login
    (`web/src/lib/contacto.ts:18`, `web/src/app/login/page.tsx:496-502`).
13. **No hay novedades del producto.** Sin `CHANGELOG.md`; `release.yml`
    genera el cuerpo de la release con git-cliff y no lo commitea
    (`.github/workflows/release.yml:25-39`); las «novedades» del Resumen son
    expedientes nuevos desde `last_login`
    (`resumen/_components/novedades-banner.tsx:37-38`,
    `services/analytics/resumen.py:196-198`).

### Crecer

14. **El embudo de activación tiene un agujero en medio.**
    `sesion_iniciada`, `perfil_configurado` y `onboarding_ocultado` se
    emiten (`web/src/lib/analytics.ts:70-75`, `:116-129`, `:130-141`);
    `regla_creada` está declarado y marcado «pendiente de cablear»
    (`:142-152`). En backend no hay métrica de activación ni de retención;
    `product_metrics` mide resultados y solo lo consume la CLI
    (`scripts/product_status.py`; cero referencias en `api/`).
15. **La procedencia se ve a medias.** Se muestran la fuente como etiqueta
    del enlace, la versión de la ficha
    (`web/src/components/pursuits/tender-fact-sheet.tsx:282`), el origen de
    cada tecnología (`web/src/components/tecnologias-block.tsx:20`, `:36`) y
    la salud de señales del Radar
    (`web/src/app/(dashboard)/radar/page.tsx:99-112`, `:426-431`). No se
    muestran por expediente `fecha_extraccion` (viaja en el DTO,
    `api/routes/licitaciones.py:105`; solo hay frescura global,
    `web/src/hooks/use-data-freshness.ts`), `fecha_actualizacion_fuente`,
    `filter_version`, `classifier_model_version`, `inclusion_reason` ni
    `analysis_universe`, columnas desde `v62` (`:51-59`) ausentes de
    `LicitacionDetail`. `MetricScope` (`shared/metric_scope.py:8`) sale por
    `/competitive` (`api/routes/competitive.py:210`, `:224`) y ninguna
    pantalla lo pinta.
16. **Lo que se sabe de cada miembro.** `sessions.last_seen_at` (`v58:25`),
    `users(email, oauth_provider, oauth_sub, display_name, created_at)` y
    membresías con `role`, `status`, `invited_by_user_id` y fechas
    (`v61`); Equipo no enseña actividad ni uso.
17. **Sin comparación entre organizaciones.** Cero coincidencias de
    benchmark o mediana de plataforma; el agregado de todas las
    organizaciones existe solo como fila de la CLI
    (`db/repositories/product_metrics.py:44-47`,
    `services/product_metrics.py:96`).
18. **El correo transaccional existe.** `enviar_email_transaccional`
    (`observability/alerts.py:220`) sirve al acceso, al restablecimiento de
    contraseña y a los digests; la baja firmada sin sesión ya tiene patrón
    (`services/email_digest.py:225-232`).

### Dirigir

19. **No hay objetivos.** Cero coincidencias de objetivo o meta comercial;
    `daily_quota` (`v28`) es un tier de API y `cuota_mercado` es la cuota de
    los competidores; `get_metrics` devuelve solo realizados
    (`services/pursuits.py:275`).
20. **La previsión es de mercado, no de pipeline.** `forecast_svc` proyecta
    volumen publicado (`services/analytics/forecast_svc.py:1-9`, `:120`);
    `TrimestreCount` sigue en el contrato sin consumidor desde 2026-07-20
    (`services/analytics/pipeline.py:71`, `:110-115`); nada proyecta
    cierres por trimestre.
21. **Nada de tesorería.** Cero coincidencias de facturación, cobro o
    garantía retenida; la portada declara que no hay planes ni pasarela
    (`web/src/app/(publico)/_content/landing.ts:376`).
22. **El gasto LLM no se atribuye a la organización.** `BudgetGuard` acumula
    en Redis con ámbitos `global | user` (`llm/budget.py:46`, `:240-255`) y
    sujeto `user_key` (`api/routes/ask.py:171-178`); no hay tabla;
    `llm_cost_usd_total` lleva solo modelo y proveedor
    (`llm/client.py:210`, `:242`); `/metrics` exige `metrics:read`
    (`api/routes/metrics.py:47`); las API keys guardan `last_used` y nada
    más (`baseline002_pg_core_genesis.py:162`).
23. **La auditoría no tiene organización.** `audit_log` se indexa por
    `user_key` sin `organization_id`
    (`v51_pg_legacy_tables_backfill.py:53-66`); la única ruta verifica la
    cadena de hashes (`api/routes/security.py:392-403`); `list_recent` no
    tiene consumidor HTTP.
24. **Ops tiene seis vistas** (observabilidad, calidad, administración,
    flags, etiquetado, webhooks; `web/src/lib/space-views.ts:61-68`) y
    ningún endpoint de métricas de producto.

## 2. Decisiones del mantenedor (D48–D55)

Continúa la numeración de los planes anteriores.

| Id | Decisión | Desbloquea |
|---|---|---|
| D48 | **Alta con organización.** Conceder el acceso a una solicitud crea también la organización (nombre de `empresa`, NIF y tecnologías de la solicitud) y deja a quien la pidió como owner en su primer login. Alternativa: seguir con la organización personal y el formulario de Equipo. Propuesta: sí; hoy cada alta acaba en una organización personal que nadie quería. | J1.2 |
| D49 | **Unión por dominio.** Quien entra con un dominio ya concedido a una organización ve «tu empresa ya tiene un espacio» y pide unirse; el owner o admin aprueba. Auto-unión solo si el owner la activa y siempre como `viewer`. Los dominios de correo públicos nunca cuentan. Propuesta: aprobación por defecto. | J1.3 |
| D50 | **Registro con contraseña bajo concesión.** `/register` admite un email con concesión activa aunque `ALLOW_SELF_REGISTRATION` esté apagado, con el mismo fail-closed que el callback OAuth. Propuesta: sí; es la mitad del embudo que hoy solo entra con Google. | J1.4 |
| D51 | **Plantillas sectoriales.** Seis presets en código (`config/presets.py`) con test, no en tabla, hasta que C5.6 convierta el diccionario en dato; entonces migran juntos. Propuesta: código. | J2.2 |
| D52 | **Histórico sin expediente.** Las ofertas antiguas que no casan con ningún expediente van a `ofertas_historicas`, no a `pursuits`, que sigue atado a un expediente real. Propuesta: tabla aparte; una oportunidad sin expediente rompería el resto de la consola. | J2.3 |
| D53 | **Benchmarks anónimos.** Medianas de plataforma con opt-in por organización, mínimo cinco organizaciones por cifra y ninguna identificable; se construye cuando haya al menos diez organizaciones activas. Propuesta: sí, en esos términos y no antes. | J3.7 |
| D54 | **Correos de arranque.** Tres correos (día 1, 3 y 7) solo mientras el paso correspondiente esté pendiente, con baja en un clic. Propuesta: sí; un producto por invitación puede permitirse tres correos útiles. | J3.5 |
| D55 | **Gates §6 pre-autorizados para este plan.** Migraciones de J1.1, J1.2, J1.3, J2.3, J2.4, J3.1, J3.3, J3.7, J4.1 y J4.5 en los términos de cada ítem. Ninguna variable nueva, ninguna edición de workflows y ninguna dependencia: el CSV se lee en el navegador con código propio y se manda como JSON, el correo usa el transporte que ya existe y el PDF `reportlab`. | todos |

Mientras D48–D54 no estén cerradas, los ítems que las citan no se empiezan.

---

## 3. Funcionalidades por etapa

Cada ítem: **Para quién** · **Qué** · **Hoy** · **Depende de** · **Esfuerzo /
gate** · **Aceptación** · **Adopción** (evento o propiedad del catálogo).

### J1 — Llegar: acceso y alta

#### J1.1 Solicitud de acceso con contexto — P1

**Para quién.** Quien pide acceso y quien lo concede. **Qué.** El formulario
público gana campos opcionales: NIF, tecnologías (las trece familias),
comunidades donde se vende y tamaño de la empresa; se guardan en la
solicitud, la tarjeta de Ops los muestra y J1.2 los usa para preparar la
organización. Sin ellos el formulario sigue funcionando igual. **Hoy.** Hecho
1. **Depende de.** Nada. **Esfuerzo / gate.** S · **[§6]** migración
(columnas en `solicitudes_acceso`), pre-autorizada.

*Aceptación:*
- El parseo a mano sigue rechazando `multipart/form-data`; los campos nuevos
  pasan por los mismos límites de longitud y el señuelo `website` sigue
  activo (tests).
- El NIF se normaliza con `services/normalization.normalize_nif` y no se
  valida contra ningún censo: es una declaración, no una verificación.
- La tarjeta de Ops enseña los campos nuevos y «sin datos» cuando faltan.
- El aviso agrupado al operador incluye tecnologías y comunidad, nunca el
  mensaje libre.

*Adopción:* propiedad `campos ∈ {basicos, ampliados}` en el evento de envío
de la superficie pública.

#### J1.2 Alta que termina en organización (D48) — P0

**Para quién.** Quien entra por primera vez. **Qué.** Al conceder, la
tarjeta crea la organización con el nombre, el NIF (S2.1) y las tecnologías
de la solicitud, y la enlaza a la concesión; en el primer login de ese email
la membresía se activa como owner, la organización queda activa y el
asistente de J2.1 arranca con el ámbito precargado. Con concesión de
dominio, la organización queda asociada al dominio para J1.3. **Hoy.** Hechos
2 y 4. **Depende de.** D48, J1.1, identidad fiscal (S2.1). **Esfuerzo /
gate.** M · **[§6]** migración (`access_grants.organization_id`,
`organizations.solicitud_id`), pre-autorizada.

*Aceptación:*
- Conceder crea organización y concesión en la misma transacción; si una
  falla, no queda ninguna (test); repetir la concesión no crea otra.
- Primer login del email → membresía `owner` `active` y organización
  activa; un segundo login no duplica (test); la organización personal se
  crea igual, pero no es la activa.
- `audit_log` registra la creación con el actor administrador, sin copiar el
  email.
- El correo de «ya puedes entrar» menciona el nombre de la organización.

*Adopción:* `sesion_iniciada` gana `alta ∈ {organizacion_preparada,
personal, existente}`.

#### J1.3 Unirse a una organización por dominio (D49) — P1

**Para quién.** El segundo y el tercero de la misma empresa. **Qué.** Al
entrar con un dominio asociado a una organización (J1.2 o verificado por el
owner con un registro TXT), el usuario ve «tu empresa ya tiene un espacio» y
pide unirse; owner y admin ven las solicitudes en Equipo y aprueban con rol;
opcionalmente, auto-unión como `viewer`. **Hoy.** Hecho 4. **Depende de.**
D49, J1.2; invitaciones (S1.1) para el camino inverso. **Esfuerzo / gate.** M
· **[§6]** migración (`organization_domains`, `organization_join_requests`),
pre-autorizada.

*Aceptación:*
- Lista de dominios públicos excluidos, versionada y con test; un dominio
  solo puede pertenecer a una organización.
- Sin aprobación no hay acceso a nada de la organización (test de
  aislamiento); aprobar crea la membresía una sola vez.
- La verificación TXT se comprueba en backend, con caducidad y reintento;
  sin DNS el owner ve «pendiente de verificar».
- Todo en `audit_log`: solicitud, aprobación, rechazo y auto-unión.

*Adopción:* evento nuevo `union_solicitada` con
`resultado ∈ {pendiente, aprobada, rechazada, automatica}`.

#### J1.4 Registro con contraseña bajo concesión (D50) — P1

**Para quién.** Quien no tiene Google ni Microsoft. **Qué.** `/register`
acepta un email con concesión activa (email o dominio) aunque el registro
abierto esté apagado; el resto de la política no cambia. **Hoy.** Hecho 3.
**Depende de.** D50. **Esfuerzo / gate.** S · sin gate.

*Aceptación:*
- Email con concesión → 201; sin concesión y registro cerrado → 403 con el
  mismo mensaje de hoy; caída de la base de datos → 503, nunca 201 (tests).
- La concesión consumida queda anotada en `audit_log` como en el callback
  OAuth.
- El correo de «ya puedes entrar» enlaza al registro cuando la concesión es
  por email.

*Adopción:* `sesion_iniciada` con `metodo=registro` gana
`via ∈ {concesion, abierto}`.

### J2 — Arrancar: primer valor

#### J2.1 Asistente de configuración con vista previa — P0

**Para quién.** Quien abre la consola por primera vez. **Qué.** Cuatro
pantallas (qué vendes, dónde, en qué rango de importe, con qué palabras)
que terminan en una vista previa calculada en el servidor: «con este ámbito,
en los últimos 90 días habrías visto N expedientes y M en banda caliente»;
guardar escribe el perfil personal o el ámbito de organización (F6.1) y
lleva al Radar. Se puede saltar y retomar; la banda de primeros pasos sigue
igual. **Hoy.** Hechos 6, 7 y 8. **Depende de.** J1.2 para el ámbito
precargado; F6.1 para el nivel de organización; sin ellos, perfil personal.
**Esfuerzo / gate.** M · sin gate.

*Aceptación:*
- `POST /me/profile/preview` puntúa el universo de los últimos 90 días con
  el perfil propuesto y devuelve conteos con universo y ventana (ADR-014);
  el mismo perfil guardado produce el mismo conteo en el Radar (test).
- Un solo asistente, sin modal ni carrusel: páginas dentro de Mi perfil con
  el presupuesto de movimiento del repo.
- Test de componente: saltar en la pantalla dos y volver mantiene lo
  rellenado.

*Adopción:* evento nuevo `asistente_configuracion` con `paso ∈ {1, 2, 3,
4}` y `resultado ∈ {completado, saltado}`; `perfil_configurado` gana
`origen ∈ {asistente, manual, preset}`.

#### J2.2 Plantillas sectoriales de ámbito (D51) — P1

**Para quién.** Quien no sabe por dónde empezar. **Qué.** Seis presets:
consultora SAP, partner Microsoft, integrador Salesforce, desarrollo a medida
y servicios TI, ciberseguridad, datos y BI; cada uno con familias, CPV,
palabras clave, pesos y dos reglas de partida; aplicar uno rellena el
asistente (J2.1) y enseña su vista previa antes de guardar. **Hoy.** Hecho
7. **Depende de.** D51, J2.1. **Esfuerzo / gate.** S · sin gate.

*Aceptación:*
- `config/presets.py` con test de que cada familia y cada CPV citados
  existen en el diccionario y en la lista de CPV.
- Aplicar un preset escribe exactamente los campos que escribiría un perfil
  manual; aplicarlo dos veces no duplica reglas.
- La vista previa de cada preset se calcula con J2.1 y se declara con fecha.

*Adopción:* `perfil_configurado` con `origen=preset` y
`preset ∈ {sap, microsoft, salesforce, desarrollo, ciberseguridad, datos}`.

#### J2.3 Importar el histórico de ofertas (D52) — P0

**Para quién.** Quien ya lleva años presentándose. **Qué.** Un CSV con
expediente o título, órgano, fecha, precio ofertado, resultado y motivo; el
navegador lo lee y lo manda como JSON; el servidor casa cada fila con un
expediente (id exacto, número natural, o título y órgano normalizados con
fecha a treinta días) y devuelve un informe de coincidencias para confirmar;
las filas casadas crean oportunidades cerradas con su resultado; las que no
casan van a `ofertas_historicas`. Desde el primer día alimentan los motivos
de pérdida (F3.1), la baja propia (C6.5) y la calidad del Radar (S3.2, solo
las casadas). **Hoy.** Hecho 9. **Depende de.** D52, motivos (F3.1 / D37).
**Esfuerzo / gate.** M · **[§6]** migración (`ofertas_historicas`,
`import_batches`), pre-autorizada.

*Aceptación:*
- `POST /pursuits/import?dry_run=true` devuelve por fila
  `coincidencia ∈ {exacta, probable, ambigua, ninguna}` con candidatos;
  sin `dry_run` solo importa exactas y confirmadas.
- Idempotente por `(organization_id, hash de la fila)`; límite de dos mil
  filas por lote y de diez lotes por día.
- Test con fixture de veinte filas: doce exactas, cinco probables, tres sin
  coincidencia; ninguna fila crea dos oportunidades del mismo expediente.
- Dato corporativo: fuera del export GDPR de usuario; la importación queda
  en `pursuit_events` con `origen=importacion`.

*Adopción:* evento nuevo `historico_importado` con
`filas ∈ {1-50, 51-500, 501+}` y `coincidencia ∈ {alta, media, baja}`.

#### J2.4 Importar cuentas, competidores y seguimientos — P2

**Para quién.** Quien tiene la lista en una hoja de cálculo. **Qué.** El
mismo importador acepta órganos (a cuentas objetivo, F1.5), empresas
(a la vigilancia de competidores, con el maestro y su cola de revisión) y
expedientes a seguir; informe de coincidencias y confirmación como en J2.3.
**Hoy.** Hecho 9. **Depende de.** J2.3, F1.5. **Esfuerzo / gate.** S ·
**[§6]** migración (`import_batches.tipo`), pre-autorizada.

*Aceptación:*
- Órganos normalizados con `services/dedupe.normalize_organo` y, cuando
  llegue C1.2, resueltos a `organo_id`; empresas por NIF antes que por
  nombre.
- Sin duplicados: importar dos veces la misma lista no cambia nada (test).

*Adopción:* `historico_importado` gana
`tipo ∈ {ofertas, cuentas, competidores, seguimientos}`.

#### J2.5 Ayuda en contexto — P1

**Para quién.** Quien no sabe qué responde cada espacio. **Qué.** Un botón
«?» en la cabecera de cada espacio que abre un panel con: qué pregunta
responde el espacio (la descripción de `console-spaces.ts`), la sección de
`/metodologia` que lo sustenta, el glosario (F1.8), los atajos (el panel de
hoy) y «enviar comentario» (J3.3). **Hoy.** Hecho 11. **Depende de.** Nada;
F1.8 y J3.3 lo completan. **Esfuerzo / gate.** S · sin gate.

*Aceptación:*
- El botón es accesible por teclado y lector, sin `title=` (C7.4); la tecla
  `?` sigue funcionando.
- Cada espacio tiene sección de metodología asignada y un test lo comprueba
  contra `console-spaces.ts`; sin sección, el panel lo dice.

*Adopción:* evento nuevo `ayuda_abierta` con `espacio` y
`seccion ∈ {que_responde, metodologia, glosario, atajos, comentario}`.

#### J2.6 Novedades del producto — P2

**Para quién.** Quien vuelve tras dos semanas. **Qué.** «Qué hay de nuevo»
en la consola: entradas fechadas en `web/src/content/novedades.ts`, escritas
al cerrar cada release, y un punto en el carril cuando hay una entrada
posterior a la última vista (guardada en el navegador). **Hoy.** Hecho 13.
**Depende de.** Nada. **Esfuerzo / gate.** S · sin gate.

*Aceptación:*
- Sin peticiones a hosts externos; el contenido va en el bundle.
- Test de que cada entrada tiene fecha y de que el punto desaparece al
  abrir el panel.
- `release.yml` no cambia: el fichero se edita a mano en la PR de release y
  `make check` avisa si la última etiqueta no tiene entrada.

*Adopción:* evento nuevo `novedades_abiertas` con
`pendientes ∈ {0, 1, 2+}`.

### J3 — Crecer: adopción, ayuda y confianza

#### J3.1 Puesto y espacio de inicio — P2

**Para quién.** Quien entra cada mañana al mismo sitio. **Qué.** La
membresía gana `puesto ∈ {comercial, preventa, direccion, administracion,
otro}` (opcional) y el usuario un espacio de inicio; el valor por defecto
sale del puesto (comercial → Radar, preventa → Oportunidades, dirección →
Dirección de F4.2, administración → Equipo) y el login lo respeta; un
`?redirect=` explícito sigue ganando. **Hoy.** Hecho 5. **Depende de.** F4.2
para el destino de dirección; sin él, Mi Pipeline. **Esfuerzo / gate.** S ·
**[§6]** migración (`organization_memberships.puesto`,
`users.espacio_inicio`), pre-autorizada.

*Aceptación:*
- `safe-redirect.ts` recibe el destino del servidor y conserva la lista de
  rutas seguras; test de que `?redirect=` gana.
- El callback OAuth y el flujo TOTP usan el mismo destino (hoy fijo en tres
  sitios).
- El puesto es visible para la organización y editable por owner/admin;
  nunca viaja a telemetría como texto.

*Adopción:* `sesion_iniciada` gana `destino` con el slug del espacio.

#### J3.2 Embudo de activación medido — P0

**Para quién.** El mantenedor y quien decida qué mejorar. **Qué.** Cablear
`regla_creada`, que hoy no se emite; en backend, activación por
organización: usuarios con perfil, con regla y con oportunidad a siete y a
treinta días del primer login, semana activa por `sessions.last_seen_at`,
y «activado» como los tres pasos hechos; `product_metrics` lo incorpora,
`make product-status` lo imprime y un endpoint de administración lo sirve a
Ops → Administración. Solo agregados. **Hoy.** Hechos 14 y 24. **Depende
de.** Nada. **Esfuerzo / gate.** S · sin gate.

*Aceptación:*
- `regla_creada` se emite en la mutación de crear regla (test de
  componente) y el comentario «pendiente de cablear» desaparece.
- `GET /admin/product-status` con `require_admin`, sin emails ni nombres;
  la CLI y el endpoint usan la misma función.
- La definición de «activado» vive en un solo sitio y un test la fija.

*Adopción:* ninguna propia; es la medida de las demás.

#### J3.3 Comentarios y soporte desde el producto — P1

**Para quién.** Quien encuentra algo roto o le falta algo. **Qué.** «Enviar
comentario» desde la ayuda (J2.5) y desde Ajustes: tipo (idea, problema,
pregunta), texto, espacio y ruta donde se envía, opt-in de contacto; se
guarda en `feedback_producto`, avisa al operador por el mismo canal agrupado
que las solicitudes de acceso y entra en Ops → Administración con estado
(nuevo, en curso, cerrado); el usuario ve el estado de los suyos. Distinto
de F6.2 (dato incorrecto) y del voto del asistente. **Hoy.** Hecho 12.
**Depende de.** Nada; J2.5 lo enlaza. **Esfuerzo / gate.** S · **[§6]**
migración (`feedback_producto`), pre-autorizada.

*Aceptación:*
- Límite de tamaño y de envíos por usuario y día; sin adjuntos.
- La fila guarda `user_id` y organización, no email; el export GDPR incluye
  los comentarios propios.
- Evento `feedback.creado` en el catálogo de webhooks (S4.2) para quien
  quiera llevarlo a su herramienta.

*Adopción:* evento nuevo `comentario_enviado` con
`tipo ∈ {idea, problema, pregunta}`.

#### J3.4 Procedencia en la ficha — P1

**Para quién.** Quien tiene que fiarse del dato delante de un cliente.
**Qué.** Bloque «De dónde sale» en Detalle y en el expediente de la
oportunidad: fuente con su enlace, visto por última vez, última
actualización en la fuente, por qué entró en el corpus
(`inclusion_reason`), versión del filtro y del clasificador, universo de
análisis, versión de la ficha (ya se muestra) y salud de señales del Radar
(ya se muestra); en Competencia, el `MetricScope` que ya viaja se pinta bajo
cada cifra: universo, denominador y salvedad. **Hoy.** Hecho 15. **Depende
de.** Nada. **Esfuerzo / gate.** S · sin gate.

*Aceptación:*
- `LicitacionDetail` gana los campos de linaje como aditivos; el ratchet del
  contrato sigue en cero y `make web-codegen` no deja diff.
- Filas anteriores a `v62` muestran «anterior al linaje», no un guion.
- `MetricScope.caveat` visible en las tres vistas de Competencia que lo
  reciben (test de componente).
- Ningún campo de linaje entra en la superficie pública (test sobre el
  allowlist de `db/repositories/publico.py`).

*Adopción:* evento nuevo `procedencia_abierta` con `espacio`.

#### J3.5 Correos de arranque (D54) — P2

**Para quién.** Quien entró, miró y no volvió. **Qué.** Tres correos, a los
días uno, tres y siete del primer login, cada uno sobre el paso pendiente
(ámbito, regla, oportunidad), calculados con las mismas señales de la banda
de primeros pasos llevadas al servidor; no se envía el correo de un paso ya
hecho; baja en un clic con el enlace firmado que ya usan los digests. **Hoy.**
Hechos 6 y 18. **Depende de.** D54; preferencias (C2.7) para el opt-out
persistente. **Esfuerzo / gate.** S · sin gate.

*Aceptación:*
- Máximo tres correos por usuario en toda su vida; test con fixture de
  fechas.
- Un paso hecho antes del envío lo cancela (test); la baja detiene los
  restantes.
- El envío corre en el plano de GitHub Actions con el resto de digests y
  queda en `ops_events` con conteo.

*Adopción:* ninguna en cliente; el conteo de envíos y bajas va a
`product_status`.

#### J3.6 Uso del equipo para el owner — P2

**Para quién.** Owner y admin. **Qué.** En Equipo, por miembro: última
actividad (`sessions.last_seen_at`), oportunidades a su cargo, comentarios,
reglas y seguimientos; bandera «sin actividad treinta días» con la acción de
suspender. Agregados de tablas que ya existen; ninguna traza de páginas.
**Hoy.** Hecho 16. **Depende de.** Nada. **Esfuerzo / gate.** S · sin gate.

*Aceptación:*
- Solo owner y admin; un `member` no ve la vista (test).
- Cada cifra se calcula en SQL en `db/` con ventana declarada.
- Nada de esto sale de la organización ni va a telemetría.

*Adopción:* `vista=uso` en `espacio_abierto`.

#### J3.7 Benchmarks anónimos entre organizaciones (D53) — P2

**Para quién.** Dirección, para saber si el problema es suyo. **Qué.** En
el cuadro de mando (F4.2), la mediana de plataforma de tasa de éxito,
tiempo de decisión y oportunidades por miembro, con opt-in por organización
y mínimo cinco organizaciones por cifra. **Hoy.** Hecho 17. **Depende de.**
D53, F4.2. **Esfuerzo / gate.** M · **[§6]** migración
(`organizations.benchmarks_opt_in`), pre-autorizada.

*Aceptación:*
- Con menos de cinco organizaciones contribuyendo, la cifra no se publica y
  la UI lo dice (test).
- Opt-in apagado por defecto; quien no contribuye no ve la mediana.
- Test de que ninguna respuesta permite reconstruir el valor de una
  organización (dos organizaciones y una consulta antes y después).

*Adopción:* `vista=benchmarks` en `espacio_abierto`.

### J4 — Dirigir: objetivos, previsión y consumo

#### J4.1 Objetivos comerciales — P1

**Para quién.** Dirección y cada comercial. **Qué.** Objetivos por año o
trimestre y, opcionalmente, por miembro: importe presentado, importe ganado,
ofertas presentadas, ofertas ganadas; progreso en el cuadro de mando (F4.2)
y en Mi Pipeline, calculado desde las oportunidades (`submitted_at`,
`closed_at`, `offer_price_eur`, `awarded_amount_eur`). **Hoy.** Hecho 19.
**Depende de.** Nada; F4.2 lo pinta. **Esfuerzo / gate.** S · **[§6]**
migración (`organization_targets`), pre-autorizada.

*Aceptación:*
- Owner y admin escriben; todos leen los de la organización y los suyos.
- El progreso declara periodo y ventana; sin objetivo, la tarjeta no se
  inventa uno.
- Test: dos oportunidades ganadas en el trimestre → progreso correcto en
  las cuatro métricas.

*Adopción:* evento nuevo `objetivo_definido` con
`metrica ∈ {importe_presentado, importe_ganado, ofertas_presentadas,
ofertas_ganadas}` y `periodo ∈ {anio, trimestre}`.

#### J4.2 Previsión de cierre por trimestre — P1

**Para quién.** Quien planifica el año. **Qué.** Valor ponderado (F4.1)
repartido por trimestre según la fecha prevista de adjudicación (F4.4),
frente al objetivo (J4.1); `TrimestreCount`, muerto desde julio, se retira o
se reutiliza aquí. **Hoy.** Hecho 20. **Depende de.** F4.1, F4.4, J4.1.
**Esfuerzo / gate.** S · sin gate.

*Aceptación:*
- Sin fecha prevista, la oportunidad va a «sin trimestre» y se cuenta
  aparte; nunca se reparte a ojo.
- Declara `n` y el supuesto de probabilidad por etapa (D34).
- Test con fixture de cuatro oportunidades en tres trimestres.

*Adopción:* `vista=prevision` en `espacio_abierto`.

#### J4.3 Tesorería prevista de la cartera — P2

**Para quién.** Quien paga las nóminas. **Qué.** Desde la cartera (F4.3):
facturación mensual (importe entre duración, editable por hitos), cobro
previsto (facturación más treinta días, o más el periodo medio de pago del
comprador de H1.4 cuando exista) y garantía definitiva retenida (5 % por
defecto o la familia `guarantees`); línea de doce meses y CSV. **Hoy.** Hecho
21. **Depende de.** F4.3; H1.4 opcional. **Esfuerzo / gate.** M · sin gate.

*Aceptación:*
- Declara supuestos por contrato (lineal o hitos, plazo de pago usado).
- Test con un contrato de veinticuatro meses y garantía del 5 %.
- Solo organización propia; el CSV pasa por la sanitización de fórmulas de
  `services/exports.py`.

*Adopción:* `vista=tesoreria` en `espacio_abierto`.

#### J4.4 Coste de venta y rentabilidad de ofertar — P2

**Para quién.** Quien decide dónde dejar de ofertar. **Qué.** Con las hojas
de costes (H2.1), el esfuerzo (H2.2) y los cierres (H4.1): coste de ofertar
por periodo, por oportunidad ganada y por segmento (CPV a cuatro dígitos y
órgano), con «dónde no compensa» cuando el coste por ganada supera el margen
medio. **Hoy.** No existe. **Depende de.** H2.1, H2.2, H4.1. **Esfuerzo /
gate.** S · sin gate.

*Aceptación:*
- `n ≥ 5` por segmento; por debajo, «sin datos suficientes».
- Declara cuántas oportunidades del periodo no tienen hoja de costes.

*Adopción:* `vista=rentabilidad` en `espacio_abierto`.

#### J4.5 Consumo de la plataforma por organización — P2

**Para quién.** Owner, y el mantenedor. **Qué.** Tabla `llm_usage` (día,
organización, usuario opaco, modelo, tokens, coste) escrita desde el
`usage_sink` que ya recogen los proveedores; en Equipo → Consumo: coste LLM
del mes frente al presupuesto de organización (C2.9), llamadas por API key
(contador diario), miembros y, cuando exista, almacenamiento (C6.3); Ops lo
ve para todas. **Hoy.** Hecho 22. **Depende de.** C2.9. **Esfuerzo / gate.**
S · **[§6]** migración (`llm_usage`, `api_key_usage_daily`), pre-autorizada.

*Aceptación:*
- Sin texto de preguntas ni respuestas; agregación diaria; retención de
  trece meses con purga en `retention_cleanup`.
- `BudgetGuard` no cambia de comportamiento (tests existentes verdes); la
  tabla es un espejo, no la fuente del límite.
- Un owner ve solo su organización (test de aislamiento).

*Adopción:* `vista=consumo` en `espacio_abierto`.

## 4. Métricas de cierre del plan

Cada una con fecha, medida al cerrar la última entrega de §5 y sesenta días
después. Las de adopción salen del catálogo de `lib/analytics.ts`; las de
activación, de `make product-status` (J3.2); las demás, de los tests.

| Métrica | Hoy (2026-09-06) | Objetivo |
|---|---|---|
| Altas que terminan en una organización preparada (J1.2) | 0 % | ≥ 80 % de las concesiones nuevas |
| Usuarios activados (perfil, regla y oportunidad) a 30 días del primer login (J2.1, J3.2) | sin medir | ≥ 50 % |
| `regla_creada` emitido (J3.2) | 0 eventos | uno por regla creada, verificado en test |
| Organizaciones con histórico importado en el primer mes (J2.3) | no existe | ≥ 40 % de las que entran con J1.2 |
| Filas del histórico casadas sin intervención (J2.3) | no existe | ≥ 70 % en el fixture y en las tres primeras importaciones reales |
| Espacios con ayuda en contexto (J2.5) | 0 de 14 | 14 de 14 y los dos nuevos del tercer plan |
| Campos de linaje visibles por expediente (J3.4) | 2 de 8 | 8 de 8, o «anterior al linaje» |
| `MetricScope.caveat` visible en Competencia (J3.4) | 0 vistas | 3 vistas |
| Comentarios de producto con estado en Ops (J3.3) | no existe | 100 % con estado; ninguno abierto más de 14 días sin respuesta |
| Organizaciones con al menos un objetivo definido (J4.1), a 60 días | no existe | ≥ 50 % de las activas |
| Correos de arranque enviados a pasos ya hechos (J3.5) | no aplica | 0 |
| Cifras de benchmark publicadas con menos de cinco organizaciones (J3.7) | no aplica | 0 |

## 5. Orden de entrega

Cuatro entregas. La primera cabe en unos diez días de agente y no depende
de ningún otro plan; las demás esperan a las decisiones y a las piezas que
citan. Dentro de cada entrega, un stream por rama.

1. **Sin dependencias externas.** J3.2 (cablear `regla_creada` y medir el
   embudo), J3.4 (procedencia), J2.5 (ayuda en contexto), J2.6 (novedades),
   J3.6 (uso del equipo), J4.1 (objetivos) y J1.4 (D50, decisión de una
   línea). Cierra con `make check`, `make check-api-contract` y
   `make web-test`.
2. **Tras las decisiones de acceso y S2.** J1.1, J1.2 (D48, S2.1), J1.3
   (D49), J2.1 (asistente; F6.1 si ya está), J2.2 (D51), J2.3 (D52, D37),
   J2.4 (F1.5), J3.3 (soporte) y J3.5 (D54, C2.7).
3. **Tras el tercer y el cuarto plan.** J3.1 (F4.2), J4.2 (F4.1, F4.4), J4.3
   (F4.3, H1.4) y J4.4 (H2.1, H2.2, H4.1).
4. **Cuando haya masa.** J4.5 (C2.9) y J3.7 (D53, diez organizaciones
   activas).

Dependencias entre ítems de este plan: J1.1 → J1.2 → J1.3; J2.1 → J2.2;
J2.3 → J2.4; J2.5 → J3.3 (el enlace); J4.1 → J4.2. Ninguna otra.

## 6. Lo que NO se hace

- **Backup y restore drill.** Fuera por decisión del mantenedor.
- **Planes, precios y pasarela de pago.** La portada dice que no existen y
  v2 lo deja fuera; J4.5 mide consumo, no factura.
- **Auto-unión sin aprobación.** D49 la limita a `viewer` y solo si el owner
  la activa; nunca por defecto.
- **Tours, modales de bienvenida y carruseles.** El repo tiene un presupuesto
  de movimiento (`docs/frontend-motion.md`) y la banda de primeros pasos ya
  decidió no serlo; J2.1 son páginas, no capas.
- **Telemetría por usuario en el navegador.** J3.2 y J3.6 se calculan en el
  servidor con tablas que ya existen; el catálogo de `lib/analytics.ts` no
  gana identificadores.
- **SSO SAML y aprovisionamiento SCIM.** Como en el complementario.
- **Importar hojas Excel en el navegador.** Solo CSV; sin dependencia
  nueva. Excel se convierte antes.
- **Benchmarks con menos de cinco organizaciones** o sin opt-in.
- **Facturación real.** J4.3 proyecta; no registra facturas ni cobros.
- **Visor de auditoría por organización.** `audit_log` es de plataforma y
  no tiene organización (hecho 23); la actividad del equipo la planifica
  F4.5 sobre el outbox, y este plan no la duplica.
- **Conectores nativos de CRM** antes de que D35 cambie.
