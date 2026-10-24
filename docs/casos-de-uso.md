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
- La pestaña «Crear cuenta» se ofrece siempre; el alta solo la completa quien
  tiene el acceso concedido (CU-31).

### CU-02 — Buscar un expediente y abrir su ficha

- **Quién:** comercial o preventa. **Dónde:** barra de ámbito, `/detalle`.
- Filtra por texto, comunidad e importe, y obtiene solo expedientes
  clasificados con tecnología.
- Abre la ficha de uno por su enlace permanente; uno que no existe no rompe la
  página.
- En la ficha ve quién lo ganó —por lote, con NIF, importe adjudicado y número
  de ofertas—, el contrato anterior del mismo órgano con su incumbente y los
  expedientes parecidos.

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
- Lo sigue también desde un lector de feeds, con la URL que le da Ajustes ›
  Claves al crear una clave con permiso para leer sus alertas.

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
- Quien dirige la organización pondera los criterios en Equipo ›
  Organización, y la misma ficha cambia de recomendación sin tocar las
  puntuaciones; quien solo lee ve los pesos y no los cambia.

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
- La usa sin sesión, y al rotarla recibe una nueva que funciona mientras la
  vieja aguanta la gracia.
- Revoca la que ya no usa, y deja de abrir la API al momento.

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
- Ve qué segmentos —familia CPV, comunidad, órgano o tecnología— están
  concentrados; en uno elegido, quién se lo reparte y a qué baja se gana, y
  las bajas medias por órgano, CPV o comunidad. Cada cifra dice sobre qué base
  de importe se calculó.

### CU-19 — Gobernar mi cuenta: preferencias, sesiones y contraseña

- **Quién:** cualquier usuario. **Dónde:** `/ajustes`.
- Una preferencia cambiada sigue ahí tras recargar.
- Ve sus sesiones abiertas, con la actual marcada, y cierra las demás.
- Cambia su contraseña dando la actual (Ajustes › Seguridad): sigue dentro,
  sus otras sesiones y sus claves de API dejan de valer, y le llega un aviso al
  correo. Con una actual equivocada no cambia nada.
- Si la olvidó, la recupera con el enlace que le llega al correo, con el mismo
  efecto sobre sesiones y claves y el mismo aviso.

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

### CU-25 — Proteger mi cuenta con la verificación en dos pasos

- **Quién:** cualquier usuario. **Dónde:** Ajustes › Seguridad.
- La activa con la clave de su app de autenticación y el primer código, y ve
  sus códigos de recuperación una sola vez. Un alta a medias se reempieza.
- Desde entonces, entrar pide el código además de la contraseña; un código de
  recuperación sirve una vez.
- La desactiva con un código vigente, y sin él no.

### CU-26 — Salir, traspasar o borrar una organización

- **Quién:** miembros y propietaria del equipo. **Dónde:** Equipo ›
  Organización.
- Un miembro sale y deja de verla; la propietaria no puede salir sin
  traspasarla antes, y el motivo se lo dice.
- La propietaria traspasa la propiedad a otro miembro activo y queda como
  administradora.
- Antes de borrarla ve cuánto trabajo se lleva el borrado, y lo confirma
  escribiendo el nombre; la organización personal no se borra por aquí.

### CU-27 — Guardar la propuesta del equipo en la oportunidad

- **Quién:** equipo de preventa. **Dónde:** ficha de la oportunidad, Adjuntos.
- Sube los documentos de la oferta, los descarga con un enlace que caduca y
  retira los que ya no sirven; el mismo fichero no se sube dos veces.
- El tamaño y los tipos admitidos los dicta el servidor, y la pantalla los dice
  antes de elegir el fichero.
- Quien solo lee los ve y los descarga, pero no sube ni retira; otra
  organización no los alcanza ni por su identificador.
- Un entorno sin almacén de documentos lo dice y no acepta ningún fichero.

### CU-28 — Acotar Detalle y el tablero por etiqueta, responsable y plazo

- **Quién:** comercial y responsable de oportunidades. **Dónde:** `/detalle`,
  `/oportunidades`.
- Filtra los expedientes por una etiqueta de su organización y obtiene todos
  los etiquetados, con su total, no solo los de la página cargada.
