# Oportunidades: del expediente a la oferta

> El espacio donde el equipo trabaja las licitaciones que ha decidido perseguir: decidir si se presenta, preparar la oferta, registrar el resultado y vigilar los contratos ganados hasta su renovación.

## Para qué sirve y cuándo usarlo

**Oportunidades** (`/oportunidades`) es el espacio de ejecución. Una oportunidad nace cuando alguien pulsa «Abrir oportunidad» en el Radar o en la ficha de Detalle (ver [Radar y Mi perfil](03-radar-y-perfil.md) y [Detalle y ficha](04-detalle-y-ficha.md)); abrirla dos veces sobre el mismo expediente no crea dos. A partir de ahí la usan:

- **El responsable de la oportunidad**, a diario: mueve las tarjetas por fases, apunta la próxima acción y registra el resultado.
- **El responsable y la dirección**, en el momento del GO o NO-GO: contrastan lo que pide el pliego con la capacidad de la organización.
- **El equipo de preventa**, mientras se prepara la oferta: kit de documentos, precio, adjuntos y conversación.
- **El responsable de cuenta**, después de ganar: la Cartera de contratos y la renovación.

El espacio tiene tres vistas, que se eligen en la cabecera: **Tablero** (la de entrada), **Cartera** y **Rendimiento**.

## Qué ves en pantalla

### Tablero

Una franja de cuatro cifras de toda la organización y, debajo, una columna por fase:

| Columna | Qué significa |
| --- | --- |
| Identificada | Detectada en el Radar, sin cualificar. |
| En cualificación | Se está comprobando encaje y solvencia. |
| Decisión | Esperando el GO o el NO-GO del comité. |
| Preparando oferta | Trabajo activo sobre la propuesta. |
| Presentada | Entregada, pendiente de resultado. |
| Cerradas | Ganadas, perdidas o retiradas. |

Cada columna dice cuántas tarjetas tiene, no cuánto suman: no hay importe por columna. Si un expediente tiene varias oportunidades (una por lote), se agrupan bajo su título con el aviso «N oportunidades de este expediente».

Cada **tarjeta** muestra: título (enlace a la ficha), órgano, lote si lo hay, la **oferta prevista** en grande (o «Sin oferta · a completar» en ámbar; en las cerradas, el importe «adjudicado»), la próxima acción con su vencimiento, las etiquetas, el responsable («Sin responsable» si no hay), el botón de la conversación del equipo y una barra con los días que faltan para el plazo de presentación (roja hasta 3 días, naranja hasta 7, amarilla hasta 21, verde después). El estado solo aparece como etiqueta en «Cerradas».

La **franja de arriba** (siempre de toda la organización, aunque filtres):

| Cifra | De dónde sale |
| --- | --- |
| Valor del pipeline | Importe de licitación de cada oportunidad abierta multiplicado por el porcentaje que tu organización asigna a su fase. |
| Previsión del trimestre | Lo mismo, repartido por trimestre de adjudicación prevista; se muestra el último trimestre de la serie. |
| Sin importe publicado | Oportunidades abiertas cuyo expediente no publica importe: quedan fuera de las dos cifras anteriores. |
| Ganadas · adjudicado | Acumulado histórico de la organización: número de ganadas e importe adjudicado. |

Los porcentajes por fase son **supuestos de la organización**, no una probabilidad de ganar calculada para cada oportunidad. Por defecto valen 10 %, 20 %, 30 %, 50 % y 60 % de «Identificada» a «Presentada»; los cambia un propietario o administrador en Equipo › Organización («Probabilidad de cierre por etapa»).

En la cabecera del tablero están los filtros y la exportación: «Exportar a CRM», el selector de responsable (solo si la organización tiene al menos dos miembros activos), el de plazo («Cualquier plazo», «Plazo vencido», «Vence en 7 días», «Vence en 30 días»), el de etiqueta (solo si tu organización usa etiquetas) y la búsqueda «Título, referencia o responsable».

### Ficha de una oportunidad

Al pulsar el título de una tarjeta se abre `/oportunidades/<id>`. Arriba: el expediente, el lote (o «Expediente completo»), las etiquetas (con el control para ponerlas o quitarlas), el título, el órgano y el responsable, y los botones «Descargar PDF» (una hoja resumen de la oportunidad), «Preguntar a la IA» (abre el asistente con este expediente como contexto), «Ver en Detalle» y la X para volver al tablero.

Debajo, el **recorrido de fases**: las seis casillas, con las ya pasadas marcadas y la actual resaltada. Es informativo; no se pulsa. Al cerrar, la última casilla dice el resultado («Ganada», «Perdida», «Retirada»).

