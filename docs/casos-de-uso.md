# Casos de uso

Lo que una persona tiene que poder hacer con el producto, y qué test lo
demuestra. Es la respuesta a «¿esto sigue funcionando?» cuando la pregunta es
por un recorrido entero y no por un endpoint.

Los tests por ruta fijan cada contrato; ninguno ve si los pasos **encajan entre
sí**. Para eso cada caso de este catálogo necesita al menos un **recorrido**:

- un **test de escenario** (`tests/test_escenario_*.py`): el caso de punta a
  punta por la API, con alta, sesión de cookie y CSRF de verdad
  (`tests/escenarios.py`); o
- un **E2E de navegador** (`web/e2e/*.spec.ts`): el mismo caso en la consola,
  contra Postgres, la API y el build de producción.

`scripts/check_casos_uso.py` lo comprueba (`make check-casos-uso`, y dentro de
la suite en `tests/test_unit_ratchet_casos_uso.py`): un caso sin recorrido
falla, y un test que cita un caso que no existe también.

## Cómo se mantiene

- **Añadir un caso:** un encabezado `### CU-NN — título` con el siguiente número
  libre, y su recorrido en el mismo cambio. Los números no se reutilizan.
- **Citar un caso desde un test:** escribir su identificador en el docstring o
  en un comentario **dentro** del test (`"""CU-07 — …"""`, `// CU-07`). Antes
  del primer test del fichero, la cita vale para el fichero entero.
- **Regenerar la tabla:** `make casos-uso`. No se edita a mano.
- **Un caso que hoy no se puede recorrer** va en `SIN_RECORRIDO`, dentro del
  script, con el motivo. Esa lista solo encoge.

Un caso describe lo que el usuario consigue, no la pantalla de hoy: si la
consola se reorganiza, el caso se queda y su recorrido se actualiza.

## Catálogo

### CU-01 — Entrar y salir de la consola

- **Quién:** cualquier usuario. **Dónde:** `/login`.
- Entra con sus credenciales y queda con sesión; una contraseña incorrecta lo
  dice y no navega.
- El alta self-service solo se ofrece donde el entorno la tiene abierta.

### CU-02 — Buscar un expediente y abrir su ficha

- **Quién:** comercial o preventa. **Dónde:** barra de ámbito, `/detalle`.
- Filtra por texto, comunidad e importe, y obtiene solo expedientes
  clasificados con tecnología.
- Abre la ficha de uno por su enlace permanente; uno que no existe no rompe la
  página.

### CU-03 — Seguir un expediente y anotarlo

- **Quién:** comercial. **Dónde:** `/mi-watchlist`.
- Marca un expediente, le deja una nota y lo recupera en su lista con los datos
  del expediente.
- Su lista es suya: otra persona no la ve. Dejar de seguir lo quita.

### CU-04 — Vigilar el mercado con una alerta

- **Quién:** comercial. **Dónde:** `/mi-watchlist`, reglas.
- Prueba una regla antes de guardarla, y lo que después casa es lo que la vista
  previa contó.
