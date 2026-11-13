# Agenda y Mi Watchlist: plazos y alertas

> La Agenda te dice qué vence y qué tienes pendiente; Mi Watchlist guarda lo que sigues, tus notas y las reglas que te avisan cuando sale algo que encaja.

## Para qué sirve y cuándo usarlo

**Agenda** (`/mi-pipeline`, en la barra lateral junto a Mi Watchlist, Mi perfil y Ajustes; en la paleta de comandos, bajo «Mi seguimiento») responde a una sola pregunta: qué se te escapa si hoy no haces nada. Junta en una cronología los plazos de presentación de tus oportunidades abiertas, las tareas de esas oportunidades (CU-07), los contratos de vuestra cartera que se acercan a su fin y las señales que traen tus reglas y que aún no has triado. Está pensada para mirarla a diario y también funciona en el móvil.

**Mi Watchlist** (`/mi-watchlist`) tiene dos usos:

- **Favoritos**: los expedientes que sigues uno a uno, con una nota personal y etiquetas del equipo (CU-03).
- **Reglas**: criterios que vigilan el mercado por ti y te avisan por correo y en la campana cuando entra una licitación que los cumple (CU-04). Las señales que traen esas reglas son las que llegan al carril «Por triar» de la Agenda.

## Qué ves en pantalla

### Agenda: la franja de contadores

Arriba, cinco botones con su cifra. Cada uno **filtra la lista** al pulsarlo y se quita pulsándolo otra vez; con cifra cero no se puede pulsar.

| Contador | Qué cuenta |
| --- | --- |
| Plazos en 7 días | Oportunidades vivas cuyo plazo de presentación vence hoy o en los próximos 7 días. A su lado, la suma de sus importes. |
| Acciones hoy o vencidas | Tareas cuya fecha es hoy o ya pasó. |
| Go/No-Go pendientes | Oportunidades vivas sin decisión GO/NO-GO. |
| Sin próxima acción | Oportunidades vivas sin próxima acción ni tareas abiertas. |
| Por cerrar | Oportunidades que ya no admiten oferta (el plazo pasó o la licitación está resuelta) y siguen abiertas. |

Una oportunidad ya presentada no cuenta en ninguno; una «por cerrar» solo cuenta en «Por cerrar». La cifra la calcula el servidor y coincide con las filas que deja el filtro.

A la derecha está el botón **Calendario** (ver más abajo). Si la lista viene recortada, un aviso lo dice, por ejemplo: «Agenda parcial: hay más oportunidades que las listadas. Los contadores cuentan solo lo listado» (con tareas o señales, el aviso las nombra igual).

### Agenda: carriles y tramos

La lista tiene dos pestañas:

- **Compromisos**: lo que la organización ya decidió trabajar (oportunidades, tareas y contratos de la cartera).
- **Por triar**: las señales de tus reglas de Mi Watchlist que aún no has seguido ni descartado. Si no tienes ninguna regla activa, esta pestaña no aparece y en su lugar ves «Aún no llega nada por triar. Crea tu primera regla».

El botón **Solo míos** limita la lista a las oportunidades de las que eres responsable y a sus tareas; los contratos de la cartera son de la organización y siguen apareciendo. Junto a él, cuántas filas hay en el carril o con el filtro activo. El carril, el filtro y «Solo míos» quedan en la URL, así que puedes pasar el enlace tal cual. La Agenda respeta también el ámbito global (tecnologías y comunidades autónomas) que tengas puesto.

Dentro de cada carril, las filas van agrupadas por tramos, en este orden: **Vencidas**, **Hoy**, **Próximos 7 días**, **Por cerrar**, **Próximos 30 días**, **Más adelante**, **Presentadas, a la espera** y **Sin fecha**. Cada cabecera lleva su número de filas.

### Agenda: qué dice cada fila