Las pestañas son: **Resumen**, **Expediente**, **Pliego**, **Precio**, **Adjuntos** y **Conversación** (con el número de comentarios).

- **Expediente**: los datos publicados de la licitación, su descripción, «Pliegos y documentos» y la señal tecnológica.
- **Pliego**: la «Ficha estructurada del pliego» («Extraer ficha» o, si ya existe, «Reprocesar ficha») y el «Guion de la oferta técnica»: un esquema de puntos a cubrir por cada criterio de adjudicación, con citas al pliego, que se crea con «Generar guion» y se descarga en Markdown o PDF. No redacta la oferta.
- **Precio**, **Adjuntos**: ver más abajo.
- **Conversación**: los comentarios del equipo sobre la oportunidad («Escribe un comentario para el equipo…» y «Publicar»).

En **Resumen**, de arriba abajo:

1. **«Este expediente ya se adjudicó»**: solo aparece si la fuente ya publicó la adjudicación. Muestra adjudicatarios, importe, número de ofertas y fecha y, si el acta de la mesa trae puntuaciones, tu nota frente a la de la ganadora criterio a criterio, con enlace a la página del acta; si TenderFlow no reconoce tu fila, puedes marcar cuál es tu empresa.
2. **Checklist go/no-go**: cada requisito del pliego frente a lo que tu organización ha declarado, con veredicto «Cumple», «No cumple» o «Desconocido», el «Dato de la organización» (o «sin declarar») y las citas del pliego con su página. Un requisito sin cita nunca sale como «Cumple». Una certificación vigente hoy pero que caduca antes de la fecha límite de presentación sale «No cumple», con las dos fechas en el motivo: la solvencia se acredita a esa fecha, y así hay tiempo de renovarla y actualizar su vigencia en Equipo › Organización. El título dice de qué ficha del pliego sale el contraste (fecha, versión del extractor y, si se usó, la publicación oficial de PLACSP).
3. **«Para salir de «<fase>»»**: lo que falta para pasar a la siguiente fase, con un contador «N de M». Ver la tabla más abajo.
4. **Decisión del comité**: el GO o NO-GO con su motivo.
5. A la derecha (o debajo en pantallas estrechas), los **datos**: Oferta prevista, Plazo de presentación, Importe de licitación (o del lote), Responsable y Adjudicación prevista (o Importe adjudicado si está cerrada), más la **Próxima acción**.
6. **Kit de presentación**, **Historial**, **Matriz ponderada** (plegada) y **Editar todos los campos** (plegado).

Lo que pide cada fase para salir:

| Fase | Pasos que comprueba |
| --- | --- |
| Identificada | Responsable asignado, fecha límite conocida, próxima acción planificada. |
| En cualificación | Requisitos del pliego contrastados, oferta prevista estimada. |
| Decisión | Oferta prevista fijada, decisión GO registrada (obligatorio) y motivo anotado (obligatorio). |
| Preparando oferta | Documentación del kit lista, oferta prevista con el precio final. |
| Presentada | Seguimiento de la mesa planificado, adjudicación publicada detectada. |

Un círculo discontinuo significa «sin dato para decidirlo» (por ejemplo, el pliego no trae requisitos extraídos), no «pendiente». Lo que quedó pendiente en una fase anterior se sigue mostrando con el aviso «Quedó pendiente en «<fase>»». Solo los pasos marcados «obligatorio» impiden avanzar; los demás son recomendaciones.

La **Adjudicación prevista** es una fecha publicada por el órgano o, si no la hay, una estimación (marcada «Estimación») que se muestra como un intervalo de fechas, calculado con la fecha límite más el plazo habitual del órgano; debajo dice la mediana y sobre cuántas adjudicaciones se calcula. Si el órgano no tiene histórico suficiente, o falta la fecha límite, dice «Sin estimación».

### Cartera

`/oportunidades?vista=cartera` muestra los contratos ganados. Una oportunidad cerrada como ganada entra aquí sola. Arriba, cuatro cifras de la cartera completa (no las recortan los filtros): **Contratos vivos** (sin fecha de fin o con el fin por delante), **Importe en ejecución**, **Vencen en 6 meses** (con el importe en juego) y **Sin renovación preparada** (de los que vencen en 6 meses; en ámbar si hay alguno).

