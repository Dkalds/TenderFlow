# Equipo y Dirección: organización, roles y resultados

> Montar el equipo con sus roles, declarar qué puede acreditar la organización y, si la diriges, ver qué se gana, quién lleva qué y qué ha cambiado.

## Para qué sirve y cuándo usarlo

Son dos espacios del bloque «Organización», el último del rail (en la paleta de comandos salen bajo ese mismo rótulo):

- **Equipo** (`/equipo`): quién está en tu organización y qué puede hacer. Lo usa la propietaria o quien administra el equipo al empezar (crear la organización, invitar, declarar NIF y capacidad) y de vez en cuando después (renovar un certificado que caduca, revisar quién cambió qué). Cualquier miembro entra para ver quién hay y la actividad del equipo.
- **Dirección** (`/direccion`): resultados, carga y actividad del equipo. Es para la propietaria y los administradores: la lectura del lunes («¿vamos mejor o peor?, ¿quién está saturado?, ¿qué falta por registrar?»).

Todo lo que ves en los dos espacios es de la **organización activa**. Se cambia en el selector «Organización activa» de la pestaña «Miembros» o en el menú de tu cuenta; cada organización aparece con tu rol («Equipo comercial · Administrador»).

## Qué ves en pantalla

### Equipo

Arriba, el panel **«Crear organización»** (para trabajar en equipo con otras personas). Debajo, cuatro pestañas: **Miembros**, **Organización**, **Actividad** e **Integraciones** (esta última solo si eres propietario o administrador).

**Miembros**

