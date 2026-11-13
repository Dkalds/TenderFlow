# Ops y Admin: operar la plataforma

> El turno de guardia de quien administra la plataforma: saber si el sistema responde, si lo programado corrió, si el dato llega bien, y decidir quién entra.

## Para qué sirve y cuándo usarlo

**Ops y Admin** (`/ops`) es el espacio del **administrador de plataforma**: la persona de quien opera TenderFlow, no un usuario de la organización cliente. No hay que confundirlo con el rol «Administrador» de una organización, que se gestiona en [Equipo](12-equipo-y-direccion.md) y no da acceso a este espacio.

Se usa en tres momentos:

- **Cada mañana (o tras un aviso)**: mirar la tira de salud, revisar si algún paso del cierre falló y atender las solicitudes de acceso pendientes.
- **Cuando algo «se ve raro» en la consola**: comprobar si una fuente va con retraso, si el esquema de la base de datos está al día o si hay pares de duplicados sin decidir.
- **De vez en cuando**: etiquetar licitaciones para el modelo de clasificación, revisar usuarios y claves de API, encender o graduar una funcionalidad.

El espacio aparece solo a quien tiene el rol de administrador de plataforma: en el rail, en el último bloque de espacios (junto a Equipo), y en la paleta, bajo «Organización».

## Qué ves en pantalla

### La tira de salud (encima de todas las vistas)

Cuatro cifras que no cambian al cambiar de vista. Cada una es un enlace a la vista donde se contesta entera:

| Celda | Qué dice | Lleva a |
| --- | --- | --- |
| **Fuentes al día** | «X de Y» fuentes que cumplen su plazo; «alguna fuente degradada» si no son todas | Datos |
| **Última ingesta** | Hace cuánto entró dato por última vez: «Al día» (menos de 6 h), «Con retraso» (hasta 24 h) o «Desfasada» (más de 24 h) | Datos |
| **Cola de errores** | Cuántas extracciones fallidas hay: «entradas esperando un reintento», o «vacía» | Ejecuciones |
| **Pasos del cierre** | «Sin fallos» o «N con error», sobre los pasos de su última ejecución | Ejecuciones |

Si una consulta falla, la celda dice **«sin dato»** en lugar de un cero: un cero afirmaría algo que nadie ha medido. La celda «Pasos del cierre» solo la ve un administrador de plataforma.

### Las cinco vistas

En el orden del turno de guardia: **Estado**, **Ejecuciones**, **Datos**, **Etiquetado** y **Administración**. Las pestañas de Ejecuciones y Administración llevan un contador cuando hay algo esperando (pasos con error y solicitudes de acceso pendientes, respectivamente).

**Estado** — si la API y lo que hay debajo responden.

- Botón **«Refrescar»** para volver a pedir el chequeo de salud.
- Tres cifras: **Estado de la API** («En línea», «Degradada» o «Sin conexión», con qué componentes revisar), **Último chequeo** y **Esquema de la base de datos** («Al día» o «Desalineado», con la revisión).
- **Componentes**: una tarjeta por pieza que la API mide (Base de datos, Redis, Disco, Esquema), con una de cuatro insignias: «OK», «Atención», «Error» o «Sin medir». «Sin medir» no es una avería: por ejemplo, un Redis que no está configurado en ese despliegue.
- **Errores en el navegador**: fallos de JavaScript que han visto los usuarios, agrupados, con su Mensaje, Ruta, Veces y Última vez. No guarda IP, correo ni parámetros de la URL.
- **Respuesta del chequeo de salud**: la respuesta de la API tal cual, sin interpretar, para cuando lo de arriba no basta.
- **Métricas en Grafana**: botón **«Abrir Grafana»** si el despliegue tiene configurada su dirección; si no, la tarjeta dice qué variable falta.

**Ejecuciones** — qué pasó con lo que corre solo.

- **Pasos del cierre**: los pasos que corren tras cada ingesta, en el orden en que corren. Columnas: Paso, Tipo («Bloqueante» o «Informativo»), Último resultado, Última ejecución, Última vez bien y Fallos (en la ventana de días que indica el panel). Los resultados posibles son «Bien», «Error», «No tocaba» (el paso decidió no correr: su cadencia no vencía o su funcionalidad está apagada), «Arrastrado» (no corrió porque falló uno del que depende) y «Sin ejecuciones». Un paso bloqueante que falla pone la pasada en rojo; uno informativo solo avisa.
- **Trabajos a demanda**: lo que piden los usuarios y ejecuta el servidor en segundo plano («Ficha del pliego», «Embeddings del expediente», «Exportación a PDF»), con En cola, En curso, Hechos, Fallidos y Último fallo.
- **Cola de errores de la ingesta**: extracciones que fallaron, con dos pestañas («Abiertas» y «Agotadas», las que gastaron todos sus reintentos) y un desglose por tipo de error.

