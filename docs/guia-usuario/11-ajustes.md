# Ajustes: tu cuenta, seguridad e integraciones

> El sitio para lo que es tuyo y de nadie más: dónde tienes la sesión abierta, cómo proteges la cuenta, con qué claves entran tus sistemas, qué avisos te llegan y qué hace TenderFlow con tus datos.

## Para qué sirve y cuándo usarlo

Ajustes (`/ajustes`) lo usa cualquier persona con cuenta, sin importar su rol. No se entra a diario, sino en momentos concretos:

- **Al empezar:** activar la verificación en dos pasos y decidir qué avisos quieres recibir y por dónde.
- **Cuando algo no cuadra:** ver una sesión abierta en un equipo que no reconoces y cerrarla, o cambiar la contraseña.
- **Al integrar:** crear una clave de API para que tu CRM o tus scripts consulten TenderFlow sin navegador, o sacar tus alertas a un lector de feeds.
- **Al irte:** descargar todo lo que TenderFlow guarda de ti y, si quieres, borrar la cuenta.

Se llega desde su icono en el rail de espacios (en el bloque de espacios personales, junto a los de tu seguimiento) o desde la búsqueda ⌘K, donde aparece en el grupo «Mi seguimiento» y la encuentras escribiendo «Ajustes», «2FA», «API keys» o «notificaciones». La antigua dirección `/mi-cuenta` sigue funcionando y abre la vista «Datos y cuenta».

## Qué ves en pantalla

Ajustes tiene cinco vistas, en este orden. La vista activa queda en la URL (`/ajustes?vista=seguridad`, por ejemplo), así que puedes guardarla o compartir el enlace. Sin vista indicada se abre «Sesiones».

| Vista | Qué contiene |
| --- | --- |
| **Sesiones** | Los navegadores donde tienes la sesión abierta ahora mismo. |
| **Seguridad** | La verificación en dos pasos y el cambio de contraseña. |
| **Claves de API** | Tus claves: crearlas, rotarlas, revocarlas y la URL del feed de alertas. |
| **Notificaciones** | Qué avisos quieres y por qué canal. |
| **Datos y cuenta** | Exportar tus datos y eliminar la cuenta. |

**Lo que no está en Ajustes:** el modo claro u oscuro y la densidad de la consola se cambian en el menú de cuenta («Modo oscuro» / «Modo claro», «Densidad compacta» / «Densidad cómoda»), y «Cerrar sesión» también está ahí. En Ajustes no se cambia el nombre ni el correo de la cuenta.

### Sesiones

El panel «Sesiones activas (N)» lista cada sesión abierta y sin caducar. Para cada una ves:

- **Navegador y sistema**, deducidos de lo que el navegador declara (por ejemplo «Chrome · Windows»). Es una pista, no una identificación exacta del equipo. Si no hay datos, pone «Origen desconocido».
- **Desde** la IP de origen, si se conoce, la fecha en que se **inició** y la fecha en que **caduca**.
- La sesión desde la que miras lleva la etiqueta **«Esta sesión»** y, en lugar del botón, el texto «Cierra sesión desde el menú». Las demás tienen el botón **«Cerrar»**.

### Seguridad

De arriba abajo:

- **Verificación en dos pasos.** Si no la tienes, un panel la explica y ofrece «Activar». Si la tienes, el panel muestra la etiqueta **«Activa»** y debajo aparecen dos paneles más: «Códigos de recuperación» (para generar unos nuevos) y «Desactivar la verificación en dos pasos».
- **Contraseña.** El formulario con «Contraseña actual», «Contraseña nueva» y «Repite la contraseña nueva», y el botón «Cambiar contraseña».

### Claves de API

- **Nueva clave:** el campo «Nombre» (hasta 80 caracteres), el botón «Crear» y la casilla «Leer también mis alertas desde un lector de feeds».
- **Tus claves (N):** cada clave con su nombre, una etiqueta con su **plan de uso** (el *tier*, por ejemplo `free`, que fija cuántas peticiones por minuto admite; no se cambia desde aquí) y, si ya no sirve, la etiqueta «Revocada» o «Caducada». Debajo, cuándo se creó, su último uso («Sin usar todavía» si nunca entró) y cuándo caduca o caducó. Las claves vivas tienen los botones «Rotar» y «Revocar».