- **Chip de plazo**: días que faltan («5 d»), «hoy» (con hora si se conoce), días de retraso («−3 d»), «presentada», «abierta» (ventana de relicitación ya empezada) o, en «Por cerrar», «resuelta», «adjudicada» o «anulada». Debajo, el día («jue 15 oct»; con año si está lejos).
- **Icono y título**: oportunidad, tarea (el título es lo que hay que hacer), contrato, relicitación o señal. Una tarea justo debajo de su oportunidad aparece sangrada como «Acción de esta oportunidad».
- **Línea de contexto**: primero qué clase de fecha es («Plazo de presentación», «Acción», «Fin de contrato», «Ventana de relicitación»), luego la fase, tareas abiertas, responsable y órgano. En una señal, la regla que la trajo («Regla «…»»). En un contrato, de dónde sale la fecha de fin: «fecha publicada», «fecha estimada por duración», «fecha con prórroga aplicada», «fecha introducida a mano». Si el plazo cae esta semana y nadie ha decidido, delante aparece en ámbar **«Sin decidir»**.
- **Importe**: el de la licitación, una sola vez (no se repite en las tareas que van justo debajo de su oportunidad).
- **Acción**: el botón del siguiente paso (ver «Cómo se hace»). Si en una oportunidad ese paso es decidir, apuntar la acción o retirarla, a su lado hay además una flecha que abre la ficha. En una tarea es «Completar» (o «Editar acción» si es una próxima acción escrita a mano); en un contrato, «Poner fecha de fin», «Preparar renovación», «Ver renovación» o «Ver contrato»; en una señal, «Seguir» y una X para descartarla.

### Agenda: el inspector

En pantallas muy anchas, a la derecha, el panel **Detalle del compromiso** enseña la fila seleccionada: botones arriba («Abrir ficha», «No nos presentamos» si toca, «PLACSP» si hay enlace a la fuente), datos (órgano, importe, CCAA, estado, responsable, adjudicatario si la licitación está cerrada) y, según la clase:

- **Oportunidad o tarea**: «Fechas», con la **Presentación** marcada «Externo» (la fija el órgano) y la **Próxima acción** marcada «Interna» (la pone el equipo); y la lista de **Tareas** con casilla para cerrarlas y un formulario «Añadir una tarea» con fecha opcional. Si no hay tareas: «Sin tareas. La primera que añadas pasa a ser la próxima acción».
- **Contrato**: fin efectivo con su origen, prórrogas aplicadas, ventana de relicitación e importe adjudicado; la nota «Las alertas de este contrato salen a 6, 3 y 1 mes del fin efectivo»; y botones para poner o cambiar la fecha de fin («Poner fecha de fin» / «Cambiar la fecha de fin») o ir a la «Oportunidad ganada» o la «Renovación preparada».
- **Señal**: «Por qué está en la bandeja» (qué regla la trajo) y tres botones: «Seguir», «Posponer 7 d» y «Descartar».

Por debajo de ese ancho el inspector no se muestra; las acciones de cada fila siguen disponibles en la propia fila.

### Mi Watchlist: pestañas

Dos pestañas: **Reglas** (por defecto) y **Favoritos**.

- **Reglas**: arriba el formulario plegable «Nueva regla de seguimiento»; debajo «Reglas (N)», una tarjeta por regla; y, si tienes alguna activa, **Resultados combinados**: las licitaciones que casan tus reglas activas, sin repetir, con título (enlaza a su ficha), órgano, importe, estado y fecha de publicación. Se piden hasta 20 por regla.
- **Favoritos**: cada expediente que sigues con título (enlaza a la ficha), etiquetas, nota, importe, estado, fecha de publicación y los botones «Comparar», nota, etiquetas y «Quitar de favoritos».

Cada tarjeta de regla muestra el nombre, el número de coincidencias («999+» cuando llega al tope del recuento), los criterios principales (palabra clave, CPV, importe mínimo, CCAA, frecuencia) y a qué correo se entrega, o «Solo notificaciones en TenderFlow» si no tiene. Una regla desactivada se ve atenuada. Si no te queda ninguna activa, encima de la lista aparece «Ninguna regla activa: No te llegan avisos ni el resumen diario».