**Datos** — si cada fuente llega a tiempo y si lo que trae viene completo.

- **Cobertura y SLA por fuente**: por fuente, su Estado («Al día» / «Degradada»), Latencia, porcentaje detectado en menos de 24 h (con el tamaño de muestra entre paréntesis), Última ingesta y una Observación. Debajo, aparte, las **Cargas históricas** (lotes de un mes que se cargan una vez y no cuentan en la frescura).
- **Completitud por columna**: porcentaje de registros con cada campo informado, sobre el total de registros que indica el pie.
- **Tendencia de completitud**: lo mismo por mes de publicación (últimos doce meses). Una caída desde un mes concreto apunta a un cambio en la fuente.
- **Formato de las fechas**: qué parte de las fechas de publicación está en formato estándar (mide el formato, no si faltan).
- **Datos reportados por los usuarios**: lo que alguien marcó como erróneo desde la ficha de una licitación, por tipo, con los abiertos.
- **Duplicados por decidir** y **Órganos por decidir**: las dos colas de revisión del dato (ver «Decidir duplicados y órganos», más abajo).
- **Verdad del dato**: la auditoría nocturna del dato contra sus umbrales, por secciones, con «En rango», «Fuera de rango», «Sin medir» o «Sin datos», y la fecha de la medición. Si hay avisos fuera de rango, se pueden desplegar con «Ver el texto de los avisos».
- **Calibración del intervalo de baja**: cuántas de las bajas adjudicadas cayeron dentro del rango p10–p90 que se mostró antes, frente a lo nominal. Dice si el rango viene del «modelo entrenado» o de la «estimación histórica», y queda en «Datos insuficientes» mientras no haya bastantes licitaciones adjudicadas con predicción previa.

**Etiquetado** — revisión humana de si cada licitación es TI y de qué familia.

- Dos cifras: **Etiquetas totales** y **En cola**.
- **Modelo de clasificación**: versión del modelo activo, cuándo se reentrenó, su métrica y cuántas etiquetas se han añadido desde el reentreno.
- **Tecnologías en cola** y la **Cola de etiquetado**, con un selector de **Estrategia**: «Desacuerdo» (por defecto: licitaciones en las que reglas, LLM y modelo no coinciden), «Incertidumbre» y «Aleatoria».

**Administración** — quién entra, quién puede qué y qué está encendido. De arriba abajo: **Solicitudes de acceso**, **Usuarios**, **Claves de API de la instancia**, **Feature flags** y **Webhooks**.

## Cómo se hace

### Conceder acceso a quien lo ha pedido (CU-31, parte del operador)

TenderFlow no tiene alta libre: una persona pide acceso desde la web pública y tú lo concedes aquí.

1. Entra en `/ops` → **Administración**. La tarjeta **Solicitudes de acceso** muestra cuántas hay pendientes y lista, por defecto, las **«Pendientes»** (cambia a **«Todas»** para ver el histórico).
2. Lee la solicitud: correo, empresa, origen, fecha y el mensaje que dejó.
3. Elige una de las tres salidas:
   - **«Conceder email y avisar»**: da acceso solo a esa dirección y le envía un correo con el enlace para crearse la cuenta. Es la opción normal.
   - **«Conceder dominio»**: da acceso a **cualquier** cuenta de ese dominio y también avisa por correo a quien lo pidió. Pide confirmación («Conceder el dominio …») porque afecta a gente que no está en la fila. Resérvalo para clientes ya aprobados. No se puede conceder el dominio de un proveedor de correo público (Gmail, Outlook…): la operación se rechaza con el motivo y no cambia nada; en ese caso usa «Conceder email y avisar».
   - **«Descartar»**: cierra la solicitud. Nunca envía correo.
4. Fíjate en el aviso que aparece:
   - «Solicitud atendida y aviso enviado»: todo bien.
   - «Solicitud atendida, pero el aviso no salió»: el acceso está concedido, pero el correo no llegó a enviarse. Revisa la configuración de correo o escríbele a mano: la solicitud ya queda atendida y desde aquí no se puede reenviar el aviso.