El último uso es el dato que te dice qué clave retirar: una que nadie usa desde hace meses es la primera candidata.

### Notificaciones

Un panel «Qué avisos quieres recibir» con una fila por tipo de aviso. La lista la manda el servidor, así que si aparece un tipo nuevo lo verás aquí sin que nadie toque la pantalla. Hoy los tipos son:

- Una licitación encaja con mi watchlist
- Una regla guardada encuentra algo
- Resumen diario
- Vence una tarea de una oportunidad
- Me mencionan en un comentario
- Informe semanal de pipeline de mi organización
- Se acerca el fin de un contrato de mi cartera
- Va a caducar un documento acreditativo de mi organización

Cada fila tiene tres selectores, uno por canal: **«En la aplicación»** (la campana), **«Correo»** y **«Webhook»**. Cada uno admite «Al momento», «Resumen diario» o «No avisar».

Lo que nunca has tocado se muestra con el valor por defecto de su canal, que es el que se aplica de verdad: **«Al momento»** en la aplicación, **«Resumen diario»** en el correo y **«No avisar»** en webhook.

### Datos y cuenta

- **Exportar mis datos:** el botón «Descargar mis datos».
- **Eliminar mi cuenta:** un panel en rojo con un campo donde tienes que escribir tu correo y el botón «Eliminar mi cuenta definitivamente», que solo se habilita cuando el correo coincide.

## Cómo se hace

### Cerrar una sesión que no reconoces

1. Ve a **Ajustes › Sesiones**.
2. Localiza la sesión por navegador, IP y fecha de inicio.
3. Pulsa **«Cerrar»**. Sale «Sesión cerrada» y desaparece de la lista; quien estuviera en ese navegador tendrá que volver a entrar.

Para salir del navegador en el que estás, usa «Cerrar sesión» en el menú de cuenta. Si crees que alguien conoce tu contraseña, cámbiala (ver más abajo): eso cierra de golpe todas las demás sesiones.

### Activar la verificación en dos pasos

Necesitas una app de autenticación en el móvil (cualquiera que genere códigos de seis cifras basados en tiempo).

1. Ve a **Ajustes › Seguridad** y pulsa **«Activar»**.
2. En el paso «1. Añade TenderFlow a tu app de autenticación» verás una clave en bloques de cuatro caracteres. En la app, elige añadir una cuenta con clave de configuración y escríbela. También puedes usar «Copiar clave», «Copiar enlace otpauth» (algunos gestores de contraseñas lo aceptan tal cual) o, si estás en el móvil, «Abrir en la app (desde el móvil)». No hay código QR.
3. En el paso «2. Escribe el código que te da la app», teclea el código de seis cifras y pulsa **«Confirmar»**.
4. Aparece el aviso «Guarda ahora tus códigos de recuperación» con diez códigos. **Solo se ven esta vez.** Pulsa «Copiar los diez», guárdalos en un sitio seguro y después pulsa «Ya los he guardado».

Si te quedas a medias, pulsa «Cancelar» y vuelve a «Activar»: empiezas con una clave nueva y la anterior deja de valer. Desde ese momento, al entrar se te pide el código además de la contraseña (o de Google); cómo es esa pantalla está en [Primeros pasos](01-primeros-pasos.md).

### Generar códigos de recuperación nuevos

Para cuando los perdiste o ya gastaste alguno (cada uno sirve una sola vez).

1. En **Ajustes › Seguridad**, panel «Códigos de recuperación», escribe en «Código de la app» el código actual de tu app. Aquí no vale un código de recuperación.
2. Pulsa **«Generar códigos nuevos»**.
3. Guarda los diez nuevos como en el alta. Los que tenías ya no valen.

### Desactivar la verificación en dos pasos

1. En **Ajustes › Seguridad**, panel «Desactivar la verificación en dos pasos», escribe en «Código de la app o de recuperación» el código actual de la app o uno de tus códigos de recuperación (queda gastado).
2. Pulsa **«Desactivar»**. Sale «Verificación en dos pasos desactivada» y la cuenta vuelve a abrirse solo con la contraseña.