La tabla «Contratos en ejecución» tiene las columnas Contrato, Fin efectivo, Prórrogas, Relicitación esperada y Adjudicado. Junto a la fecha de fin, una etiqueta dice de dónde sale: **publicada** (por la fuente), **estimada** (inicio más duración), **con prórroga** (incluye prórrogas registradas) o **manual** (puesta por el equipo). La relicitación esperada es una ventana estimada de 6 a 3 meses antes del fin, no una fecha publicada. Se puede filtrar por tecnología y por órgano.

En pantallas anchas, el botón «Detalle» de cada fila abre a la derecha el contrato con su inicio, importe, enlace al expediente y la **Cronología del contrato** (adjudicación, formalización, modificaciones de importe, prórrogas, anulación) tal como la publica la fuente.

### Rendimiento

`/oportunidades?vista=rendimiento` mide el embudo en una ventana que eliges arriba a la derecha: «12 meses», «Este año» o «Histórico» (por defecto). La línea «Ventana:» dice las fechas exactas. Todas las cifras las calcula el servidor sobre esa ventana:

- **Tasa de éxito** (ganadas sobre ganadas + perdidas), **Importe adjudicado**, **Mediana de decisión** (de identificada a GO/NO-GO) y **Perdidas**.
- **Embudo de oportunidades**: Identificadas → Presentadas → Ganadas, con el porcentaje de cada paso. Cuenta oportunidades, no expedientes.
- **Valor ponderado del pipeline**: el mismo cálculo que la franja del tablero, pero sobre las oportunidades abiertas de la ventana (con «Histórico» coincide con la franja), con los porcentajes por etapa usados y la previsión por trimestre. La pantalla lo dice: «Es un supuesto, no una previsión de cobro».
- **Pérdidas por motivo**: el reparto solo se publica a partir de 5 pérdidas cerradas en la ventana; por debajo dice cuántas hay.
- **Calidad del Radar**: por cada banda del Radar, cuántas oportunidades se siguieron, cerraron y ganaron, y el acierto (ganadas sobre resueltas). Por debajo de 10 resueltas en una banda muestra «aún no» con las que hay.

## Cómo se hace

### Mover una oportunidad de fase

1. En el tablero, arrastra la tarjeta a la columna siguiente, o usa el menú de los tres puntos de la tarjeta y elige la fase.
2. Desde la ficha, pulsa el botón del bloque «Para salir de…»: «Empezar a cualificar», «Llevar a decisión», «Empezar la oferta» o «Marcar presentada».
3. Si el movimiento no está permitido, la columna no acepta la tarjeta y el menú muestra esa fase desactivada; en la ficha, el botón aparece desactivado con el motivo al lado (por ejemplo, «Preparar o presentar una oferta exige la decisión GO.»).

Reglas: solo se avanza a la fase siguiente o se retira; no hay vuelta atrás ni «Deshacer». «Preparando oferta» y «Presentada» exigen la decisión GO; con GO tomado se puede saltar de «Identificada» o «En cualificación» directamente a «Preparando oferta». Si alguien del equipo movió la misma tarjeta a la vez, se avisa y el tablero se recarga con su cambio. Cada movimiento queda en el historial, con quién y cuándo. Al entrar en «Preparando oferta» se crean las tareas de la plantilla de tu organización, si la tiene configurada en Equipo.

### Asignar responsable, oferta prevista y próxima acción

1. En la columna de datos de la ficha, pulsa el lápiz de «Oferta prevista» o de «Responsable» y guarda; o pulsa «Asignar» / «Anotar» junto al paso pendiente del bloque de salida.
2. En «Próxima acción», pulsa «Añadir» (o «Editar»), escribe «Qué toca hacer» y «Cuándo vence», y pulsa «Guardar». Debajo se ve «Vence hoy», «Vence en N d» o «Vencida hace N d», y el punto de la izquierda se pone rojo si vence hoy, mañana o ya ha vencido.

### Decidir GO o NO-GO

1. Abre la ficha: lo primero es el **Checklist go/no-go**. Revisa los «No cumple» y los «Desconocido». Si lo que falta es el dato de tu organización, el requisito enlaza a Equipo › Organización para completarlo. Si no hay ficha del pliego, el checklist ofrece «Abrir la pestaña «Pliego»» para extraerla.
2. En **Decisión del comité** (fase «Decisión»), pulsa «GO» o «NO-GO», escribe el «Motivo de la decisión» y pulsa «Guardar decisión». Sin motivo no se guarda.
3. Antes de llegar a esa fase puedes usar «Decidir ya»: un GO lleva la oportunidad directamente a «Preparando oferta»; un NO-GO la retira (como «No presentada») y no se puede reabrir.
4. Con NO-GO, desde «Decisión» solo cabe «Retirar la oportunidad». Corregir una decisión después de esa fase se hace en «Editar todos los campos».