A partir de ahí, la persona se da de alta en `/login` con ese correo y la contraseña que elija, y tiene que activar la cuenta desde el enlace que le llega (ver [Primeros pasos](01-primeros-pasos.md)).

### Revocar o volver a conceder un acceso

1. En la misma tarjeta, baja a **Accesos dinámicos activos**: cada fila dice si es «Correo» o «Dominio», quién lo concedió y cuándo.
2. Pulsa **«Revocar»** y confirma con «Revocar» en el cuadro que se abre. La persona (o el dominio) no podrá **iniciar sesión de nuevo**, tampoco con Google; las sesiones ya abiertas no se cierran. Para cortar a alguien que ya está dentro, desactívalo en **Usuarios**.
3. Las revocadas siguen a la vista en **Accesos revocados**, con la fecha. **«Volver a conceder»** las reactiva y avisa por correo a quien pidió el acceso; solo funciona si existe una solicitud con ese correo o dominio (si no, la fila lo dice y hace falta una nueva).

Si la lista de accesos dinámicos está vacía, no significa que nadie pueda entrar: puede haber accesos fijados en la configuración del despliegue, que no se ven ni se revocan desde aquí.

### Gestionar usuarios (CU-20)

1. **Administración** → **Usuarios**: Correo, Nombre, Rol («Administrador» / «Usuario»), Estado («Activo» / «Desactivado») y Último acceso.
2. En **Acciones**, cada fila ofrece **«Hacer administrador»** / **«Quitar administrador»** y **«Desactivar»** / **«Reactivar»**. Cada una pide confirmación («Sí, …» / «Cancelar»).
3. Desactivar revoca a la vez sus sesiones y sus claves de API. Sobre tu propia fila no hay acciones («Tu cuenta»).

### Revisar y revocar claves de API de la instancia (CU-20)

1. **Administración** → **Claves de API de la instancia**. Arriba, cuatro cifras: Activas, Activas sin dueño, Activas sin caducidad y «Total, con revocadas».
2. La tabla muestra Nombre, Dueño, Permisos, Tier, Creada, Caduca, Último uso («Sin uso registrado» si nunca se usó) y Estado («Activa», «Caducada», «Revocada»). Incluye las claves que no tienen dueño.
3. Pulsa **«Revocar»** y después **«Sí, revocar»**. La clave deja de valer al momento.

Cada persona crea sus propias claves en [Ajustes](11-ajustes.md); aquí solo se ven y se revocan.

### Encender, apagar o graduar una funcionalidad

1. **Administración** → **Feature flags**. Cada funcionalidad muestra su nombre, descripción, «Último cambio» y si está «Activo» o «Inactivo».
2. Usa el interruptor para activarla y, si está activa, el control **Despliegue** para fijar qué porcentaje la recibe.
3. Los cambios quedan en borrador («N cambios sin guardar») hasta que pulsas **«Guardar cambios»**; **«Descartar»** los deshace. Solo se guardan las que cambiaste, así que no pisas lo que haya tocado otro administrador. Si cierras la pestaña con cambios pendientes, el navegador avisa.

### Atender la cola de errores de la ingesta

1. **Ejecuciones** → **Cola de errores de la ingesta** (o pulsa «Cola de errores» en la tira).
2. Mira el desglose «Sin resolver, por tipo de error» para decidir qué salida tiene sentido.
3. En cada entrada (fuente, tipo y mensaje de error, reintentos, desde cuándo):
   - **«Reencolar»** → **«Sí, reencolar»**: la devuelve al ciclo de reintentos. Se reintenta en la **próxima pasada**, no al instante.
   - **«Descartar»** → **«Sí, descartar»**: la cierra sin reintentarla, para lo que un reintento no va a arreglar.

### Decidir duplicados y órganos

1. **Datos** → **Duplicados por decidir**: cada par enseña «Se queda» y «Posible duplicado» (título, fuente, órgano, fecha, importe) y la confianza del detector. Mientras está pendiente, el segundo no sale en los listados pero sigue contando en cuotas e importes.
   - **«Es el mismo»** → **«Sí, es el mismo»**: deja de contar también en las métricas; su ficha sigue abriéndose con el aviso de a cuál duplica.
   - **«No es el mismo»** → **«Sí, son distintos»**: vuelve a los listados.
