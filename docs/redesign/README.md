# Rediseño de consola — estado y reglas

El rediseño convierte el dashboard en una **consola de trabajo**: dos bandas de
cromo en vez de seis, el ámbito como objeto editable, y el detalle en el mismo
plano que la lista. La especificación visual son los prototipos de Claude Design
(`Radar - Consola de decision.dc.html` y hermanos): ahí está cada valor exacto de
color, espaciado y timing.

## Regla dura

**Consolidar no elimina funcionalidad.** Una pantalla rediseñada conserva el
100% de las capacidades de la original; se puede reorganizar, agrupar en vistas
o cambiar el patrón de interacción, nunca quitar. Antes de rediseñar una
pantalla: leer su código, inventariar sus funciones y decir dónde vive cada una
después. Los tests de cada pantalla son la red que lo verifica — si un test
antiguo deja de compilar, la pregunta es *dónde ha ido esa capacidad*, no
*cómo lo borro del test*.

## Anatomía del marco

| Pieza | Archivo | Qué absorbió |
| --- | --- | --- |
| Rail de 56px | `components/layout/console-rail.tsx` | La sidebar de 248px con sus once secciones, más el menú de cuenta del TopNav (organización activa, densidad, tema, cerrar sesión) |
| Barra de ámbito de 52px | `components/layout/scope-bar.tsx` | La `GlobalFilterBar` entera (mismos seis controles, mismo contrato por página), el buscador ⌘K, exportar, notificaciones y el indicador de frescura |
| Marco | `components/layout/console-frame.tsx` | Decide entre superficie de consola y cromo heredado según `isConsoleRoute` |
| Mapa de espacios | `lib/console-spaces.ts` + `lib/space-views.ts` | Las 25 rutas → 13 espacios; gobierna rail, redirects y qué ruta usa qué cromo |
| Historial del ámbito | `lib/scope-history.ts` | Deshacer / rehacer sobre cualquier cambio de filtro, venga de donde venga |

`TopNav`, `Sidebar` y `GlobalFilterBar` siguen en el árbol con sus tests: son la
referencia de lo que había que conservar mientras quedan espacios por migrar.

## Migración por lotes

`BUILT_SPACE_ROUTES` (en `lib/space-views.ts`) es el interruptor. Un espacio
entra ahí **cuando su ruta existe de verdad**, y entonces pasan tres cosas a la
vez, sin tocar nada más:

1. Su ruta viste el cromo de consola en vez del heredado.
2. El rail deja de apuntar a la ruta antigua y apunta al espacio.
3. `next.config.ts` emite el redirect 308 de cada ruta absorbida hacia
   `?vista=…`.

Mientras un espacio no esté construido, el rail enlaza a la primera ruta que
absorberá y no hay redirect: mandar `/tendencias` a un `/mercado` inexistente
cambiaría una pantalla viva por un 404.

### Estado: los 13 espacios, cubriendo las 25 rutas

**Rediseñadas a fondo**, con su superficie reconstruida:

- **Resumen** (`/resumen`) — lo urgente en tarjetas grandes con su destino
  visible; el contexto en tira compacta con delta y aviso de anomalía.
- **Radar** (`/radar`) — consola de decisión: J/K para recorrer, S seguir,
  X descartar con deshacer, ⏎ abrir oportunidad, inspector siguiendo a la
  selección.
- **Detalle** (`/detalle`) — tabla de trabajo de trece columnas con el
  inspector de cinco pestañas (`components/detail-inspector.tsx`) en el mismo
  plano, en vez del Sheet modal de once bloques apilados.

**Consolidadas**, con el cromo de consola y su conmutador de vistas
(`components/layout/space-shell.tsx`). Cada vista monta la pantalla original
completa, así que no se ha tocado una sola de sus funciones:

| Espacio | Vistas | Rutas absorbidas |
| --- | --- | --- |
| `/mercado` | 8 | tendencias · tendencias-cpv · calendario · geografía · tecnologías · órganos · clusters · proyectos-modulos |
| `/competencia` | 2 | competidores · utes |
| `/mi-pipeline` | 2 | pipeline-alertas · renovaciones |
| `/ops` | 5 | observabilidad · calidad-datos · administración · feature-flags · active-learning |

**Con cabecera de espacio** y su pantalla intacta: `/oportunidades`,
`/investigador`, `/mi-watchlist`, `/mi-perfil`, `/empresas`, `/equipo`.

**Retiradas**: `/red-organo-empresa` y `/ecosistema-partners` (antes
consolidadas bajo `/relaciones`) se borraron por completo — pantallas,
componentes de grafo (`force-graph.tsx`) y los endpoints de backend que solo
existían para servirlas (`organ-concentration`, `organ-company-graph*`,
`organ-company-edge`, `partnership-graph`).

### Los movimientos estructurales, uno por pantalla

Consolidar no era el objetivo: era el envase. Esto es lo que cambia dentro.