## Cómo se hace

### Repasar la Agenda por la mañana

1. Abre **Agenda** en la barra lateral.
2. Mira la franja: pulsa el contador que quieras resolver (por ejemplo «Plazos en 7 días»).
3. Recorre las filas con `J`/`K` (o las flechas). `⏎` abre la fila; `S` sigue una señal; `X` la descarta; `C` completa la tarea activa (o, en una próxima acción escrita a mano, lleva al campo para editarla). La barra solo muestra los atajos que sirven para las filas visibles.
4. Pulsa el botón de la fila. Según lo que le falte a cada oportunidad, ofrece:
   - **«No nos presentamos»**, si ya no admite oferta;
   - **«Registrar resultado»**, si está presentada y la licitación ya se resolvió (abre la oportunidad);
   - **«Decidir»**, si nadie ha tomado el GO/NO-GO;
   - **«Apuntar acción»**, si no tiene siguiente paso;
   - **«Abrir ficha»** en el resto.

### Decidir GO o NO-GO desde la fila

1. Pulsa «Decidir».
2. Elige **GO** o **NO-GO** y escribe el motivo (es obligatorio).
3. Pulsa «Guardar decisión». Con GO la oportunidad pasa a «Preparando oferta». Con NO-GO se retira, sale de la Agenda y **no se puede reabrir**: la capa lo avisa antes de guardar.

### Apuntar la próxima acción o una tarea

1. En una oportunidad sin siguiente paso, pulsa «Apuntar acción».
2. Escribe qué hay que hacer y, si quieres, para cuándo. Pulsa «Guardar».
3. Se guarda como tarea de la oportunidad: la tarea aparece en la Agenda y la oportunidad deja de contar en «Sin próxima acción».

Desde el inspector puedes además añadir más tareas («Añadir»), marcarlas como hechas con su casilla o, en una próxima acción escrita a mano, editarla en «Editar la próxima acción a mano» y pulsar «Guardar».

### Completar una tarea

Pulsa «Completar» en su fila (o `C`). El aviso trae «Deshacer».

### Cerrar las oportunidades que ya no admiten oferta

1. En el tramo «Por cerrar», pulsa «No nos presentamos» en una fila, o «Retirar las N» en la cabecera del tramo si hay varias.
2. El diálogo lista las oportunidades, todas marcadas. Desmarca la que sí se presentó: se queda en la Agenda para registrarla en su ficha.
3. Pulsa «Retirar» (con varias, el botón dice cuántas: «Retirar 3»). Se cierran como retiradas con el motivo «No presentada» y **no se pueden reabrir**. Si te retiraste por otra causa (precio, solvencia), ciérrala desde su ficha, donde está la lista completa de motivos.

### Triar una señal

1. Abre la pestaña **Por triar**.
2. Elige:
   - **Seguir**: crea una oportunidad con esa licitación y te lleva a ella. Ojo: en la Agenda «Seguir» abre una oportunidad, no añade un favorito.
   - **Posponer 7 d** (solo en el inspector): la señal vuelve sola pasada una semana.
   - **Descartar** (la X de la fila o `X`).
3. Posponer y descartar se deshacen desde el aviso.

### Mantener los contratos de la cartera

- **«Poner fecha de fin»**: si el contrato no tiene fecha de fin, elígela y pulsa «Guardar». De ella sale la ventana de relicitación y queda como fecha puesta a mano.
- **«Preparar renovación»**: cuando se abre la ventana de relicitación y nadie la ha preparado. Escribe el expediente de la relicitación y pulsa «Crear oportunidad»; si ya existía, te lo dice en vez de duplicarla.
- **«Ver renovación»**: si la renovación ya está preparada, lleva a esa oportunidad.

### Llevar tus plazos a tu calendario

