# Mercado: cuánto se licita, dónde y quién compra

> Mercado responde a preguntas sobre el conjunto de las licitaciones TI, no sobre un expediente concreto: cuánto se publica y cuándo, en qué CPV, dónde, qué tecnologías, qué órganos compran y qué contratos ajenos vencen pronto.

## Para qué sirve y cuándo usarlo

Mercado (`/mercado`, en el bloque de análisis del rail, junto a Competencia e Investigador) es el espacio de análisis. Lo usan el responsable de ofertas y preventa para dimensionar un segmento antes de decidir dónde invertir esfuerzo, el responsable de cuenta para conocer a un órgano antes de trabajarlo y dirección para leer el tamaño del mercado. No es trabajo diario de triaje (eso es el [Radar](03-radar-y-perfil.md)) ni el seguimiento de tus oportunidades (eso es [Oportunidades](05-oportunidades.md)).

Momentos típicos:

- **Antes de una campaña o un plan comercial:** Tiempo, CPV, Geografía y Tecnologías para ver volumen, estacionalidad y reparto.
- **Antes de trabajar un órgano:** Órganos, para ver qué publica, cuánto adjudica y a quién.
- **Para anticiparte a una relicitación:** Renovaciones, para ver qué contratos de otros vencen y con qué riesgo de cambiar de manos.
- **Para planificar la semana:** Calendario, para ver qué plazos de presentación cierran y cuándo.

Todas las cifras salen de las licitaciones TI que TenderFlow recoge de las fuentes oficiales (PLACSP, TED y las fuentes autonómicas activas). Un contrato que llega por varias fuentes cuenta una vez. Es un radar tecnológico, no un censo de toda la contratación pública.

## Qué ves en pantalla

Bajo el título del espacio hay un conmutador de **vistas**. Cada una es un corte distinto del mismo conjunto de datos y vive en la dirección como `?vista=…`. Si entras en `/mercado` sin vista, se abre **Tiempo**.

| Vista | `?vista=` | Qué responde | Filtros del ámbito que aplica |
| --- | --- | --- | --- |
| Tiempo | `tiempo` | Cuánto se publica y por cuánto importe, mes a mes | Todos |
| CPV | `cpv` | Cómo evoluciona el importe de cada código CPV | Periodo, CCAA y Tecnología |
| Calendario | `calendario` | Qué plazos de presentación cierran y cuándo (o cuánto se publica cada día) | Todos |
| Geografía | `geografia` | Reparto por comunidad autónoma y provincia | Periodo y Tecnología |
| Tecnologías | `tecnologias` | Qué tecnologías se licitan, cómo evolucionan y dónde | Periodo y CCAA |
| Órganos | `organos` | Quién compra y qué perfil tiene cada órgano | Todos |
| Clusters (Exp) | `clusters` | Licitaciones agrupadas por el parecido de sus títulos | Periodo y CCAA |
| Proyectos y módulos (Exp) | `proyectos` | Qué se licita por familia tecnológica, con los módulos SAP dentro de ERP | Periodo y Tecnología |
| Renovaciones | `renovaciones` | Qué contratos adjudicados vencen pronto y quién los defiende | Solo Tecnología |

**La barra de ámbito manda.** Cambiar de vista no cambia de página: el ámbito se mantiene. Cada vista aplica solo los filtros de la tabla; si tienes puesto uno que la vista no usa, la barra lo avisa («N filtros activos no aplican en esta pantalla») y el recuento se calcula solo con los que sí aplica. Ver [Primeros pasos](01-primeros-pasos.md).

**Vistas experimentales.** Clusters y Proyectos y módulos llevan la marca «Exp» en su pestaña y, dentro, el aviso «Vista experimental» seguido de qué se valida y «En validación: puede cambiar o desaparecer». La administración de la plataforma puede apagarlas (en Ops › Administración); entonces la pestaña muestra «apagada» y la vista dice «Vista desactivada».

En el Resumen, el atajo a Tiempo se llama «Tendencias». En ⌘K cada vista aparece con su nombre de pestaña, y también se encuentra por el de su ruta antigua (por ejemplo, «tendencias»).

### Tiempo