| Pantalla | El movimiento |
| --- | --- |
| Resumen | Lo urgente en tarjetas grandes con su destino visible; el contexto en tira con delta y anomalía |
| Radar | Consola tabular: J/K · S · X con deshacer · ⏎, inspector siguiendo a la selección |
| Detalle | Los once bloques del Sheet modal en cinco pestañas, en el mismo plano que la tabla |
| Oportunidades | Carriles a alto de pantalla con scroll propio; en la ficha, **Decisión abre** (era el último de seis paneles) |
| Competencia | La tabla que gobierna los nueve gráficos va primero; los nueve pasan a cortes con pestañas; el dossier sale del modal |
| Investigador | `alpha` y `top_k` visibles; resultados y conversación conviven en vez de excluirse |
| Mercado · Órganos | El drill-down sale del Sheet y convive con el ranking |
| Empresas | La cola de revisión pasa de bloque condicional a vista con contador; importe resuelto en ámbar bajo el 95% |
| Equipo | Los cuatro roles pasan de etiqueta a matriz de permisos |
| Ops y Admin | Tira de salud común a las cinco vistas: fuentes, frescura, DLQ y etiquetado |

El patrón que se repite: **lo que era un modal encima pasa a vivir al lado**.
Un Sheet obliga a cerrar para volver a mirar, y comparar es justamente mirar
dos cosas seguidas.

### Vocabulario compartido

`components/console/panel.tsx` es la parte del sistema de gráficos que aterriza
en código: una forma de panel, un título, los tres estados con el alto del
contenido real —para que la página no salte al cargar—, la tira de estadísticas
en rejilla de 1px y los cortes con pestañas. Las reglas duras que hereda: color
de serie por índice y nunca a mano, «Otros» siempre en `chart-8`, nunca dos ejes
Y en un panel, y clic en una marca filtra el ámbito en vez de navegar.

La vista vive en `?vista=`, no en el path: cambiar de corte no navega, así que
**el ámbito y la selección sobreviven al cambio**. Las vistas se cargan bajo
demanda (`next/dynamic`) — ocho pantallas de gráficos en un bundle costarían el
arranque del espacio entero para ver un corte.

### El contrato de filtros lo hereda el espacio

Un espacio no declara a mano si consume el ámbito: lo deduce de las rutas que
absorbe (`absorbedPages` en `lib/navigation.ts`). Basta con que una vista lo use
para que el espacio lo use; si ninguna lo usa —el caso de Ops y Admin— la barra
de ámbito no aparece. Sin esto, Ops pintaba chips que no filtraban nada, que es
exactamente la clase de mentira que el resto del rediseño se dedica a quitar.

### Deuda declarada

Los ficheros de las rutas absorbidas siguen en `app/(dashboard)/<ruta>/page.tsx`
y son quienes montan cada vista; su ruta HTTP está redirigida, así que el
`page.tsx` funciona ya sólo como componente. Moverlos a `_views/` sigue
pendiente, y no es sólo mover ficheros:

- cada una lleva su `layout.tsx` con el `metadata.title` y su `loading.tsx`;
- `/competidores` cuelga la subruta `/competidores/empresa/[empresaId]`, que
  tiene que seguir viva (el redirect es de ruta exacta, no de prefijo).

Mezclar veinte movimientos de fichero con el cambio de arquitectura en el mismo
diff habría hecho ilegible el uno y arriesgado el otro.

### Qué está verificado y qué no

En verde: tests unitarios, lint, typecheck, build, invariantes de datos, y los
17 redirects comprobados contra el servidor real (308 con la query intacta).

**Sin verificar: el aspecto con datos reales.** No hay backend en el entorno de
desarrollo remoto, así que no hay QA visual. Los e2e de Playwright fallan 27 de
43 por `ERR_CERT_AUTHORITY_INVALID` al cargar scripts externos — comprobado que
fallan **igual en el commit base**, así que es del entorno y no del rediseño.

## Sistema de movimiento

Lo fija [`frontend-motion.md`](../frontend-motion.md) y no cambia aquí: entrada
260ms `cubic-bezier(.21,1.02,.73,1)`, salida 170ms (más rápida que la entrada),
hover/press 140ms, sólo `transform` y `opacity`, y `prefers-reduced-motion`
siempre. Dos decisiones deliberadas de la consola:

- La selección por teclado va a 110ms y el inspector **no** hace crossfade: con
  J/K mantenido, cualquier transición se percibe como lag.
- Las acciones de fila aparecen con `opacity` + `translateX`, y tienen columna
  propia: no se superponen a Importe ni a Plazo, así que cambiar de fila no
  mueve ninguna columna.

## Reglas aprendidas

- **Los estados se pueden alcanzar.** Toda pantalla que liste datos tiene
  cargando, vacío y error reales, no declarados de boquilla.
- **El inventario no puede mentir.** Un contador que no se puede calcular sin
  pedir un dato extra no se pinta.
- **Nada de analítica derivada en cliente** (ADR-014 y
  [`frontend-data-invariants.md`](../frontend-data-invariants.md)): el desglose
  de score, los adjudicatarios del órgano y los deltas vienen del backend.