Opcionalmente, abre la **Matriz ponderada** («Opcional: puntúa cinco criterios de 1 a 5 con los pesos de tu organización»): Encaje estratégico, Capacidad de ejecución, Posición frente a la competencia, Rentabilidad esperada y Riesgo (5 = riesgo bajo). Cada puntuación lleva su motivo y se guarda por separado. La matriz da un total ponderado sobre 5, el «Umbral para el GO» y una recomendación («Recomienda GO» / «Recomienda NO-GO»); si solo hay algunos criterios puntuados la marca como provisional. No decide: si tu decisión contradice la recomendación, solo lo deja a la vista con un aviso. Los pesos los fija un propietario o administrador en Equipo › Organización («Pesos de la matriz go/no-go»).

### Preparar la oferta: kit y tareas

1. En **Kit de presentación** ves los documentos que exige el pliego agrupados por Sobre A, Sobre B, Sobre C y Otros documentos, con «N de M documentos listos».
2. Marca la casilla de cada documento cuando esté listo.
3. Elige un responsable en el desplegable de cada documento: eso **crea una tarea** «Kit: …» a su nombre (o reasigna la existente). El estado y vencimiento de la tarea aparecen bajo el documento.
4. Si el kit está vacío, dice por qué y, si no hay ficha del pliego, ofrece «Extraer ficha» (o «Reintentar» si la última falló). Nunca propone una lista genérica.

El reparto de tareas con responsable se hace aquí, desde el kit (y con la plantilla de tu organización al entrar en «Preparando oferta»). Las tareas sueltas se crean, se fechan y se cierran en la Agenda, desde el inspector de la oportunidad; allí no se elige responsable. Ver [Agenda y Watchlist](06-agenda-y-watchlist.md).

### Fijar el precio

En la pestaña **Precio**:

1. **Competencia esperada**: cuántos se presentarán, quién tiene hoy el contrato, contra quién se compite y cómo se puja en ese segmento.
2. **Escenarios de precio**: tres escenarios (Defensivo, Central, Competitivo) a partir de las bajas observadas en adjudicaciones comparables, con la calidad de la muestra. Puedes «Acotar a la competencia esperada»; si no hay bastantes comparables con esa competencia, lo dice y no la usa. «Usar como oferta prevista» fija ese importe en la oportunidad.
3. **Tu baja frente al mercado**: tu baja media por CPV y por órgano frente a la del mercado, a partir de tus ofertas previstas anteriores.
4. **Simulador de puntuación del precio**: la fórmula de precio del pliego, cuántos puntos reparte el precio y una tabla de puntos de precio para varias bajas de referencia, con «Temeraria» donde aplica. Escribe «Tu baja (%)» y, si quieres, «Baja del rival (%)», y pulsa «Simular»: dice los puntos que obtienes, si cae en temeridad y cuántos puntos sacas (o pierdes) frente al rival. La baja del rival se puede rellenar con un clic desde referencias publicadas («Usar como rival el p90 de la baja esperada», «… la baja del incumbente», «… la baja típica del ganador»). Sin fórmula de precio en el pliego, o sin saber cuántos puntos reparte, no calcula y dice por qué.

### Guardar la propuesta del equipo (adjuntos)

1. Abre la pestaña **Adjuntos** («Adjuntos del equipo»: solo los ve tu organización).
2. Pulsa «Subir adjunto» y elige el fichero. Antes de elegir, la pantalla indica el tamaño máximo y los tipos admitidos.
3. Para descargar, pulsa «Descargar»: se genera un enlace temporal que caduca. Para quitar uno, pulsa la papelera y confirma «¿Retirar este adjunto?».

Cada adjunto muestra su tamaño, quién lo subió y cuándo. Subir otra vez el mismo fichero a la misma oportunidad no lo duplica. Si la instalación no tiene almacén de documentos, la pestaña avisa de que «no se pueden subir adjuntos ni descargar los que hubiera». Permitir que el Investigador o el guion de la oferta citen un adjunto se explica en [Investigador](10-investigador.md).

### Registrar el resultado y cerrar

