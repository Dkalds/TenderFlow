# Radar y Mi perfil: priorizar lo que encaja

> El Radar ordena las licitaciones abiertas por lo bien que encajan con tu perfil para que decidas cada mañana cuáles seguir, abrir o descartar; Mi perfil decide cómo se calcula ese orden.

## Para qué sirve y cuándo usarlo

El **Radar** (`/radar`, tecla `1`) es la bandeja de triaje diario. Lo usan sobre todo el responsable de ofertas y los comerciales a primera hora: repasan las señales, descartan lo que no les sirve, siguen lo que quieren vigilar y convierten en oportunidad lo que van a trabajar con el equipo. Está pensado para decidir sin cambiar de pantalla y también funciona en el móvil para el triaje rápido.

**Mi perfil** (`/mi-perfil`, en la barra lateral junto a Mi Watchlist y Ajustes) es donde dices qué te interesa y cuánto pesa cada criterio. Se visita poco: al empezar, cuando el Radar te pone arriba cosas que no son tuyas o cuando tu organización ya tiene bastantes decisiones para proponerte pesos. Los cambios se aplican en el Radar, en el detalle de cada licitación y en los rankings de análisis.

Una idea que conviene tener clara desde el principio: **el score mide encaje con tu perfil, no probabilidad de ganar**. El propio Radar lo dice: «No es una recomendación comercial: mide encaje con tu perfil, no probabilidad de ganar».

## Qué ves en pantalla

### Radar: las bandejas

Arriba, un conmutador «Bandejas» con el recuento de cada una («—» mientras no se sabe):

| Bandeja | Qué contiene |
| --- | --- |
| Bandeja | Las señales por revisar: ni descartadas ni en seguimiento. Es la vista por defecto. |
| Próximas | Compras que el órgano ya ha anunciado y que todavía no han salido a licitación (consultas preliminares y anuncios previos, solo abiertos). Sin score, sin plazo y sin acciones de triaje. |
| Siguiendo | Las licitaciones que sigues, aunque no estén entre las del ranking. |
| Descartadas | Las que descartaste, silenciaste o pospusiste y aún no han vuelto. |
| Todas | Las del ranking (hasta 24) sin separar por seguimiento: las que sigues que estén en él también salen. Las descartadas no. |

A la derecha: «Restaurar N descartadas» (solo si tienes alguna), un filtro por etiqueta (solo si tu organización usa etiquetas; filtra las señales ya cargadas) y «Orden» con tres opciones: **Score**, **Plazo** (lo que cierra antes, primero) e **Importe** (de mayor a menor). En Próximas el orden es fijo: «Orden: fecha prevista».

### Radar: la lista

La lista es **el top de hasta 24 licitaciones abiertas que mejor encajan con tu perfil**, no todas las abiertas; el pie lo recuerda («hasta 24 abiertas, las que mejor encajan con tu perfil»). Solo entran expedientes vivos (estado no terminal y plazo por vencer): lo resuelto, adjudicado o anulado no aparece.

En pantallas anchas es una tabla con estas columnas:

| Columna | Qué significa |
| --- | --- |
| Score | Puntuación de 0 a 100, coloreada por banda, con la banda escrita debajo. Sin puntuación, «—» y «Sin puntuar». Al pulsarla se abre «Cómo se compone esta puntuación». |
| Licitación | Título, y debajo expediente, CPV y comunidad. La etiqueta «Nueva» marca lo publicado desde la última vez que saliste del Radar en ese navegador. |
| Órgano | Órgano de contratación. |
| Tecnología | Tecnología detectada. En pantallas muy anchas no tiene columna propia y va en la línea bajo el título. |
| Importe | Importe publicado, abreviado. |
| Plazo | Días naturales hasta el cierre, con una mecha de color: rojo hasta 5 días, luego naranja (hasta 12), amarillo (hasta 25) y verde. |
| Acción | Aparece en la fila seleccionada: descartar, seguir, «Ver ficha» (solo en anchos intermedios) y «Abrir». |