1. Pulsa **Calendario** en la franja de la Agenda.
2. Copia la URL con «Copiar» y añádela como suscripción en Google Calendar, Apple Calendar u Outlook. Incluye los plazos de tus oportunidades abiertas y de tus favoritos, y se actualiza sola. También puedes «Descargar .ics».
3. La URL lleva una firma personal: quien la tenga ve tus plazos. Si se filtra, pide una rotación de claves.

### Seguir un expediente y anotarlo (CU-03)

1. Sigue el expediente desde Detalle o el Radar: la estrella de la fila, «Seguir» en la ficha o la tecla `S`. Ver [Detalle y ficha](04-detalle-y-ficha.md).
2. Abre **Mi Watchlist › Favoritos**: aparece con sus datos.
3. Pulsa el icono de nota («Añadir una nota»), escribe y pulsa «Guardar nota» (o `Ctrl`/`Cmd` + `Intro`). `Esc` cancela. Hasta 2000 caracteres. Para borrarla, vacía el texto y pulsa «Borrar nota».
4. Para dejar de seguirlo, pulsa la papelera («Quitar de favoritos»).

### Crear una regla de alerta probándola antes (CU-04)

1. En **Mi Watchlist › Reglas**, abre «Nueva regla de seguimiento».
2. Rellena la **Palabra clave** (obligatoria) y, si quieres, «Filtro CPV», «Importe mínimo», «Comunidad autónoma» y «Frecuencia de notificación»: «En cuanto se detecte (hasta ~4 h)», «Diaria» (la que viene puesta) o «Semanal».
3. Pulsa **«Ver cuántas alertas daría»**: verás cuántas licitaciones coincidirían hoy y las coincidencias por semana de las últimas 8, con una línea de umbral. Si la media pasa de 50 por semana, avisa de que la regla «va a hacer ruido» y propone acotarla con un CPV, un importe mínimo o una comunidad autónoma.
4. Pulsa **«Añadir regla»**. Al crearla o editarla desde la consola, la entrega va al correo de tu cuenta; si la regla no tiene correo, la tarjeta dice «Solo notificaciones en TenderFlow» y los avisos llegan solo a la campana.

Si llegaste desde la paleta de comandos con «Crear regla de watchlist con estos filtros», el formulario viene relleno; lo que no tiene campo aquí (tecnología, órgano, procedimiento) aparece en «Además filtra por», con «Quitar».

### Afinar, pausar o borrar una regla

- **Afinar**: pulsa el lápiz («Editar regla»). En el panel tienes, además de los campos del alta, «Tecnología», «Órgano de contratación» (se compara sin tildes, sin mayúsculas y sin la forma jurídica), «Procedimiento», «Tipo de contrato», «Banda mínima del Radar» («Tibia o mejor», «Atractiva o mejor», «Solo Caliente»; con banda solo mira expedientes abiertos y en plazo) y «Plazo mínimo (días)», de 0 a 365. Pulsa «Probar regla» para ver la vista previa y «Guardar cambios». Tras guardar, la tarjeta se titula con la palabra clave (o, si no hay, con el órgano o la tecnología).
- **Pausar o reactivar**: el botón del ojo («Desactivar» / «Activar»). Corta los avisos sin perder la regla.
- **Borrar**: la papelera abre la confirmación en la propia tarjeta: «¿Eliminar esta regla?» y «Sí, eliminar». Si es tu única regla activa, avisa de que sin ella dejas de recibir avisos y el resumen diario, y ofrece «Desactivar» en su lugar. Borrar no se deshace.

### Leer tus alertas en un lector de feeds

1. Ve a **Ajustes › Claves de API**.
2. En «Nueva clave», escribe un nombre y marca «Leer también mis alertas desde un lector de feeds». Pulsa «Crear».
3. Junto al secreto aparece «Tus alertas en un lector de feeds» con la URL: cópiala y pégala en Feedly, Inoreader, Thunderbird u otro lector. Verás lo mismo que casan tus reglas activas.
4. La URL solo se enseña al crear la clave y lleva la clave dentro: quien la tenga lee tus alertas. Si se filtra, revoca la clave. Más en [Ajustes](11-ajustes.md).

## Quién puede usarlo