Sin un código válido no se puede desactivar, ni siquiera con la sesión abierta.

### Cambiar la contraseña

1. En **Ajustes › Seguridad**, panel «Contraseña», escribe la actual, la nueva y repítela. El icono del ojo muestra u oculta las tres a la vez.
2. Pulsa **«Cambiar contraseña»**.

Al terminar sale «Contraseña cambiada», y además:

- **esta sesión sigue abierta, pero todas las demás se cierran;**
- **todas tus claves de API dejan de valer**: cualquier integración que las use deja de funcionar hasta que crees claves nuevas;
- te llega un aviso por correo.

Si la contraseña actual es incorrecta, no cambia nada y el error («La contraseña actual no es correcta.») aparece bajo el formulario. Tras cinco contraseñas actuales erróneas en un cuarto de hora, el formulario responde «Demasiados intentos. Inténtalo más tarde.» y hay que esperar. La nueva tiene que cumplir la misma política que al crear la cuenta. Si se te olvidó la actual, usa «¿Has olvidado tu contraseña?» en la pantalla de entrada; el efecto sobre sesiones y claves es el mismo.

### Crear una clave de API

1. Ve a **Ajustes › Claves de API**.
2. Escribe un **Nombre** que te permita reconocerla después (por ejemplo «Integración con nuestro CRM»).
3. Si además quieres leer tus alertas en un lector de feeds, marca **«Leer también mis alertas desde un lector de feeds»**.
4. Pulsa **«Crear»**.
5. Aparece el aviso «Guarda esta clave ahora» con la clave completa. **No se puede volver a ver.** Pulsa «Copiar», guárdala en tu gestor de secretos y después pulsa «Ya la he guardado».

Qué puede hacer la clave:

- Sin la casilla, nace con el permiso mínimo: **leer datos** de licitaciones (el permiso `data:read`). No sirve para modificar nada.
- Con la casilla, además puede **leer tus alertas** (el permiso `watchlist:read`).
- Con la configuración por defecto, caduca a los **90 días**. La caducidad no se elige desde esta pantalla.
- Nace con el plan de uso por defecto (`free`).
- Tus sistemas la envían en la cabecera `X-API-Key` de cada petición, sin sesión de navegador. La API está descrita en [Web pública e integraciones](14-web-publica-e-integraciones.md).

### Usar la URL del feed de alertas (RSS)

Solo aparece si creaste la clave con la casilla marcada, y solo en ese momento.

1. Debajo del aviso de la clave verás «Tus alertas en un lector de feeds» con una URL.
2. Pulsa **«Copiar»** y pégala en Feedly, Inoreader, Thunderbird o el lector que uses. Verás lo mismo que casan tus alertas activas en Mi watchlist.
3. La URL lleva la clave dentro y la organización activa en ese momento. Si cambias de organización y quieres el feed de otra, crea otra clave estando en ella.

Quien tenga la URL puede leer tus alertas. Si se filtra, revoca la clave.

### Rotar una clave

Sirve para sustituir una clave sin cortar la integración.

1. En la clave viva, pulsa **«Rotar»**.
2. En «Margen para la clave anterior», elige cuánto tiempo sigue valiendo la vieja: «Ninguno», «Un día», «Una semana» (la opción marcada) o «Un mes».
3. Pulsa **«Rotar clave»**.
4. Guarda la clave nueva del aviso «Guarda esta clave ahora». El aviso te dice hasta cuándo vale la anterior, o «La anterior ya no vale» si elegiste «Ninguno».

La nueva tiene los mismos permisos, empieza una caducidad nueva (90 días con la configuración por defecto) y aparece en la lista con « (rotada)» añadido al nombre. Una clave caducada o revocada no se puede rotar: crea otra.

### Revocar una clave

1. En la clave viva, pulsa **«Revocar»**.
2. Confirma con **«Revocar clave»**. Sale «Clave revocada».

Lo que use esa clave deja de entrar al momento. No se puede deshacer.

### Elegir qué avisos te llegan