- La afina, y un expediente nuevo que cumple aparece sin tocar la regla.
- Lo que escribe se busca como texto: `%`, `_` y `\` no son comodines.

### CU-05 — Llevar una oportunidad del expediente al cierre

- **Quién:** responsable de la oportunidad. **Dónde:** `/oportunidades`.
- Convierte un expediente en oportunidad (dos veces no la duplica) y la mueve
  por el embudo hasta ganarla, perderla o retirarla.
- El embudo solo avanza, un cierre no se reabre, perder exige un motivo
  codificado y ganar, importe o justificación.
- Las cifras del embudo reflejan lo que pasó.

### CU-06 — Decidir GO o NO-GO con la matriz

- **Quién:** responsable y dirección. **Dónde:** ficha de la oportunidad.
- Puntúa los criterios y recibe una recomendación; la decisión exige motivo.
- Sin GO no hay oferta, y un NO-GO solo puede retirarse.

### CU-07 — Preparar la oferta con tareas

- **Quién:** equipo de preventa. **Dónde:** ficha de la oportunidad, Agenda.
- Crea tareas con fecha, las reparte y las cierra; el estado de cada una
  persiste.

### CU-08 — Vigilar la cartera y preparar la renovación

- **Quién:** responsable de cuenta. **Dónde:** Oportunidades › Cartera.
- La oportunidad ganada pasa sola a la cartera con su importe.
- Pone a mano la fecha de fin que la fuente no publicó, y queda dicho que es
  manual.
- Prepara la oportunidad de la relicitación, una sola vez y sobre otro
  expediente.

### CU-09 — Guardar una vista del ámbito

- **Quién:** cualquier usuario. **Dónde:** barra de ámbito.
- Guarda los filtros con nombre, los recupera tal cual tras recargar y los
  borra. Una vista privada no la ve nadie más.

### CU-10 — Priorizar con el Radar

- **Quién:** comercial. **Dónde:** `/radar`.
- Ve los expedientes puntuados, descarta el que no interesa y deja de verlo.
- Lo recupera cuando quiere; descartar dos veces no duplica.

### CU-11 — Seguir una cuenta objetivo

- **Quién:** responsable de cuenta. **Dónde:** `/cuentas`.
- Busca un órgano, lo convierte en cuenta, la anota y lee su ficha y su
  resumen.
- Al eliminarla, el órgano vuelve a estar libre.

### CU-12 — Trabajar en equipo con roles

- **Quién:** dueña de la organización y sus miembros. **Dónde:** `/equipo`.
- Invita a una persona con un rol; quien solo lee ve y no modifica.
- Asciende, y entonces sí puede mover y comentar; retira el acceso, y deja de
  ver la organización.

### CU-13 — Mantener separados los datos de cada organización

- **Quién:** todo cliente del producto.
- Lo que una organización abre, sigue o vigila no aparece en otra, ni listando
  ni pidiendo el recurso por su identificador.
- El mismo expediente lo puede trabajar cada una por su cuenta.

### CU-14 — Integrar por API con una clave propia

- **Quién:** integrador. **Dónde:** Ajustes › Claves.
- Crea una clave, que se enseña una sola vez y nace con el mínimo privilegio.
- La usa sin sesión, y al rotarla recibe una nueva que funciona.

### CU-15 — Exportar mis datos y borrar mi cuenta

- **Quién:** cualquier usuario (RGPD). **Dónde:** Ajustes › Cuenta.
- Descarga lo que el producto guarda de él.
- Borra la cuenta con confirmación explícita; después no valen ni su sesión, ni
  sus claves, ni sus credenciales.

### CU-16 — Exportar el ámbito a CSV

- **Quién:** cualquier usuario. **Dónde:** barra de ámbito.
- Descarga los expedientes del ámbito en un CSV servido por la API.

### CU-17 — Ajustar mi perfil de puntuación

- **Quién:** comercial. **Dónde:** `/mi-perfil`.
- Cambia pesos y palabras clave, y el cambio persiste y vuelve a los valores
  por defecto si lo borra.
- Unos pesos que no suman cien no se guardan.

### CU-18 — Estudiar a la competencia

- **Quién:** preventa y dirección. **Dónde:** `/competencia`.
- Ve quién gana en su ámbito y abre el perfil de una empresa con sus
  adjudicaciones.

### CU-19 — Gobernar mi cuenta: preferencias y sesiones

- **Quién:** cualquier usuario. **Dónde:** `/ajustes`.
- Una preferencia cambiada sigue ahí tras recargar.
- Ve sus sesiones abiertas, con la actual marcada, y cierra las demás.

### CU-20 — Gestionar la plataforma como administrador

- **Quién:** administrador. **Dónde:** `/ops`.
- Ve usuarios, banderas y ejecuciones; quien no es administrador recibe un
  aviso, no los datos.

### CU-21 — Descubrir el producto en la web pública

- **Quién:** visitante sin cuenta. **Dónde:** portada, hubs y fichas públicas.
- Navega por comunidad, órgano y CPV hasta una ficha, sin datos que la
  superficie anónima no debe enseñar.
- Los buscadores encuentran lo mismo: metadatos, sitemap y enlaces canónicos.

### CU-22 — Leer el pliego con la cita delante

- **Quién:** preventa. **Dónde:** ficha del pliego.
- Desde un dato extraído llega a la página del documento con la cita
  resaltada.

### CU-23 — Preguntar al Investigador en lenguaje natural

- **Quién:** preventa. **Dónde:** `/investigador`.
- Escribe una frase, el producto la interpreta y responde con expedientes y
  pliegos citados.

### CU-24 — Ver el trabajo del equipo desde Dirección

- **Quién:** dirección. **Dónde:** `/direccion`.
- Ve la carga por persona y la actividad reciente de las oportunidades de la
  organización.

### CU-29 — Enterarme de lo que me concierne desde la campana

- **Quién:** cualquier miembro de una organización. **Dónde:** la campana de la
  barra de ámbito, y «Ver todas».
- Ve solo lo suyo en la organización activa: alertas de sus reglas, cambios en
  lo que sigue, menciones, tareas y plazos de sus oportunidades y avisos de la
  organización. Las novedades del mercado no están: son del Resumen.
- Mirar la campana no marca nada; cada aviso se marca al abrirlo, y «Marcar
  todo como leído» es una acción aparte.
- Recorre la lista completa, paginada, filtrando leídos y sin leer, y pone en
  pausa la regla que disparó una alerta sin salir de la campana.

### CU-30 — Tener al día la documentación acreditativa

- **Quién:** propietario o administrador de la organización. **Dónde:**
  Equipo › Organización, perfil de capacidad.
- Declara cada documento con su tipo —certificación técnica, o documentación
  administrativa: corriente con la AEAT y con la Seguridad Social, ROLECE,
  clasificación— y hasta cuándo vale.
- Ve el estado de cada uno (vigente, caduca en N días, caducado, sin caducidad
  declarada), ordenado por la próxima caducidad.
- Recibe en la campana y por correo un aviso a 60, 30 y 7 días y al caducar,
  una sola vez por umbral y documento; renovarlo con otra fecha vuelve a
  avisar en sus umbrales. Lo puede apagar en Ajustes.

## Trazabilidad

<!-- trazabilidad: generado por scripts/check_casos_uso.py — no editar a mano -->

| Caso | Recorrido por la API | E2E en el navegador | Otros tests que lo citan |
|---|---|---|---|
| **CU-01** Entrar y salir de la consola | — | [login.spec.ts](../web/e2e/login.spec.ts) | — |
| **CU-02** Buscar un expediente y abrir su ficha | [test_escenario_seguimiento.py](../tests/test_escenario_seguimiento.py) | [detail-permalink.spec.ts](../web/e2e/detail-permalink.spec.ts) | — |
| **CU-03** Seguir un expediente y anotarlo | [test_escenario_seguimiento.py](../tests/test_escenario_seguimiento.py) | [critical-workflows.spec.ts](../web/e2e/critical-workflows.spec.ts) | — |
| **CU-04** Vigilar el mercado con una alerta | [test_escenario_seguimiento.py](../tests/test_escenario_seguimiento.py) | [recorrido-alerta.spec.ts](../web/e2e/recorrido-alerta.spec.ts) | [test_watchlist_rules_maquina_property.py](../tests/test_watchlist_rules_maquina_property.py) |
| **CU-05** Llevar una oportunidad del expediente al cierre | [test_escenario_oportunidad.py](../tests/test_escenario_oportunidad.py) (x3) | [recorrido-oportunidad.spec.ts](../web/e2e/recorrido-oportunidad.spec.ts) | [test_pursuit_maquina_property.py](../tests/test_pursuit_maquina_property.py) |
| **CU-06** Decidir GO o NO-GO con la matriz | [test_escenario_oportunidad.py](../tests/test_escenario_oportunidad.py) (x2) | [recorrido-oportunidad.spec.ts](../web/e2e/recorrido-oportunidad.spec.ts) | [test_pursuit_maquina_property.py](../tests/test_pursuit_maquina_property.py) |
| **CU-07** Preparar la oferta con tareas | [test_escenario_oportunidad.py](../tests/test_escenario_oportunidad.py) | [recorrido-oportunidad.spec.ts](../web/e2e/recorrido-oportunidad.spec.ts) | — |
| **CU-08** Vigilar la cartera y preparar la renovación | [test_escenario_oportunidad.py](../tests/test_escenario_oportunidad.py) | — | — |
| **CU-09** Guardar una vista del ámbito | [test_escenario_seguimiento.py](../tests/test_escenario_seguimiento.py) | [critical-workflows.spec.ts](../web/e2e/critical-workflows.spec.ts) | — |
| **CU-10** Priorizar con el Radar | [test_escenario_seguimiento.py](../tests/test_escenario_seguimiento.py) | [navigation.spec.ts](../web/e2e/navigation.spec.ts)<br>[recorrido-radar.spec.ts](../web/e2e/recorrido-radar.spec.ts) | — |
| **CU-11** Seguir una cuenta objetivo | [test_escenario_equipo_y_cuentas.py](../tests/test_escenario_equipo_y_cuentas.py) | [recorrido-cuenta.spec.ts](../web/e2e/recorrido-cuenta.spec.ts) | — |
| **CU-12** Trabajar en equipo con roles | [test_escenario_equipo_y_cuentas.py](../tests/test_escenario_equipo_y_cuentas.py) | — | — |
| **CU-13** Mantener separados los datos de cada organización | [test_escenario_equipo_y_cuentas.py](../tests/test_escenario_equipo_y_cuentas.py) | — | — |
| **CU-14** Integrar por API con una clave propia | [test_escenario_equipo_y_cuentas.py](../tests/test_escenario_equipo_y_cuentas.py) | — | — |
| **CU-15** Exportar mis datos y borrar mi cuenta | [test_escenario_equipo_y_cuentas.py](../tests/test_escenario_equipo_y_cuentas.py) | [critical-workflows.spec.ts](../web/e2e/critical-workflows.spec.ts) | — |
| **CU-16** Exportar el ámbito a CSV | — | [critical-workflows.spec.ts](../web/e2e/critical-workflows.spec.ts) | — |
| **CU-17** Ajustar mi perfil de puntuación | [test_escenario_seguimiento.py](../tests/test_escenario_seguimiento.py) | [recorrido-perfil.spec.ts](../web/e2e/recorrido-perfil.spec.ts) | [test_me_profile_routes.py](../tests/test_me_profile_routes.py) |
| **CU-18** Estudiar a la competencia | [test_escenario_competencia.py](../tests/test_escenario_competencia.py) | [recorrido-competencia.spec.ts](../web/e2e/recorrido-competencia.spec.ts) | — |
| **CU-19** Gobernar mi cuenta: preferencias y sesiones | — | [ajustes.spec.ts](../web/e2e/ajustes.spec.ts) | — |
| **CU-20** Gestionar la plataforma como administrador | — | [admin-guard.spec.ts](../web/e2e/admin-guard.spec.ts) | — |
| **CU-21** Descubrir el producto en la web pública | — | [seo.spec.ts](../web/e2e/seo.spec.ts) | — |
| **CU-22** Leer el pliego con la cita delante | — | [pagina-cita.spec.ts](../web/e2e/pagina-cita.spec.ts) | — |
| **CU-23** Preguntar al Investigador en lenguaje natural | [test_escenario_seguimiento.py](../tests/test_escenario_seguimiento.py) | — | — |
| **CU-24** Ver el trabajo del equipo desde Dirección | [test_escenario_equipo_y_cuentas.py](../tests/test_escenario_equipo_y_cuentas.py) | — | — |

**24 casos**, 24 con recorrido y 0 sin él (ver `SIN_RECORRIDO` en `scripts/check_casos_uso.py`).

<!-- fin trazabilidad -->