En el móvil cada señal es una ficha con los mismos datos y los botones siempre visibles.

### Las bandas

| Banda | Score |
| --- | --- |
| Caliente | 75 o más |
| Atractiva | de 50 a 74 |
| Tibia | de 25 a 49 |
| Descarte | menos de 25 |

La banda solo resume el score; no es una predicción.

### De qué está hecho el score

El score suma lo que aporta cada una de las **seis dimensiones**, según los pesos de tu perfil (suman 100), y le resta las penalizaciones de riesgo. El resultado se limita a 0–100.

| Dimensión | Peso por defecto | Qué premia | De dónde sale |
| --- | --- | --- | --- |
| Importe | 20 | Contratos más grandes dentro del mercado | Posición del importe entre el percentil 10 y el 90 de las licitaciones abiertas hoy. |
| Plazo | 15 | Plazos con margen para preparar la oferta | Todo el peso entre 7 y 90 días; la mitad con menos de 7; el 70 % entre 91 y 180; el 30 % a más de 180. |
| Competencia | 20 | Segmentos con menos licitadores | Media de ofertas por adjudicación en la misma división CPV (4 dígitos), con adjudicaciones de los últimos 24 meses. |
| Margen esperado | 20 | Baja esperada menor | Predicción de baja del expediente o, si no la hay, la baja histórica de su división CPV (y, a falta de ella, la media general). |
| Afinidad | 15 | Parecido con lo que tú o tu equipo hacéis | Tus palabras clave y CPV de interés; si no tienes ninguno, la capacidad declarada de tu organización en Equipo › Organización. |
| Señal técnica | 10 | Evidencia clara de la tecnología | Texto de los pliegos y el clasificador: de la tecnología que filtres en la barra de ámbito o, sin filtro, de la más clara que tenga el expediente. |

Cuando falta el dato de una dimensión (sin importe, sin fecha, sin histórico, sin predicción, sin señal técnica), esa dimensión puntúa **la mitad de su peso**: ni premia ni castiga. La afinidad es distinta: si hay con qué compararla y el expediente no se parece en nada, aporta 0. Si ni tu perfil ni tu organización declaran a qué os dedicáis, la afinidad no cuenta y su peso se reparte entre las demás.

**Riesgo** no es una dimensión: resta puntos. Sin importe publicado, −5; sin título, −3; sin fecha límite, −2; importe fuera de tu rango de Mi perfil, −15; y, con la penalización activada (lo está por defecto), −8 cuando el órgano anula o deja desiertos al menos uno de cada cuatro expedientes (con un mínimo de diez resueltos en 24 meses). Estas causas aparecen como avisos: «Sin importe publicado», «Fuera de tu rango de importe», «Órgano que anula a menudo», etc.

### Radar: el inspector (ficha de la señal)

Al seleccionar una fila se abre a la derecha (en pantallas muy anchas, fijo; en medianas, como panel lateral con «Ver ficha»; en el móvil no hay inspector). Muestra:

- **Cabecera:** banda, expediente, score y el título, que enlaza a la ficha completa en Detalle. Debajo, los avisos de riesgo o, si no hay, el estado y los días que quedan.
- **Datos:** Órgano, Importe, Cierre, Tecnología, CPV, Comunidad, Procedimiento y Tramitación.
- **Desglose de score:** una barra por dimensión con los puntos que aporta, y una fila «Riesgo» con lo que resta.
- **Línea de tiempo:** publicación y cierre de ofertas.
- **Competencia esperada:** cuántos se presentarán, quién lo tiene hoy, contra quién y cómo se puja.
- **Acciones** (ver «Cómo se hace»).

### Avisos que pueden aparecer sobre la lista