1. Ve a **Ajustes › Notificaciones**.
2. En la fila del aviso, abre el selector del canal y elige «Al momento», «Resumen diario» o «No avisar».
3. Se guarda al instante («Preferencias guardadas») y se mantiene aunque recargues. No hay botón de guardar.

Solo se guarda lo que cambias; lo demás sigue en su valor por defecto. Lo que eliges aquí vale para todas tus organizaciones.

**Darse de baja desde el correo:** el correo del informe semanal trae un enlace de baja que pone en «No avisar» el canal «Correo» de «Informe semanal de pipeline de mi organización», sin tocar la campana ni los demás avisos, y te trae a Ajustes. No necesitas iniciar sesión para usarlo. (El enlace de baja del resumen de alertas es otro: pausa tus reglas; ver [Agenda y Watchlist](06-agenda-y-watchlist.md).)

### Exportar tus datos

1. Ve a **Ajustes › Datos y cuenta** y pulsa **«Descargar mis datos»**.
2. Mientras se prepara, el botón dice «Preparando…». Al terminar se descarga `tenderflow-mis-datos.zip` y sale «Datos descargados». Si falla, sale «No se pudieron preparar tus datos» y puedes volver a pulsarlo.

El ZIP contiene ficheros JSON con lo que TenderFlow guarda de tu cuenta: perfil, Watchlist, reglas de alerta, seguimientos, vistas guardadas, datos de tus claves de API (nunca la clave en sí), sesiones, preferencias de aviso y registro de actividad, entre otros.

### Eliminar tu cuenta

1. Si quieres conservar una copia, **exporta antes tus datos**.
2. En **Ajustes › Datos y cuenta**, panel «Eliminar mi cuenta», escribe tu correo tal como aparece en «Escribe … para confirmar» (no importan mayúsculas ni minúsculas).
3. Pulsa **«Eliminar mi cuenta definitivamente»**.

Se anonimiza tu histórico, se borran tus datos personales (watchlist, reglas, perfil, vistas, avisos, preferencias, segundo factor…), sales de tus organizaciones y se revocan todas tus claves de API y sesiones. Vuelves a la pantalla de entrada. **No se puede deshacer.**

Si eres el único propietario de una organización compartida, el borrado se rechaza: primero traspasa la propiedad o borra la organización (ver [Equipo y Dirección](12-equipo-y-direccion.md)). La pantalla no dice el motivo, solo «No se pudo eliminar la cuenta»; si te pasa y entraste hace poco, comprueba esto antes de reintentarlo.

### Integrar a tu equipo por webhook

Los webhooks no están en Ajustes, sino en **Equipo › Integraciones**, porque son de la organización y no de una persona. La pestaña solo la ven el propietario y los administradores.

1. En «Nuevo webhook», rellena «Nombre del webhook» y «URL de destino» (tiene que empezar por `https://`).
2. En «Eventos», elige a qué eventos suscribirte; si no eliges ninguno, recibe «Todos los eventos».
3. En «Formato del mensaje», elige «JSON (genérico)», «Slack · Block Kit» o «Teams · Adaptive Card». Para Slack o Teams, pega la URL del *incoming webhook* del canal y el mensaje llegará ya maquetado.
4. Pulsa **«Crear webhook»** y guarda el secreto del aviso «Guarda este secreto ahora». Solo se ve una vez y sirve para comprobar la firma HMAC de cada entrega.
5. Pruébalo con el icono «Enviar entrega de prueba».

En cada webhook verás su formato, sus eventos, «Última entrega» con el código HTTP y, si las últimas entregas han fallado, una etiqueta «N fallos seguidos». Desde ahí puedes:

- **Activarlo o desactivarlo** con el interruptor.
- **Rotar el secreto** (icono de llave, confirma con «Sí, rotar»). El secreto anterior deja de firmar al momento: carga el nuevo en el receptor o desactiva el webhook mientras tanto.
- **Eliminarlo** (icono de papelera, confirma con «Sí, eliminar»). No se puede deshacer.
- **«Ver entregas»** abre el historial con las columnas Evento, Resultado («OK», «Fallo» o «En cola», con el código HTTP) y Cuándo. Una entrega fallida tiene el botón **«Reenviar»**: se queda en cola para el siguiente ciclo de reintentos, no sale en ese instante.