- En el tablero filtra por texto, etiqueta, responsable y plazo de
  presentación —vencido, 7 días, 30 días— sobre todas las oportunidades.
- El plazo cuenta solo en las oportunidades abiertas y sin presentar, igual
  que en Dirección.

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

### CU-31 — Pedir acceso, recibirlo y crearme la cuenta

- **Quién:** una persona sin cuenta, y quien administra los accesos. **Dónde:**
  la portada, el panel de solicitudes y `/login`.
- Pide acceso desde la portada; la operadora lo concede desde el panel y a la
  persona le llega un correo con el enlace para crearse la cuenta.
- Se da de alta con ese correo y la contraseña que elige; hasta que no pulsa
  el enlace de activación que le llega, la contraseña no le deja entrar.
- Sin el acceso concedido, el alta lo dice y no crea nada. Si se revoca, deja
  de poder entrar con su contraseña (también con Google).

### CU-32 — Revisar y exportar lo que cambió en la organización

- **Quién:** propietario o administrador de la organización. **Dónde:**
  Equipo › Actividad, rastro de auditoría.
- Ve, del más reciente al más antiguo, quién entró y salió del equipo, los
  cambios de rol, de configuración, de capacidad y de pesos del go/no-go, con
  quién lo hizo (por su identidad, nunca por su correo).
- Acota por fechas, recorre el rastro página a página sin repetir ni saltarse
  nada y se lo lleva en CSV.
- Un miembro que no administra no lo ve.

### CU-33 — Mantener la integración del equipo por webhook

- **Quién:** propietario o administrador de la organización. **Dónde:**
  Equipo › Integraciones.
- Da de alta un webhook (el secreto se enseña una vez) y lo prueba con una
  entrega de prueba en su formato.
- Rota el secreto tras confirmarlo: recibe uno nuevo, una sola vez, y el
  anterior deja de firmar en el acto.
- Ve en el historial qué entregas fallaron y reenvía una; queda en cola para
  el siguiente ciclo de reintentos.
- Otra organización no ve el webhook ni puede rotarlo ni reenviar sus entregas.

## Trazabilidad

<!-- trazabilidad: generado por scripts/check_casos_uso.py — no editar a mano -->