- **Organización activa**: el selector y, si gestionas, el formulario de alta («Correo de la persona», «Rol» y **«Añadir»**).
- La tabla del equipo, con las columnas **Persona** (nombre y correo), **Rol**, **Estado** («Activo», «Invitado», «Suspendido», «Revocado») y **Acciones** («Revocar» / «Reactivar»).
- **Invitaciones pendientes** (solo propietario y administradores): Correo, Rol, Caduca, Estado («Pendiente», «Aceptada», «Revocada», «Caducada») y los botones **«Reenviar»** y **«Revocar»**.
- **Qué puede hacer cada rol**: una matriz orientativa por rol. Lo que manda es la comprobación de cada acción (ver [Quién puede usarlo](#quién-puede-usarlo)).

Si la activa es tu **organización personal**, la pantalla lo avisa: no admite más miembros. Para trabajar con otras personas hay que crear una compartida.

**Organización** (de arriba abajo)

| Panel | Qué es | Quién lo edita |
| --- | --- | --- |
| Tecnologías de tu organización | Las familias que el Radar puntúa cuando no filtras por tecnología a mano. Vacío significa todas. | Propietario y administradores; el resto lo ve |
| Informe semanal por correo | El resumen semanal de Dirección (embudo abierto, plazos a catorce días, ganadas y perdidas) por correo y en PDF. Nace desactivado. | Solo lo ven propietario y administradores |
| Identidad fiscal | Los NIF/CIF con los que la organización se presenta, con su razón social y cuál es el «Principal». | Solo lo ven y editan propietario y administradores |
| Perfil de capacidad | Documentación acreditativa, facturación, referencias y perfiles de equipo: lo que el checklist de cada oportunidad contrasta con el pliego. | Propietario y administradores; el resto lo ve |
| Tareas al preparar una oferta | Las tareas que se crean, una sola vez, cuando una oportunidad pasa a «Preparando oferta». | Propietario y administradores; el resto lo ve |
| Probabilidad de cierre por etapa | Los porcentajes con los que se pondera el valor del Pipeline. | Propietario y administradores; el resto lo ve |
| Pesos de la matriz go/no-go | Cuánto pesa cada criterio al recomendar ir o no ir. | Propietario y administradores; el resto lo ve |
| Salir / Traspasar / Borrar | El final del ciclo de la organización. | Según rol (ver más abajo) |

Identidad fiscal, perfil de capacidad, tareas y probabilidades no aparecen en la organización personal: no concurre a licitaciones.

**Actividad**

- El feed **«Quién abrió, movió, decidió y cerró cada oportunidad del equipo»**, agrupado por día y del más reciente al más antiguo. Cada línea dice qué cambió («Etapa: Preparando oferta → Presentada», «Decisión», «Resultado», «Motivo»). Si hay más de una persona activa, se puede filtrar con «Todo el equipo» / una persona. Al final, **«Cargar más»** trae lo anterior. Un miembro o un lector ve el feed sin los eventos de administración (invitaciones, cambios de rol); propietario y administradores lo ven entero.
- Debajo, solo para propietario y administradores, el **Rastro de auditoría** (ver [CU-32](#revisar-y-exportar-el-rastro-de-auditoría)).

**Integraciones**: los webhooks de la organización. Se explican en [Web pública e integraciones](14-web-publica-e-integraciones.md).

### Dirección

Tres vistas: **Resultado**, **Carga del equipo** y **Actividad del equipo**. Quien no es propietario ni administrador ve en las tres «Dirección es solo para propietarios y administradores».

**Resultado**

- Arriba, la ventana que se está mirando («Cierres del … a hoy · frente al mismo periodo de hace un año») y el selector de periodo: **«12 meses»** (con el que se entra), **«Este año»** e **«Histórico»**. El histórico no tiene periodo con el que comparar («Cierres de todo el histórico, sin periodo con el que comparar»). Al lado, el enlace **«Embudo completo en Rendimiento»**.
- Cuatro cifras, cada una con su `n` (y su mínimo, en las que lo tienen) y un desplegable **«Cómo se calcula»** que dice de qué universo sale:

| Cifra | De dónde sale |
| --- | --- |
| Importe adjudicado | Suma del importe con el que se adjudicaron las oportunidades ganadas del periodo. Una ganada sin importe registrado no cuenta como cero: se dice aparte. |
| Tasa de éxito | Ganadas sobre ganadas más perdidas; las retiradas no cuentan. Necesita 5 cierres. |
| Valor ponderado del pipeline | Oportunidades abiertas hoy con importe publicado, cada una por la probabilidad de su etapa que configuró tu organización. Es una foto de hoy, no depende del periodo; enlaza a «Reparto por trimestre en Rendimiento». |
| Ciclo de identificada a cerrada (mediana) | Mediana de días entre identificar y cerrar las ganadas y perdidas con las dos fechas. Necesita 5. |

  Debajo de cada cifra, la comparación con hace un año («+12 pp frente a 30 % hace un año»), en verde si mejora y en rojo si empeora. Si no hay base, en lugar de la cifra pone **«Sin base»** con el motivo.
- **Dónde ganamos**: la tasa de éxito por tecnología, tramo de importe, procedimiento y órgano. Cada fila lleva barra (tasa), una línea con el margen al 95 % y un trazo vertical con la media de la organización; «Por encima de la media» o «Por debajo de la media» solo aparece cuando todo el margen queda a un lado. Las filas con menos de 5 cierres se agrupan en un desplegable aparte. El órgano y la tecnología enlazan a Mercado.
- **Por qué perdemos**: reparto de las pérdidas del periodo por motivo, a partir de un mínimo de pérdidas que la pantalla indica; y la lista de **Pérdidas sin motivo codificado**, con enlace a cada oportunidad.
- **¿El Radar ordena bien?**: de las oportunidades abiertas desde el Radar, qué parte se ganó en cada banda de entrada, y si la escalera baja («Ordena bien: lo que pone más arriba se gana más») o no. Solo cuenta las oportunidades que guardan la banda con la que se abrieron.
- **Presentadas sin resultado**: ofertas presentadas que aún no tienen resultado, de la más antigua a la más reciente («presentada hace N días»).

**Carga del equipo**: una fila por miembro activo, también quien no tiene nada abierto, con **Abiertas**, **Presentadas**, **Plazo en 14 días**, **Plazo vencido**, **Sin próxima acción** y **Acción vencida**. Si hay oportunidades sin asignar, al final sale una fila «Sin responsable»; quien ya no está en el equipo pero conserva oportunidades a su nombre también aparece. Los avisos solo cuentan lo que está sin presentar. La vista lee hasta 500 oportunidades abiertas; si hay más, lo avisa: las cifras son un mínimo.

**Actividad del equipo**: el mismo feed que Equipo › Actividad.

## Cómo se hace

### Crear una organización de equipo

1. En `/equipo`, escribe el nombre en «Nombre de la organización».
2. Pulsa **«Crear organización»**. Quedas como propietario y pasa a ser la organización activa («Organización creada»).

Cada persona puede crear hasta 10 organizaciones.

### Invitar a una persona (CU-12)

1. En **Miembros**, con la organización compartida activa, escribe su correo y elige el rol: «Administrador», «Miembro» o «Solo lectura».
2. Pulsa **«Añadir»**.
   - Si ya tiene cuenta, entra al momento («Miembro añadido»).
   - Si no, recibe un correo con un enlace que caduca a los 7 días («Invitación enviada por correo») y aparece en **Invitaciones pendientes**. Al abrir el enlace, entra en TenderFlow con **el mismo correo** al que se envió y queda dentro del equipo.
3. Si el correo no le llegó, pulsa **«Reenviar»**: sale un enlace nuevo y el anterior deja de valer; también sirve con una invitación «Caducada». **«Revocar»** anula una invitación pendiente.

Hay un tope de 100 altas e invitaciones al día por persona.

### Cambiar el rol o retirar el acceso

1. En la tabla de **Miembros**, cambia el rol en el desplegable de la columna «Rol».
2. Para quitar el acceso, pulsa **«Revocar»**: deja de ver la organización. **«Reactivar»** le devuelve el acceso con el mismo rol.

El propietario no se puede degradar ni revocar desde aquí: se traspasa.

### Declarar el ámbito tecnológico

1. En **Organización › Tecnologías de tu organización**, marca las familias.
2. Pulsa **«Guardar tecnologías»**. El Radar ya puntúa con ese ámbito.

Si en la organización nadie tiene aún ninguna regla de alerta, al guardar recibes una alerta diaria por tecnología (hasta cinco), a tu nombre y a tu correo. Ocurre una sola vez: volver a guardar no la duplica y, si la borras, no vuelve. La gestionas en [Agenda y Watchlist](06-agenda-y-watchlist.md) como cualquier otra.

### Declarar NIF y documentación acreditativa (CU-30)

1. En **Identidad fiscal**, pulsa **«Añadir NIF»**, rellena «NIF / CIF» y «Razón social» y marca uno como **«Principal»**. Pulsa **«Guardar»** (solo aparece si hay cambios). Con los NIF, la ficha de una oportunidad propone si la ganó tu organización y Competencia deja de contarla como competidora de sí misma.
2. En **Perfil de capacidad › Certificaciones y documentación administrativa**, añade una fila por documento y elige su **Tipo**: «Certificación técnica», «Al corriente con la AEAT», «Al corriente con la Seguridad Social», «Inscripción en el ROLECE» o «Clasificación empresarial». En las certificaciones técnicas elige además el **Ámbito** («Empresa» o «Equipo»).
3. Pon la fecha en **«Vigente hasta»** (si no caduca, déjala vacía).
4. Completa, si quieres, **Facturación anual** (los tres últimos ejercicios cerrados), **Referencias de contratos** y **Perfiles de equipo**.
5. Pulsa **«Guardar perfil»**.

Tras guardar, **Vigencia de la documentación** lista cada documento por la próxima caducidad: «Caducado el …», «Caduca en N días» (a 60 días o menos), «Caduca mañana», «Caduca hoy», «Vigente hasta el …» o «Sin caducidad declarada». El propietario y los administradores reciben un aviso en la campana y por correo a 60, 30 y 7 días y al caducar, una vez por umbral y documento; si se renueva con otra fecha, vuelve a avisar. El aviso lleva a esta pestaña y se puede apagar en [Ajustes › Notificaciones](11-ajustes.md).

Si una familia del perfil está vacía, el panel lo avisa arriba: el go/no-go responderá «desconocido» en ella.

### Añadir referencias desde contratos ganados

Con los NIF declarados, bajo las referencias aparecen los contratos **adjudicados a tus NIF en los últimos tres años** que aún no figuran como referencia, con órgano, año, tecnología, importe y «Ver la licitación».

1. Pulsa **«Añadir»** en uno, o **«Añadir todos»** (aparece cuando hay más de uno).
2. Revisa el importe: es el **adjudicado**, no el ejecutado.
3. Pulsa **«Guardar perfil»**. Nada se guarda solo.

### Configurar el informe semanal

1. En **Informe semanal por correo**, activa el interruptor («Se envía cada semana»).
2. Elige **Día** y **Hora** (en tu horario; en zonas con media hora de desfase se elige en UTC).
3. En **Destinatarios**, deja vacío para que llegue a propietario y administradores, o escribe hasta 25 correos, uno por línea.
4. Pulsa **«Guardar programación»**. Sale a partir de esa hora y puede tardar hasta cuatro horas. Debajo verás «Último envío» y cómo fue.

Cada destinatario con cuenta puede dejar de recibirlo para sí en [Ajustes › Notificaciones](11-ajustes.md) («Informe semanal de pipeline de mi organización»).

### Plantilla de tareas, probabilidades y pesos

- **Tareas al preparar una oferta**: **«Añadir tarea»**, título y «Días antes del límite» (vacío = sin plazo), y **«Guardar plantilla»**. Hasta 20 tareas. Cambiarla no toca las tareas ya creadas.
- **Probabilidad de cierre por etapa**: enteros de 0 a 100; un campo vacío usa el valor por defecto que se ve en gris. **«Guardar probabilidades»**. Ganadas y perdidas no se ponderan: ya no están en el Pipeline. Son una hipótesis de tu equipo para ponderar el pipeline, no una predicción de TenderFlow.
- **Pesos de la matriz go/no-go**: pesos relativos de 0 a 100 (un 2 cuenta el doble que un 1); al lado de cada uno ves qué parte del total supone. No se pueden poner todos a cero. **«Guardar pesos»**.

### Revisar y exportar el rastro de auditoría

1. En **Actividad**, baja hasta **Rastro de auditoría**.
2. Acota con **Desde** y **Hasta** si quieres. La tabla muestra **Cuándo**, **Qué** («Añadió un miembro», «Cambió el rol de un miembro», «Cambió los NIF», «Cambió el perfil de capacidad», «Cambió los pesos del go/no-go», «Cambió si un adjunto se puede citar», «Traspasó la propiedad»…), **Quién** y **Detalle**. Un evento que no llegó a completarse lleva «No se completó».
3. Pulsa **«Cargar más»** para páginas anteriores, hasta «No hay eventos anteriores en este rango».
4. Pulsa **«Descargar CSV»**. Lleva como mucho los 500 eventos más recientes del rango; si llegas al tope, la pantalla te pide acotar fechas.

El rastro guarda a cada persona por su identificador, nunca por su correo. La pantalla pone en **Quién** el nombre de quien figura en la tabla de Miembros (o su correo, si no tiene nombre); a quien no figura, como «Usuario #id», y lo que hizo el propio sistema, como «Sistema».

### Salir, traspasar o borrar la organización (CU-26)

Al final de **Organización**, según tu rol:

- **Miembro o administrador**: **«Salir de …»** y confirma con **«Salir»**. Dejas de verla en el acto; lo que escribiste sigue firmado con tu nombre. Para volver, te tienen que invitar de nuevo.
- **Propietario**: no puede salir sin más.
  1. **Traspasar la propiedad**: elige en «Nuevo propietario» a un miembro **activo**, pulsa **«Traspasar…»** y confirma con **«Traspasar la propiedad»**. Quedas como administrador.
  2. **Borrar la organización**: pulsa **«Borrar la organización…»**. La confirmación enseña cuántas oportunidades, comentarios y adjuntos se borran y cuántos miembros pierden el acceso. Escribe el nombre exacto y pulsa **«Borrar definitivamente»**. No se puede deshacer. Lo personal de cada miembro (perfil, favoritos, reglas) se queda en su cuenta.

Traspasar y borrar piden una sesión reciente: si hace tiempo que entraste, la pantalla dice «Vuelve a entrar para …» con el botón **«Volver a entrar»**. La organización personal no se sale, no se traspasa ni se borra por aquí.

### Mirar Dirección

1. Abre `/direccion` (aparece en el rail si eres propietario o administrador de una organización compartida).
2. En **Resultado**, elige el periodo. Si una cifra dice «Sin base», abre «Cómo se calcula» y mira la `n`.
3. En **Carga del equipo**, busca números en ámbar o rojo: plazos que vencen en 14 días, vencidos u oportunidades sin próxima acción.
4. En **Actividad del equipo**, filtra por persona si quieres ver lo que hizo alguien.

## Quién puede usarlo

Los roles se muestran como **Propietario**, **Administrador**, **Miembro** y **Solo lectura**.

| Acción | Propietario | Administrador | Miembro | Solo lectura |
| --- | --- | --- | --- | --- |
| Ver miembros y actividad del equipo | Sí | Sí | Sí | Sí |
| Invitar y ver invitaciones | Sí | Sí, como Miembro o Solo lectura | No | No |
| Dar el rol Administrador o cambiar a otro administrador | Sí | No | No | No |
| Pasar a alguien entre Miembro y Solo lectura, revocar o reactivar | Sí | Sí | No | No |
| Editar tecnologías, NIF, capacidad, plantilla, probabilidades y pesos | Sí | Sí | No (lo ve, salvo los NIF) | No (lo ve, salvo los NIF) |
| Informe semanal, rastro de auditoría, Integraciones, Dirección | Sí | Sí | No | No |
| Salir de la organización | No (traspasa antes) | Sí | Sí | Sí |
| Traspasar o borrar | Sí | No | No | No |

La matriz «Qué puede hacer cada rol» de la pantalla es un resumen: por ejemplo, dice que solo el propietario cambia roles, pero un administrador sí puede mover a alguien entre Miembro y Solo lectura. Si una acción no está permitida, la propia acción lo rechaza con su motivo.

## Límites y avisos

- **Separación entre organizaciones (CU-13)**: lo que una organización abre, sigue o vigila no aparece en otra, ni listando ni pidiéndolo por su identificador. El mismo expediente lo puede trabajar cada una por su cuenta.
- **Dirección no publica cifras sin base.** Con menos de 5 cierres (ganadas o perdidas) en todo el histórico, la vista dice «Dirección empieza a publicar con 5 cierres» y solo enseña el pipeline y lo que falta por registrar. Con base histórica pero pocos cierres en el periodo, ofrece **«Ver el histórico»**.
- **Ninguna cifra es una probabilidad de ganar.** La tasa de éxito y la precisión por banda del Radar son lo que pasó con tus cierres registrados; el valor ponderado usa los porcentajes que tu equipo configuró. TenderFlow no predice si vas a ganar una licitación.
- Las cifras salen de lo que el equipo registra en sus oportunidades (etapa, resultado, importe adjudicado, motivo). Una pérdida sin motivo o una ganada sin importe no se inventan: se cuentan aparte y se dicen.
- Las **referencias sugeridas** salen de las adjudicaciones publicadas en las plataformas de contratación. El importe es el adjudicado; un acuerdo marco publica su valor máximo.
- El **estado de vigencia** usa lo guardado: un documento que aún no has guardado no avisa.
- Los **documentos propios** que tu equipo permite citar se gestionan en los Adjuntos de cada oportunidad, no aquí; en el rastro solo queda quién lo permitió o lo retiró. Ver [Oportunidades](05-oportunidades.md) e [Investigador](10-investigador.md).
- Tras salir de una organización o borrarla, deja de ser la activa: pasa a serlo la primera organización de equipo a la que pertenezcas o, si no te queda ninguna, tu organización personal.

## Relacionado

- [Primeros pasos](01-primeros-pasos.md): cuenta, organización activa y acceso por invitación.
- [Radar y perfil](03-radar-y-perfil.md): cómo usa el Radar las tecnologías de la organización.
- [Oportunidades](05-oportunidades.md): checklist go/no-go, tareas, Rendimiento y adjuntos.
- [Agenda y Watchlist](06-agenda-y-watchlist.md): las alertas creadas al guardar las tecnologías.
- [Competencia](09-competencia.md): por qué importan los NIF.
- [Ajustes](11-ajustes.md): avisos de caducidad y notificaciones.
- [Web pública e integraciones](14-web-publica-e-integraciones.md): webhooks del equipo.
- [Glosario](15-glosario.md).