- **«Score incompleto: …»**: alguna fuente del cálculo falló o no está disponible y lo dice en concreto, por ejemplo «sin histórico de competencia: esa dimensión puntúa neutra» o «no se pudo cargar tu perfil: el orden usa temporalmente los pesos globales». Mientras aparezca, el orden es menos fiable.
- **Precisión de la banda Caliente en tu organización**: cuántas de las oportunidades abiertas desde esa banda se ganaron, sobre las ya resueltas. Por debajo del mínimo dice «sin datos suficientes» y cuántas resueltas lleva de las necesarias; si ninguna abierta desde Caliente ha llegado aún a un cierre, lo dice así. «Ver todas las bandas» despliega el cuadro completo, con la ventana de fechas y cuántas oportunidades guardan su banda. Solo aparece cuando hay oportunidades con banda guardada.

### Mi perfil

La página tiene tres secciones y, a la derecha (debajo en pantallas estrechas), la vista previa:

- **Qué te interesa:** «Palabras clave de afinidad», «CPV de interés» y «Rango de importe ejecutable».
- **Cuánto pesa cada criterio:** «Pesos de la puntuación» (un control deslizante por dimensión, una barra con el reparto de los 100 puntos y el interruptor «Penalizar órganos que anulan a menudo») y «Pesos que sugieren tus decisiones».
- **Quién lo usa:** «Ámbito del perfil», con el interruptor «Compartir con la organización», qué tecnologías puntúa tu organización (se configura en Equipo › Organización) y un enlace para exportar o eliminar tus datos en Ajustes › Datos y cuenta.
- **Así quedaría tu Radar:** las primeras licitaciones abiertas de tu ámbito ordenadas con tu perfil y, si tienes cambios sin guardar, cuánto sube o baja cada una («sube 2 puestos», «entra, estaba la 14.ª») y cuáles dejan de estar entre las primeras.

## Cómo se hace

### Repasar la bandeja con el teclado

1. Entra en `/radar` (tecla `1`). Se selecciona la primera señal.
2. Recorre con `J` / `K` (o las flechas). El inspector cambia con la selección.
3. Pulsa `S` para seguir, `X` para descartar o `Intro` para abrir oportunidad. El pie de la pantalla recuerda los atajos.

### Ver por qué una licitación tiene ese score

1. Pulsa la cifra del score en la fila.
2. En «Cómo se compone esta puntuación» lees primero unas frases que explican el cálculo y después la barra de cada dimensión, con los puntos que aporta.
3. Debajo se indica contra qué se midió la afinidad: tu perfil personal, la capacidad declarada de tu organización o ninguna de las dos.

### Seguir una licitación

1. Pulsa la estrella de la fila, «Seguir» en el inspector, o `S`.
2. Sale el aviso «Añadida a seguimiento», con «Deshacer». La señal pasa a la bandeja Siguiendo.
3. Para dejar de seguirla, vuelve a pulsar (el botón dice «Siguiendo»).

### Descartar, silenciar o posponer

1. **Descartar:** la X de la fila, «Descartar» en el inspector, o `X`. Desaparece de la bandeja y no vuelve sola. El aviso «Señal descartada» ofrece «Deshacer» durante unos segundos. Descartar dos veces la misma no duplica nada.
2. **Silenciar 30 días** (solo en el inspector): la oculta y la devuelve a la bandeja cuando pasan los 30 días, sin avisarte. Sale el aviso «Silenciada 30 días», con «Deshacer».
3. **Posponer** (solo en el inspector): elige en «Recordar en» 3, 7, 14 o 30 días y pulsa «Posponer». Se oculta igual y, ese día, te deja un aviso en la campana. Sale el aviso «Te lo recordamos en N días», con «Deshacer».
4. Lo descartado, silenciado o pospuesto se queda en la bandeja Descartadas hasta que vuelve. El descarte se guarda en el servidor: recargar o cambiar de equipo no lo deshace.

### Recuperar lo descartado

1. Justo después de descartar, pulsa «Deshacer» en el aviso.
2. Más tarde, pulsa «Restaurar N descartadas». Un diálogo confirma el recuento; al pulsar «Restaurar N» («Restaurar» si es una) vuelven todas a la bandeja, incluidas las silenciadas y pospuestas, y aún tienes unos segundos para deshacerlo desde el aviso.