| Caso | Recorrido por la API | E2E en el navegador | Otros tests que lo citan |
|---|---|---|---|
| **CU-01** Entrar y salir de la consola | — | [login.spec.ts](../web/e2e/login.spec.ts) | — |
| **CU-02** Buscar un expediente y abrir su ficha | [test_escenario_ficha_y_filtros.py](../tests/test_escenario_ficha_y_filtros.py)<br>[test_escenario_seguimiento.py](../tests/test_escenario_seguimiento.py) | [detail-permalink.spec.ts](../web/e2e/detail-permalink.spec.ts) | — |
| **CU-03** Seguir un expediente y anotarlo | [test_escenario_seguimiento.py](../tests/test_escenario_seguimiento.py) | [critical-workflows.spec.ts](../web/e2e/critical-workflows.spec.ts) | [favoritos-nota.test.tsx](../web/src/app/(dashboard)/mi-watchlist/__tests__/favoritos-nota.test.tsx)<br>[use-watchlist-items.test.ts](../web/src/hooks/__tests__/use-watchlist-items.test.ts) |
| **CU-04** Vigilar el mercado con una alerta | [test_escenario_feed_alertas.py](../tests/test_escenario_feed_alertas.py)<br>[test_escenario_seguimiento.py](../tests/test_escenario_seguimiento.py) | [recorrido-alerta.spec.ts](../web/e2e/recorrido-alerta.spec.ts) | [test_watchlist_rules_maquina_property.py](../tests/test_watchlist_rules_maquina_property.py) |
| **CU-05** Llevar una oportunidad del expediente al cierre | [test_escenario_oportunidad.py](../tests/test_escenario_oportunidad.py) (x3) | [recorrido-oportunidad.spec.ts](../web/e2e/recorrido-oportunidad.spec.ts) | [test_pursuit_maquina_property.py](../tests/test_pursuit_maquina_property.py)<br>[test_pursuits_filtros_tablero.py](../tests/test_pursuits_filtros_tablero.py) |
| **CU-06** Decidir GO o NO-GO con la matriz | [test_escenario_gobierno_organizacion.py](../tests/test_escenario_gobierno_organizacion.py)<br>[test_escenario_oportunidad.py](../tests/test_escenario_oportunidad.py) (x2) | [recorrido-oportunidad.spec.ts](../web/e2e/recorrido-oportunidad.spec.ts) | [test_pursuit_maquina_property.py](../tests/test_pursuit_maquina_property.py)<br>[pesos-go-no-go-card.test.tsx](../web/src/app/(dashboard)/equipo/_components/__tests__/pesos-go-no-go-card.test.tsx) |
| **CU-07** Preparar la oferta con tareas | [test_escenario_oportunidad.py](../tests/test_escenario_oportunidad.py) | [recorrido-oportunidad.spec.ts](../web/e2e/recorrido-oportunidad.spec.ts) | — |
| **CU-08** Vigilar la cartera y preparar la renovación | [test_escenario_oportunidad.py](../tests/test_escenario_oportunidad.py) | — | — |
| **CU-09** Guardar una vista del ámbito | [test_escenario_seguimiento.py](../tests/test_escenario_seguimiento.py) | [critical-workflows.spec.ts](../web/e2e/critical-workflows.spec.ts) | — |
| **CU-10** Priorizar con el Radar | [test_escenario_seguimiento.py](../tests/test_escenario_seguimiento.py) | [navigation.spec.ts](../web/e2e/navigation.spec.ts)<br>[recorrido-radar.spec.ts](../web/e2e/recorrido-radar.spec.ts) | — |
| **CU-11** Seguir una cuenta objetivo | [test_escenario_equipo_y_cuentas.py](../tests/test_escenario_equipo_y_cuentas.py) | [recorrido-cuenta.spec.ts](../web/e2e/recorrido-cuenta.spec.ts) | — |
| **CU-12** Trabajar en equipo con roles | [test_escenario_equipo_y_cuentas.py](../tests/test_escenario_equipo_y_cuentas.py) | — | — |
| **CU-13** Mantener separados los datos de cada organización | [test_escenario_equipo_y_cuentas.py](../tests/test_escenario_equipo_y_cuentas.py) | — | — |
| **CU-14** Integrar por API con una clave propia | [test_escenario_equipo_y_cuentas.py](../tests/test_escenario_equipo_y_cuentas.py) | — | [claves-view.test.tsx](../web/src/app/(dashboard)/ajustes/_components/__tests__/claves-view.test.tsx) |
| **CU-15** Exportar mis datos y borrar mi cuenta | [test_escenario_equipo_y_cuentas.py](../tests/test_escenario_equipo_y_cuentas.py) | [critical-workflows.spec.ts](../web/e2e/critical-workflows.spec.ts) | — |
| **CU-16** Exportar el ámbito a CSV | — | [critical-workflows.spec.ts](../web/e2e/critical-workflows.spec.ts) | — |
| **CU-17** Ajustar mi perfil de puntuación | [test_escenario_seguimiento.py](../tests/test_escenario_seguimiento.py) | [recorrido-perfil.spec.ts](../web/e2e/recorrido-perfil.spec.ts) | [test_me_profile_routes.py](../tests/test_me_profile_routes.py) |
| **CU-18** Estudiar a la competencia | [test_escenario_competencia.py](../tests/test_escenario_competencia.py) (x2) | [recorrido-competencia.spec.ts](../web/e2e/recorrido-competencia.spec.ts) | — |
| **CU-19** Gobernar mi cuenta: preferencias, sesiones y contraseña | [test_escenario_cuenta_y_acceso.py](../tests/test_escenario_cuenta_y_acceso.py) | [ajustes.spec.ts](../web/e2e/ajustes.spec.ts) | [cambio-contrasena.test.tsx](../web/src/app/(dashboard)/ajustes/_components/__tests__/cambio-contrasena.test.tsx) |
| **CU-20** Gestionar la plataforma como administrador | [test_escenario_revision_datos.py](../tests/test_escenario_revision_datos.py) | [admin-guard.spec.ts](../web/e2e/admin-guard.spec.ts) | — |
| **CU-21** Descubrir el producto en la web pública | — | [seo.spec.ts](../web/e2e/seo.spec.ts) | — |
| **CU-22** Leer el pliego con la cita delante | — | [pagina-cita.spec.ts](../web/e2e/pagina-cita.spec.ts) | — |
| **CU-23** Preguntar al Investigador en lenguaje natural | [test_escenario_seguimiento.py](../tests/test_escenario_seguimiento.py) | [recorrido-investigador.spec.ts](../web/e2e/recorrido-investigador.spec.ts) | — |
| **CU-24** Ver el trabajo del equipo desde Dirección | [test_escenario_equipo_y_cuentas.py](../tests/test_escenario_equipo_y_cuentas.py) | — | — |
| **CU-25** Proteger mi cuenta con la verificación en dos pasos | [test_escenario_cuenta_y_acceso.py](../tests/test_escenario_cuenta_y_acceso.py) | — | [seguridad-view.test.tsx](../web/src/app/(dashboard)/ajustes/_components/__tests__/seguridad-view.test.tsx)<br>[space-views.test.ts](../web/src/lib/__tests__/space-views.test.ts) |
| **CU-26** Salir, traspasar o borrar una organización | [test_escenario_cuenta_y_acceso.py](../tests/test_escenario_cuenta_y_acceso.py) | — | [ciclo-organizacion.test.tsx](../web/src/app/(dashboard)/equipo/_components/__tests__/ciclo-organizacion.test.tsx) |
| **CU-27** Guardar la propuesta del equipo en la oportunidad | [test_escenario_adjuntos.py](../tests/test_escenario_adjuntos.py) (x2) | — | [adjuntos-panel.test.tsx](../web/src/components/pursuits/__tests__/adjuntos-panel.test.tsx) |
| **CU-28** Acotar Detalle y el tablero por etiqueta, responsable y plazo | [test_escenario_ficha_y_filtros.py](../tests/test_escenario_ficha_y_filtros.py) | — | [use-etiqueta-listado.test.tsx](../web/src/app/(dashboard)/detalle/__tests__/use-etiqueta-listado.test.tsx)<br>[tablero-view.test.tsx](../web/src/app/(dashboard)/oportunidades/__tests__/tablero-view.test.tsx) |
| **CU-29** Enterarme de lo que me concierne desde la campana | [test_escenario_campana.py](../tests/test_escenario_campana.py) | — | [notification-bell.test.tsx](../web/src/components/__tests__/notification-bell.test.tsx)<br>[ver-todas-sheet.test.tsx](../web/src/components/campana/__tests__/ver-todas-sheet.test.tsx) |
| **CU-30** Tener al día la documentación acreditativa | [test_escenario_documentacion.py](../tests/test_escenario_documentacion.py) | — | [page.test.tsx](../web/src/app/(dashboard)/equipo/__tests__/page.test.tsx)<br>[organizacion-documentacion.test.tsx](../web/src/app/(dashboard)/equipo/_components/__tests__/organizacion-documentacion.test.tsx) |
| **CU-31** Pedir acceso, recibirlo y crearme la cuenta | [test_escenario_alta_tras_concesion.py](../tests/test_escenario_alta_tras_concesion.py) | — | — |
| **CU-32** Revisar y exportar lo que cambió en la organización | [test_escenario_gobierno_organizacion.py](../tests/test_escenario_gobierno_organizacion.py) | — | [auditoria-organizacion-card.test.tsx](../web/src/app/(dashboard)/equipo/_components/__tests__/auditoria-organizacion-card.test.tsx) |
| **CU-33** Mantener la integración del equipo por webhook | [test_escenario_webhooks.py](../tests/test_escenario_webhooks.py) | — | [webhook-row.test.tsx](../web/src/app/(dashboard)/ops/_components/webhooks/__tests__/webhook-row.test.tsx) |

**33 casos**, 33 con recorrido y 0 sin él (ver `SIN_RECORRIDO` en `scripts/check_casos_uso.py`).

<!-- fin trazabilidad -->