- **Tira de KPIs:** «Licitaciones» e «Importe total» (suma de la serie del ámbito), «Variación interanual (licitaciones)» y «Variación interanual (importe)» (últimos 365 días frente a los 365 anteriores; con «—» y «Hace falta el año anterior completo» si no hay un año previo completo) y «Mes con más importe», con su importe y número de licitaciones.
- **Licitaciones por mes:** barras; pulsar una abre en Detalle las licitaciones publicadas ese mes.
- **Importe acumulado**, **Variación mensual del número de licitaciones** y **Licitaciones por tramo de importe** (pasa a escala logarítmica cuando los tramos son muy desiguales, y lo indica).
- **Licitaciones por mes y estado:** matriz de licitaciones publicadas cada mes según su estado actual. Pulsar un mes o una celda abre esas licitaciones en Detalle.
- **Previsión a 6 meses**, con el conmutador «Licitaciones» / «Importe». Va rotulada como **«Estimación»**. La banda sombreada es aproximada (± un número de sigmas de toda la serie histórica, que se indica), no se ensancha con el horizonte y **no es un intervalo de confianza**. Se nombra el modelo: «Holt-Winters (suavizado exponencial)» o «regresión lineal (de respaldo)». Si la serie es demasiado corta: «Sin previsión».

### CPV