No hay un botón para restaurar una sola descartada pasado el aviso: la restauración posterior es en bloque.

### Convertir una señal en oportunidad

1. Pulsa «Abrir» en la fila, «Abrir oportunidad» en el inspector, o `Intro`.
2. Se crea la oportunidad para tu organización activa, con el score, la banda y el desglose de ese momento, y te lleva a ella (aviso «Oportunidad abierta para el equipo»). Abrir dos veces la misma licitación no crea dos oportunidades.
3. Lo que sigue (Go/No-Go, tareas, adjuntos) está en [Oportunidades](05-oportunidades.md).

### Otras acciones del inspector

- **Comparar**: añade el expediente a la bandeja de comparación de fichas del pliego, que sigue abierta al pasar a Mi Watchlist o a Detalle.
- **Enlace externo** (icono al lado de «Abrir oportunidad»): abre el anuncio en la fuente oficial en una pestaña nueva, si la señal trae URL.
- **El título** abre la ficha completa en Detalle.

### Acotar el Radar a una tecnología

1. En la barra de ámbito, elige una tecnología. El Radar se limita a las licitaciones de esa tecnología y la señal técnica mide esa tecnología; si eliges varias, usa la primera. Mientras haya una elegida, el resto del ámbito de tu organización no se aplica.
2. Sin tecnología elegida, el Radar aplica el ámbito que tu organización tenga configurado (tecnologías, CPV, comunidades, importe, procedimientos excluidos y tipos de órgano). Si no hay ninguno, mira todo el mercado abierto. Tus CPV y tu rango de Mi perfil no recortan la lista: puntúan dentro de ella.
3. Si ves «Bandeja al día» y no te lo esperas, quita la tecnología de la barra de ámbito. Para enterarte de lo nuevo sin volver al Radar, crea una regla en Mi Watchlist.

### Ajustar palabras clave y CPV

1. En «Palabras clave de afinidad», escribe una o varias separadas por comas (o punto y coma) y pulsa «Añadir» (o `Intro`); se guardan en minúsculas. Se busca la palabra completa en el título o la descripción, y tres palabras distintas encontradas ya dan la afinidad máxima. Si el servidor tiene activa la comparación por significado, también puntúan textos parecidos aunque no repitan la palabra. Para quitar una, pulsa su etiqueta.
2. En «CPV de interés», escribe un código de 4 a 8 dígitos o parte del nombre y elige entre las sugerencias. El mismo código da la afinidad máxima; si coincide en los 4 primeros dígitos, un 80 %.
3. Comprueba en «Así quedaría tu Radar» cómo cambia el orden y pulsa «Guardar perfil».

### Fijar tu rango de importe

1. En «Rango de importe ejecutable», rellena «Mínimo (€)», «Máximo (€)» o los dos. En blanco no hay límite.
2. El máximo no puede ser menor que el mínimo. Los contratos con importe fuera del rango **no desaparecen del Radar: restan 15 puntos**.
3. Pulsa «Guardar perfil».

### Cambiar los pesos

1. Mueve el control de una dimensión. Los pesos siempre suman 100: al subir uno, los demás se reparten la diferencia.
2. Pulsa «Fijar» en los que no quieras que cambien (el botón pasa a «Fijado»; vuelve a pulsarlo para soltarlo). Si fijas todos menos uno, aparece «Con los demás fijados no queda con qué compensar un cambio».
3. El interruptor «Penalizar órganos que anulan a menudo» activa o quita esa resta de 8 puntos; no cuenta en los 100.
4. «Restablecer» vuelve a los pesos por defecto y suelta lo fijado.
5. Pulsa «Guardar perfil». Si los pesos no suman 100, o la afinidad se lleva los 100, el botón queda bloqueado y la barra lo explica. «Descartar» deshace los cambios sin guardar.

### Aplicar los pesos que sugieren tus decisiones