- **Agenda**: cualquier miembro, sobre la organización activa. Las señales de «Por triar» son las de **tus** reglas y tu triaje.
- **Favoritos y notas**: tu lista y tus notas son tuyas; otra persona no las ve. En un favorito que también sigue otro compañero, cada uno tiene su nota. Las etiquetas sí son del equipo.
- **Reglas**: cada regla es de una persona dentro de una organización. Crear, editar (también pausar o reactivar) o borrar una regla queda en el rastro de auditoría de la organización (ver [Equipo y Dirección](12-equipo-y-direccion.md)). La baja desde el correo también se registra, pero no figura en ese rastro porque no lleva organización.
- **Alerta diaria por defecto**: cuando un owner o admin guarda las tecnologías de la organización en Equipo › Organización y en ella nadie tiene aún ninguna regla, se crea a su nombre y con su correo una regla diaria por tecnología, hasta cinco, titulada «Alerta por defecto · <tecnología>». Si la organización no declaró tecnologías pero sí CPV, se crea una por CPV («Alerta por defecto · CPV <código>»). Se ve, edita, pausa y borra como cualquier otra. Volver a guardar las tecnologías no la duplica ni la resucita si la borraste. Si la cuenta no tiene correo, no se crea.

## Límites y avisos

- **Las alertas no son instantáneas.** «En cuanto se detecte (hasta ~4 h)» significa eso: TenderFlow revisa las fuentes cada 4 horas y ninguna frecuencia entrega antes. Para un plazo que vence hoy, la fuente oficial sigue siendo el perfil del contratante.
- **El texto se busca tal cual.** La palabra clave se busca en el título y la descripción, sin distinguir mayúsculas; `%`, `_` y `\` no son comodines. El CPV casa por prefijo. Todos los criterios de una regla se suman: si «Resultados combinados» sale vacío, afloja alguno (el importe mínimo o la CCAA suelen ser los que más recortan).
- **Lo que casa es lo que contó la vista previa**, y un expediente nuevo que cumpla la regla aparece sin tocarla.
- **El resumen por correo** (con la frecuencia de cada regla) trae, por licitación, la fecha límite, el importe base sin IVA (o «base desconocida»), hasta tres requisitos de solvencia del pliego y, si tu organización declaró su capacidad, el veredicto del checklist, con enlace a la ficha. «Me interesa» y «No encaja» abren la ficha con esa decisión propuesta; pulsar el enlace no escribe nada hasta que confirmas.
- **Baja desde el correo**: el enlace pausa tus reglas (no las borra). Al volver a Mi Watchlist un aviso dice cuántas quedaron en pausa; se reactivan con el ojo.
- **La Agenda tiene topes**: hasta 500 oportunidades, 500 tareas y 50 señales (25 por regla). Por encima, el aviso «Agenda parcial» lo dice y los contadores cuentan solo lo listado.
- **Las fechas de fin de contrato** pueden ser publicadas o estimadas por duración; la fila y el inspector dicen cuál. Una estimada no vale lo mismo que una publicada.
- **El recuento de coincidencias** de cada regla se corta en 999+: a partir de ahí es «al menos».
- **Nada de esto es una probabilidad de ganar.** Las señales y las bandas solo dicen que la licitación cumple tus criterios o encaja con tu perfil.

## Relacionado

- [Primeros pasos](01-primeros-pasos.md): barra lateral, paleta de comandos y campana.
- [Radar y Mi perfil](03-radar-y-perfil.md): seguir y descartar desde la bandeja diaria.
- [Detalle y ficha](04-detalle-y-ficha.md): marcar favoritos y leer la ficha.
- [Oportunidades](05-oportunidades.md): la ficha de la oportunidad, el GO/NO-GO, la cartera y el cierre.
- [Ajustes](11-ajustes.md): claves de API y feed de alertas.
- [Equipo y Dirección](12-equipo-y-direccion.md): tecnologías de la organización y rastro de auditoría.
- [Glosario](15-glosario.md).