## Quién puede usarlo

- **Ajustes** es igual para todos los roles, y cada persona solo ve y toca lo suyo: sus sesiones, sus claves y sus preferencias.
- **Una clave no puede dar más permisos que tu cuenta.** Los permisos de administración de la plataforma no se pueden pedir desde aquí.
- **Webhooks:** solo el propietario y los administradores de la organización activa. Un miembro o un lector no los ve. Si quien creó un webhook sale de la organización, el webhook queda inactivo hasta que un propietario o administrador lo reactive.
- **Acciones que piden haber entrado hace poco:** activar o desactivar la verificación en dos pasos, generar códigos de recuperación, crear, rotar o revocar claves, cerrar otra sesión y eliminar la cuenta. Si hace rato que entraste, aparece «Vuelve a entrar para…» con el botón «Volver a entrar»: cierra tu sesión, te lleva a la pantalla de entrada y, al volver, te deja en la misma vista para repetir la acción. Al cerrar una sesión o eliminar la cuenta no sale ese aviso, solo «No se pudo cerrar la sesión» o «No se pudo eliminar la cuenta»: en ese caso, sal, vuelve a entrar y repítelo.

## Límites y avisos

- **Los secretos se ven una sola vez.** Ninguna pantalla vuelve a mostrar una clave de API, un código de recuperación ni el secreto de un webhook después de crearlos. Si los pierdes, crea, rota o genera otros.
- **Cambiar la contraseña desactiva todas tus claves de API.** Ten en cuenta tus integraciones antes de hacerlo.
- **Cuentas sin contraseña:** si entras solo con Google o Microsoft (Microsoft solo existe si tu instalación lo tiene configurado), «Cambiar contraseña» responde que tu cuenta no tiene contraseña. Para crearte una, usa «Crear cuenta» en la pantalla de entrada con el mismo correo y te llegará un enlace para elegirla.
- **Códigos rechazados:** si la app da códigos que no valen, comprueba que la hora del móvil esté en automático. Tras varios fallos seguidos hay que esperar unos minutos.
- **Si pierdes el móvil y no te quedan códigos de recuperación,** no hay forma de entrar desde la consola.
- **Cómo se aplican las preferencias de aviso hoy:**
  - Los selectores de Ajustes deciden de verdad la campana y el correo en estos casos: vencimiento de tareas, menciones, fin de contratos de cartera y caducidad de documentos acreditativos. El canal «Correo» también es la baja del informe semanal.
  - Las alertas de tus reglas y de tu watchlist siguen la **frecuencia de cada regla**, que se cambia en [Mi watchlist](06-agenda-y-watchlist.md). Para dejar de recibir una regla, ponla en pausa allí o desde la campana.
  - **«Webhook»** no te envía nada a ti. Indica si quieres que ese aviso salga por los webhooks de tu organización. Como el webhook es común, el aviso solo deja de salir si **todos** sus destinatarios lo han puesto en «No avisar»; con que uno no lo haya tocado, sale. En webhook, «Resumen diario» equivale a «Al momento».
- **La campana** muestra los avisos de la organización activa; cómo leerla, marcarla y pausar una regla desde ella está en [Primeros pasos](01-primeros-pasos.md).
- **El plan de uso de una clave** (su *tier*) no se elige ni se cambia en Ajustes. Si una integración recibe errores por exceso de peticiones, ese es el límite que se ha superado.

## Relacionado

- [Primeros pasos](01-primeros-pasos.md): entrar con la verificación en dos pasos, recuperar la contraseña y usar la campana.
- [Agenda y Mi Watchlist](06-agenda-y-watchlist.md): reglas de alerta, su frecuencia y la baja desde el correo.
- [Equipo y Dirección](12-equipo-y-direccion.md): roles, la pestaña Integraciones y cómo salir, traspasar o borrar una organización.
- [Web pública e integraciones](14-web-publica-e-integraciones.md): la API, los webhooks y su formato vistos desde fuera.
- [Glosario](15-glosario.md): organización activa, roles y el resto de términos de la consola.