1. En «Pesos que sugieren tus decisiones» se compara el desglose de lo que tu organización **ganó** frente a lo que **perdió**, cuando hay 20 cierres con desglose guardado. Mientras no los haya, compara lo que tu equipo **abrió** frente a lo que **descartó** desde el Radar o el resumen diario, con un mínimo de 10 de cada.
2. La tarjeta dice sobre qué base habla («Base: …») y contra qué pesos compara. Si no hay base, dice cuántas decisiones faltan.
3. Para aplicarla, pulsa «Aplicar la propuesta»: el botón pasa a decir «¿Aplicar estos pesos a tu perfil?»; púlsalo otra vez para confirmar o pulsa «Cancelar». Nunca se aplica sola, sustituye los pesos de tu perfil y queda registrado. Si tienes cambios sin guardar, el botón está bloqueado: primero guárdalos o descártalos.

### Compartir tu perfil con la organización o eliminarlo

1. Activa «Compartir con la organización» y guarda: los miembros sin perfil propio usarán tus pesos.
2. Si ves «Estás usando el perfil compartido de tu organización», lo configuró otra persona; al guardar creas tu propio perfil, privado salvo que lo compartas, y el de la organización no cambia.
3. «Eliminar perfil» (con «Sí, eliminar» para confirmar) borra el tuyo y la puntuación vuelve a los pesos globales. Solo aparece si tienes un perfil propio y no hay cambios sin guardar.

## Quién puede usarlo

- Cualquier usuario con sesión ve el Radar, sigue, descarta, silencia y pospone, y puede usar la vista previa de Mi perfil.
- **Abrir oportunidad** y **guardar tu perfil** en la organización activa requieren un rol con escritura: con el rol «Solo lectura» se rechazan.
- El Radar usa el perfil de la organización activa. Si cambias de organización, cambian el perfil y el ámbito.
- Las tecnologías que puntúa tu organización y su capacidad declarada se configuran en Equipo › Organización, no en Mi perfil.

## Límites y avisos

- **No es una probabilidad de ganar.** El score ordena por encaje con tu perfil a partir de datos públicos (anuncios oficiales, adjudicaciones de los últimos 24 meses, predicciones de baja). La única medida de acierto es la precisión por banda, calculada con las oportunidades de tu organización ya resueltas, y solo se muestra a partir del mínimo de casos.
- **Solo hasta 24 licitaciones.** El Radar no es un listado completo: para ver todo, usa Detalle.
- **Neutral no es bueno.** Un expediente sin datos en una dimensión recibe la mitad del peso. Si aparece «Score incompleto», una dimensión entera está en neutro para todas las filas.
- **Próximas no se puntúa** ni se descarta: no hay pliego ni plazo. La fecha que muestra es la de inicio previsto del contrato, solo cuando el órgano la publica («Sin fecha» si no); no se estima. Que esté vacía es lo habitual.
- **«Nueva»** depende del navegador: se calcula con la última vez que saliste del Radar en ese equipo.
- **En el móvil** no hay inspector: puedes ver el desglose, descartar, seguir y abrir, pero no silenciar, posponer ni comparar.
- **La vista previa no guarda nada.** Se recalcula sola poco después de cada cambio y solo funciona con pesos válidos.
- **Los pesos guardados afectan a todo**: Radar, detalle de cada licitación y rankings de análisis.

## Relacionado

- [Primeros pasos](01-primeros-pasos.md): sesión, barra de ámbito y navegación.
- [Resumen](02-resumen.md): el arranque del día, con enlace al Radar.
- [Detalle y ficha](04-detalle-y-ficha.md): el listado completo y la ficha de cada expediente.
- [Oportunidades](05-oportunidades.md): qué pasa después de «Abrir oportunidad» y el rendimiento del Radar por banda.
- [Agenda y Watchlist](06-agenda-y-watchlist.md): lo que sigues y las reglas de aviso.
- [Equipo y Dirección](12-equipo-y-direccion.md): tecnologías y capacidad declarada de la organización.
- [Glosario](15-glosario.md): score, bandas, CPV, baja.