1. Desde «Presentada», pulsa «Registrar resultado» en la ficha, o arrastra la tarjeta a «Cerradas» (o «Cerrar…» en su menú).
2. Elige **Ganada**, **Perdida** o **Retirada**. No hay opción preseleccionada.
3. Ganada pide el «Importe adjudicado (€)»; Perdida y Retirada piden un motivo de la lista: Precio, Valoración técnica, Solvencia, Plazo, Desierto o anulado, No presentada u Otro.
4. Pulsa «Confirmar cierre». Desde cualquier fase anterior a «Presentada», cerrar solo puede ser retirar: el menú y la ficha ofrecen «Retirar…», y el diálogo «Retirar la oportunidad» pide el motivo y se confirma con «Retirar».

Si la fuente ya publicó la adjudicación, el bloque «Este expediente ya se adjudicó» lo facilita cuando la oportunidad está en «Presentada»: si tu organización declaró sus NIF, propone «La ganamos» o «La perdimos», y si el acta trae puntuaciones propone también el motivo; tú lo confirmas («Confirmar como ganada» / «Confirmar como perdida») o lo cambias. Sin NIF declarado ofrece «Cerrar como ganada» y «Cerrar como perdida» sin proponer nada. Al ganar desde ahí se toma el importe adjudicado publicado. Si la oportunidad no llegó a «Presentada», el bloque solo ofrece «Marcar como retirada». Un cierre no se reabre.

### Preparar la renovación de un contrato

1. En **Cartera**, busca el contrato (los que vencen pronto aparecen en ámbar).
2. Pulsa «Preparar renovación», escribe el «Expediente de la relicitación» (debe ser distinto del vigente) y pulsa «Crear oportunidad».
3. Se crea una oportunidad en «Identificada» enlazada al contrato. Repetirlo no crea otra; desde entonces la fila muestra «Ver oportunidad de renovación».

Si la fuente no publicó la fecha de fin, se pone a mano desde la Agenda («Poner fecha de fin»); queda marcada como **manual**.

### Filtrar el tablero y exportar

1. Usa búsqueda, etiqueta, responsable y plazo. Filtran en el servidor sobre todas las oportunidades, y una banda dice cuántas casan («la tira de arriba es de toda la organización»).
2. El filtro de plazo solo cuenta oportunidades abiertas y sin presentar.
3. «Exportar a CRM» descarga un CSV con una fila por oportunidad (la cuenta es el órgano y la fase se traduce a las etapas habituales de un CRM), listo para importar. Exporta todo el tablero de la organización: no aplica los filtros.

## Quién puede usarlo

- **Solo lectura**: ve el tablero, las fichas, la Cartera y el Rendimiento, y descarga adjuntos, pero no mueve, decide, puntúa la matriz, comenta, sube ni retira.
- **Miembro, Administrador y Propietario**: trabajan las oportunidades.
- **Propietario y Administrador**: además ajustan en Equipo › Organización los pesos de la matriz y los porcentajes por etapa.
- Un comentario lo borra su autor o un propietario o administrador.

## Límites y avisos

- **Nada aquí es probabilidad de ganar.** El valor ponderado usa porcentajes por fase que fija tu organización; la matriz y el checklist proponen, la decisión es vuestra.
- El tablero carga hasta **200 oportunidades**; si hay más, avisa de que se ven las de actividad más reciente y pide acotar con los filtros.
- La oportunidad sin importe de licitación publicado no entra en el valor del pipeline: se cuenta aparte en «Sin importe publicado».
- El checklist, el kit y el simulador dependen de la ficha extraída del pliego; sin ella lo dicen en vez de inventar requisitos o documentos. «Desconocido» es una pregunta abierta, no un «no».
- La relicitación esperada y la adjudicación prevista son estimaciones y así se rotulan.
- La Cartera muestra el detalle lateral y la cronología solo en pantallas anchas; las acciones de cada fila están en todos los anchos.
- Los escenarios de precio piden adjudicaciones comparables suficientes; si no las hay, dicen «Sin comparables suficientes».

## Relacionado

- [Radar y Mi perfil](03-radar-y-perfil.md): de dónde salen las oportunidades y qué es la banda.
- [Detalle y ficha](04-detalle-y-ficha.md): la ficha completa del expediente, con requisitos y competencia antes de abrir la oportunidad.
- [Agenda y Watchlist](06-agenda-y-watchlist.md): tareas, próximas acciones y fecha de fin de los contratos.
- [Competencia](09-competencia.md): rivales y bajas por segmento.
- [Investigador](10-investigador.md): preguntas sobre pliegos y adjuntos citables.
- [Equipo y Dirección](12-equipo-y-direccion.md): capacidad de la organización, pesos de la matriz, porcentajes por etapa y plantilla de tareas.
- [Glosario](15-glosario.md): GO/NO-GO, baja, temeridad, lote.