2. **Datos** → **Órganos por decidir**: «Nombre recibido» frente a «Se parece a». Hasta que decides, sus licitaciones se quedan sin órgano asignado.
   - **«Es el mismo»** → **«Sí, juntarlos»**: la grafía pasa a ser otro nombre del órgano conocido.
   - **«Es otro órgano»** → **«Sí, separarlo»**: queda como órgano propio.

Juntar dos organismos distintos mezcla sus historiales de contratación, y ese error no se ve después en la ficha: ante la duda, sepáralos.

### Etiquetar licitaciones para el modelo

1. **Etiquetado** → elige la **Estrategia** de la cola.
2. En cada tarjeta verás el motivo por el que está en cola (por ejemplo, «El LLM dice que es TI; ni las reglas ni el CPV lo ven»), la propuesta del LLM con su confianza y la predicción del modelo.
3. Decide con una de estas acciones:
   - **«Aceptar propuesta»**: guarda la propuesta del LLM de un clic. No aparece cuando el LLM nombró familias sin una cita del anuncio que las sostenga.
   - Marca familias y fabricantes en la lista (la primera que marques es la principal) y pulsa **«Es TI: …»**. En la predicción del modelo, pulsar una tecnología la hace principal; con Mayús, la añade o la quita.
   - **«Es TI, sin familia»**, **«No es TI»** o **«Saltar»**. **«Limpiar selección»** deshace lo marcado, y **«Nota»** abre un campo para dejar una nota opcional.

## Quién puede usarlo

- Solo el **administrador de plataforma**. El espacio no aparece en el rail ni en la paleta de nadie más.
- Si otra persona abre la URL, **Ejecuciones**, **Etiquetado** y **Administración** muestran «Acceso restringido». **Estado** y **Datos** enseñan lo general (salud de la API, frescura y completitud), pero no los errores del navegador, que ni aparecen, ni las colas de revisión y la verdad del dato, que avisan «Sólo los administradores pueden…». En la tira de salud tampoco ve la celda «Pasos del cierre».
- El rol de administrador de plataforma se da y se quita desde **Usuarios**, por otro administrador.
- Las concesiones y revocaciones de acceso, las decisiones sobre la cola de errores y los cambios de feature flags quedan registrados en el servidor.

## Límites y avisos

- **Las cifras son las que devuelve la API**: la pantalla no rellena huecos. Sin respuesta, verás «sin dato», «Sin medir» o un panel de error con «Reintentar», nunca un cero inventado.
- **«Reencolar» no ejecuta nada en el momento**: deja la entrada lista para la próxima pasada.
- **Revocar un acceso no echa a quien ya está dentro**: impide nuevos inicios de sesión. Para cortar ya, desactiva al usuario.
- **Accesos fijados en la configuración** del despliegue: no se ven ni se revocan desde esta pantalla.
- **Solicitudes**: cada lista trae como máximo las 500 más recientes; si hay más, la tarjeta lo dice. Usa «Pendientes» para no perder ninguna sin atender.
- **Webhooks** aquí es una lista **de solo lectura** de todos los de la instancia, incluidos los antiguos que no tienen organización. Cada equipo crea y edita los suyos en Equipo › Integraciones (ver [Web pública e integraciones](14-web-publica-e-integraciones.md)).
- **Grafana** solo aparece como enlace si el despliegue tiene configurada su dirección.
- **La calibración** mide el rango de baja que se mostró, no una probabilidad de ganar: el producto no da esa probabilidad.
- **Enlaces antiguos**: `/observabilidad`, `/calidad-datos`, `/active-learning`, `/administracion`, `/feature-flags` y `/webhooks` siguen funcionando y llevan a su vista (o sección) dentro de `/ops`.

## Relacionado

- [Primeros pasos](01-primeros-pasos.md): la otra mitad de CU-31, cómo pide acceso y se da de alta la persona.
- [Equipo y Dirección](12-equipo-y-direccion.md): los roles dentro de una organización cliente.
- [Ajustes](11-ajustes.md): sesiones y claves de API de cada persona.
- [Detalle y ficha](04-detalle-y-ficha.md): desde dónde se reporta un dato erróneo.
- [Web pública e integraciones](14-web-publica-e-integraciones.md): el formulario de solicitud y los webhooks de equipo.
- [Glosario](15-glosario.md).