- **CPV en el gráfico:** casillas para elegir qué códigos comparar. Al entrar se marcan los tres primeros; cada CPV conserva su color.
- **Importe por periodo:** una línea por CPV marcado. El botón «Previsión» muestra u oculta el panel siguiente.
- **Previsión de licitaciones a 6 meses:** el desplegable «Prever» deja elegir uno de los CPV marcados o «Mercado entero». Una etiqueta dice sobre qué serie se calcula («CPV …» o «Todo el mercado») y el texto lo repite: es una estimación sobre la serie mensual de ese CPV, o del mercado entero.
- **Los 15 CPV con más importe** (gráfico) y **CPV con más importe** (tabla con «#», «CPV», «Licitaciones», «Importe total»). Pulsar una fila de la tabla marca o desmarca ese CPV en el gráfico.

### Calendario

Arriba, el conmutador **«Vencimientos» / «Publicaciones»** y el selector de año (flechas «Año anterior» / «Año siguiente»).

- **Vencimientos** (por defecto): licitaciones cuyo plazo de presentación termina cada día. KPIs «Vencen hoy», «Vencen en 7 días» (hoy y los seis siguientes), «Vencen este mes» (de hoy a fin de mes) y «Día con más cierres» del año elegido; cada uno abre esas licitaciones en Detalle. Debajo, «Próximos 7 días» con el recuento de cada día. La rejilla «Cierres de plazo» resalta hoy y los próximos 7 días; pulsar un día con cierres abre esas licitaciones. Se navega desde cinco años atrás hasta el año que viene.
- **Publicaciones:** licitaciones publicadas cada día. Solo se navega por los años con datos y las celdas no son enlaces.
- En los dos modos: «Cierres por mes» o «Publicaciones por mes» y «Distribución por día de la semana» (media de los días con dato) del año elegido. La leyenda de la rejilla va de «Menos» a «Más», en tramos de 0 a 51 o más licitaciones por día.

### Geografía

- **KPIs:** «CCAA más activa», «Concentración en las 3 primeras» (porcentaje del total de licitaciones), «CCAA con licitaciones» y «Mayor importe medio» (la CCAA con más importe por licitación).
- **Mapa** por comunidad autónoma, con el conmutador «Licitaciones» / «Importe».
- **CCAA por número de licitaciones** y **Reparto del importe por CCAA** (con más de diez comunidades, las nueve primeras y «Otros»). Los dos dicen «Pulsa una para filtrar».
- **Todas las CCAA:** «CCAA», «Licitaciones», «Importe», «%», ordenables.
- **Provincias:** «Provincia», «Licitaciones», «Importe». Pulsar una abre Detalle filtrado por esa provincia y el resto del ámbito.
- Botón **«Exportar geografía»** (CSV o Excel).

### Tecnologías

- **KPIs:** «Tecnologías detectadas» (con cuántas licitaciones quedan sin clasificar), «Tecnología líder», «Importe medio por tecnología» y «Tasa de adjudicación» (media por tecnología).
- **Licitaciones con tecnología identificada:** porcentaje del ámbito que el clasificador ha asignado a alguna tecnología, con «N sin clasificar de M licitaciones». Por debajo del 70 % se pone en ámbar y avisa: «las cifras de esta vista se quedan cortas».
- **Evolución mensual por tecnología** («Licitaciones» / «Importe»), **Licitaciones por tecnología** e **Importe por tecnología** (las 15 primeras; el color de cada barra indica la otra medida), **Reparto de licitaciones por tecnología**, **Tecnologías por comunidad autónoma** (las 10 CCAA con más licitaciones) y **Licitaciones por tecnología y órgano**.
- **Detalle por tecnología:** eliges una en «Elige una tecnología» y ves «Licitaciones», «Importe total», «Importe medio» y sus licitaciones («Título», «Órgano», «Importe», «Estado», «CCAA», «Publicación»).
- **Todas las tecnologías:** tabla con buscador («Licitaciones», «Importe», «Adjudicadas», «% del total»).
- **Las 20 licitaciones mejor puntuadas:** expedientes vivos (estado no terminal y plazo por vencer) con su score y su banda según tu perfil, como en el [Radar](03-radar-y-perfil.md) (encaje, no probabilidad de ganar). El título abre la ficha.
- Botón **«Exportar tecnologías»**.

### Órganos

- **Titular:** «10 órganos concentran el X % de las N licitaciones del ámbito», con el número de órganos y el importe licitado. A la derecha, «Medir por» («Licitaciones» / «Importe»), el buscador «Buscar órgano o CCAA…» y **«Exportar órganos»** (si hay búsqueda, el fichero también se acota a ella).
- **Mapa de compradores:** cada punto es uno de los 50 órganos más activos del ámbito (con búsqueda, los que encajan con ella), por licitaciones e importe, en escala logarítmica; el tamaño es su importe medio por licitación. Las líneas discontinuas son las medianas. Los órganos sin importe conocido no se pueden dibujar y se dice cuántos quedan fuera. Con búsqueda activa aparece la marca «Filtrado».
- **Concentración:** rejilla de 100 casillas (cada una, el 1 %) con lo que concentran los 10 primeros órganos, más «Importe total» e «Importe medio» por licitación. Medida por licitaciones, la cifra es sobre todo el ámbito; **medida por importe es parcial**: se calcula entre los órganos más activos de la lista recibida, y el texto lo dice.
- **Los 12 primeros, por las dos medidas:** ranking en mariposa, licitaciones a un lado e importe al otro, ordenado según «Medir por».
- **Perfil del órgano:** al entrar se abre el del primero del ranking; pulsar un punto o una fila lo cambia a ese órgano. Muestra la posición en el ranking por la medida activa, «Licitaciones», «Importe total», «Adjudicado» (porcentaje de sus licitaciones), «Días hasta adjudicar» (mediana de publicación a adjudicación), el enlace «Ver sus N licitaciones en Detalle», **«Quién le gana los contratos»** (reparto del importe adjudicado entre sus primeros adjudicatarios: cinco con nombre y «Otros»), **«Cuándo publica»** (licitaciones por mes del año) y **«Mejor puntuadas»** (las tres primeras por score, con enlace al anuncio oficial). El perfil usa el mismo ámbito que el mapa.

### Renovaciones

Contratos adjudicados, **de cualquier adjudicatario**, que vencen dentro de la ventana elegida (desplegable: «3 meses», «6 meses» —por defecto—, «12 meses», «24 meses»).

- **KPIs**, calculados sobre toda la ventana y no solo sobre la tabla: «Contratos venciendo», «Importe en juego» (suma de lo adjudicado que vence), «Importe en alto riesgo» (riesgo de cambio ≥ 60 %) y «Oportunidades calientes» (alto riesgo y ≤ 30 días).
- **Cartera en juego por empresa:** las 10 empresas con más importe que vence en la ventana.
- **Contratos que vencen:** **los 200 más accionables** de la ventana, ordenados por riesgo × importe × urgencia. No son todos los que vencen, y la pantalla lo dice. Columnas:

| Columna | Qué significa |
| --- | --- |
| Vence | Fecha de fin y días que faltan (rojo hasta 30, gris hasta 90). «estimada» si la fecha se calculó con la duración del contrato porque la fuente no la publicó; «sin fecha» si no hay con qué calcularla. Si hay prórroga: «+N meses de prórroga → fecha». |
| Contrato | Título, con «Acuerdo marco» o «SDA» si lo que vence es un marco entero (cada fila es uno de sus admitidos), y enlace al anuncio original. |
| Adjudicatario | Empresa que lo tiene, con la marca «UTE» si lo es. |
| Órgano | Órgano de contratación. |
| Importe | Importe adjudicado. |
| Riesgo de cambio | **Estimación del modelo de retención** (se indica la versión): probabilidad de que el contrato cambie de adjudicatario, no un dato publicado. Rojo desde 60 %, gris desde 35 %. |
| Oportunidad | Riesgo × importe × urgencia, sobre 100 respecto al primero de la lista. Es relativo: solo sirve para comparar filas entre sí. |
| Acción | «Anticipar», o el rótulo «En tu cartera» (lo tiene adjudicado tu organización) o «Anticipada» (tu organización ya tiene una oportunidad sobre ese expediente). |

## Cómo se hace

### Cambiar de vista sin perder el ámbito

1. En `/mercado`, pulsa la pestaña de la vista (o búscala en ⌘K por su nombre).
2. El ámbito de la barra se conserva. Mira si la barra avisa de filtros que esta vista no aplica.
3. Para compartir lo que ves, copia el enlace: lleva la vista y el ámbito.

### Ver las licitaciones que hay detrás de una cifra

1. En Tiempo, pulsa una barra de «Licitaciones por mes» o una celda de «Licitaciones por mes y estado».
2. En Calendario (modo «Vencimientos»), pulsa un KPI, un día de «Próximos 7 días» o un día de la rejilla.
3. En Geografía, pulsa una provincia; en el perfil de un órgano, «Ver sus N licitaciones en Detalle».
4. Se abre [Detalle](04-detalle-y-ficha.md) con esas licitaciones y el resto del ámbito ya aplicado.

### Comparar CPV y prever uno

1. En CPV, marca en «CPV en el gráfico» los códigos que quieras (o pulsa sus filas en la tabla).
2. Pulsa «Previsión».
3. En «Prever», elige uno de los CPV marcados o «Mercado entero». Lee la etiqueta: la previsión es de esa serie y es una estimación.

### Filtrar por comunidad desde Geografía

1. Pulsa una CCAA en el mapa, en los gráficos o en «Todas las CCAA».
2. Se añade al ámbito global (pulsarla otra vez la quita) y queda resaltada en la tabla.
3. Geografía no se filtra por CCAA (la barra lo indica), pero el resto de vistas que sí la aplican y Detalle quedan acotadas a ella.

### Estudiar un órgano y seguirlo como cuenta

1. En Órganos, busca el órgano en «Buscar órgano o CCAA…» o localízalo en el mapa o el ranking. También llegas desde la ficha de una licitación, pulsando su órgano.
2. Púlsalo para abrir su perfil (si llegas desde la ficha, la búsqueda ya viene escrita con su nombre y el perfil abierto es el del primero que encaja con ella).
3. Para trabajarlo como cliente, pulsa el icono de seguir junto al nombre («Seguir el órgano …»): crea (o completa) la cuenta en [Cuentas](08-cuentas.md). El mismo icono sirve para dejar de seguirlo.
4. Cierra el perfil con la X.

### Anticipar una renovación

1. En Renovaciones, elige la ventana y, si quieres, filtra la tabla en «Empresa, órgano o título…» (filtra solo los 200 contratos servidos).
2. Pulsa una fila para abrir la ficha de la licitación en el panel lateral.
3. Pulsa «Anticipar»: se abre una oportunidad sobre ese contrato («Renovación anticipada como oportunidad») y te lleva a ella.
4. Si el contrato ya es tuyo («En tu cartera»), su renovación se prepara en Oportunidades › Cartera, no aquí.

### Exportar

1. En Geografía, Tecnologías u Órganos, pulsa «Exportar geografía», «Exportar tecnologías» o «Exportar órganos» y elige «Exportar CSV» o «Exportar Excel». Se exporta la tabla de esa vista con el ámbito.
2. En Proyectos y módulos, «Exportar licitaciones» exporta las licitaciones del ámbito.
3. Para el resto, usa «Exportar ámbito» de la barra.

### Usar las vistas experimentales

1. **Clusters:** ajusta «Número de clusters» (de 3 a 20; 8 al entrar) o activa «Elegir el número automáticamente», y pulsa «Recalcular». «Calidad del agrupamiento» dice si los grupos están bien separados («Grupos bien separados», «Separación moderada», «Separación débil: prueba otro número»). En «Resumen de clusters» elige uno para ver sus licitaciones.
2. **Proyectos y módulos:** tres secciones, «Por familia tecnológica», «ERP por dentro: módulos SAP» y «Por tipo de proyecto y CPV». Los fabricantes que venden en varias familias no se reparten entre ellas y la vista los nombra.

## Quién puede usarlo

- Cualquier usuario con sesión puede abrir todas las vistas y exportar.
- **Seguir un órgano** desde su perfil exige poder escribir en la organización. Con el rol Solo lectura no aparece el botón; si el órgano ya es cuenta, ves «Cuenta: …» con enlace a ella.
- **«Anticipar»** abre una oportunidad, así que también exige poder escribir: con Solo lectura la API lo rechaza y verás el aviso «No se pudo anticipar la renovación».
- El botón «Revisar sin clasificar» de Tecnologías solo lo ven los administradores de la plataforma (lleva a Ops › Etiquetado).
- Encender o apagar Clusters y Proyectos y módulos es cosa de la administración de la plataforma, en Ops › Administración ([Ops y Admin](13-ops-y-admin.md)).

## Límites y avisos

- **Mercado no da probabilidad de ganar.** Los scores de Tecnologías y del perfil de órgano miden encaje con tu perfil. El riesgo de cambio de Renovaciones es la estimación de un modelo sobre si el contrato cambiará de adjudicatario, no sobre si lo ganarás tú.
- **Lo estimado va rotulado:** las previsiones («Estimación», con su modelo), la banda de previsión (no es un intervalo de confianza), las fechas de fin calculadas («estimada») y el riesgo de cambio. Solo una pequeña parte de los contratos publica su fecha de fin; la mayoría se calcula con la duración.
- **Sin datos suficientes:** las variaciones interanuales salen «—» sin un año previo completo; la previsión sale «Sin previsión» si la serie es corta; un KPI sin base sale «—» y no un 0.
- **Lo parcial se dice:** la tabla de Renovaciones son los 200 primeros, no todos; la concentración por importe en Órganos es parcial; el mapa de compradores y el ranking trabajan con los 50 órganos más activos y el mapa omite los que no tienen importe conocido.
- **Tecnologías depende del clasificador.** Si el porcentaje con tecnología identificada es bajo, las cifras se quedan cortas, y la tarjeta de cobertura lo avisa.
- **Proyectos y módulos y Clusters están en validación** y pueden cambiar o desaparecer.
- **Renovaciones solo lista contratos adjudicados:** un marco sin admitidos publicados (casi todos los sistemas dinámicos) no aparece.
- Las rutas antiguas (`/tendencias`, `/tendencias-cpv`, `/calendario`, `/geografia`, `/tecnologias`, `/organos`, `/clusters`, `/proyectos-modulos`, `/renovaciones`) siguen funcionando y llevan a la vista correspondiente.

## Relacionado

- [Primeros pasos](01-primeros-pasos.md): la barra de ámbito, las vistas y la ficha lateral.
- [Resumen](02-resumen.md): sus atajos a Tiempo, Tecnologías y Órganos.
- [Detalle y ficha](04-detalle-y-ficha.md): adonde llevan los enlaces de Mercado.
- [Oportunidades](05-oportunidades.md): lo que abre «Anticipar» y la Cartera de tus contratos.
- [Cuentas](08-cuentas.md): seguir un órgano como cliente.
- [Competencia](09-competencia.md): quién gana y con qué cuota.
- [Glosario](15-glosario.md): CPV, banda, score, acuerdo marco, SDA, UTE.
