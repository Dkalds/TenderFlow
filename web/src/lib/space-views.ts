/**
 * Vistas de cada espacio y las rutas heredadas que absorben.
 *
 * Vive separado de `lib/console-spaces.ts` porque `next.config.ts` necesita
 * esta tabla para generar los redirects, y `console-spaces` arrastra iconos de
 * `lucide-react` — un import de React en la configuración de Next.
 *
 * Regla del proyecto: consolidar no elimina nada. Una ruta absorbida se
 * convierte en `?vista=` del espacio y su URL antigua redirige, para que
 * ningún enlace guardado se rompa.
 */

export interface SpaceView {
  /** Valor de `?vista=` dentro del espacio. */
  key: string;
  label: string;
  /** Ruta heredada del repo que esta vista absorbe. */
  from?: string;
  /**
   * `experimental`: la vista existe y funciona, pero no está a la altura del
   * resto del producto — análisis en validación, o superficies que nadie ha
   * usado todavía en serio. Se marca en la UI en vez de esconderse: ocultarla
   * la convertiría en código muerto, y prometer paridad con las vistas core
   * sería lo que este proyecto ya hace demasiado.
   *
   * Ausente ≡ `core`.
   */
  visibility?: "core" | "experimental";
}

/** slug del espacio → sus vistas, en orden de aparición. */
export const SPACE_VIEWS: Record<string, SpaceView[]> = {
  mercado: [
    { key: "tiempo", label: "Tiempo", from: "tendencias" },
    { key: "cpv", label: "CPV", from: "tendencias-cpv" },
    { key: "calendario", label: "Calendario", from: "calendario" },
    { key: "geografia", label: "Geografía", from: "geografia" },
    { key: "tecnologias", label: "Tecnologías", from: "tecnologias" },
    { key: "organos", label: "Órganos", from: "organos" },
    { key: "clusters", label: "Clusters", from: "clusters", visibility: "experimental" },
    {
      key: "proyectos",
      label: "Proyectos y módulos",
      from: "proyectos-modulos",
      visibility: "experimental",
    },
    // Reestructura 2026-09-20 («un espacio, una pregunta»): las renovaciones
    // son una pregunta de mercado —qué contratos ajenos vencen y quién los
    // defiende—, no un compromiso personal, así que la pantalla de
    // `/renovaciones` (hasta entonces «Horizonte» de Mi Pipeline) vive aquí.
    // Absorbe la ruta heredada, de modo que `/renovaciones` redirige a
    // `/mercado?vista=renovaciones`; el `?vista=horizonte` viejo lo reenvía la
    // página de `/mi-pipeline`.
    { key: "renovaciones", label: "Renovaciones", from: "renovaciones" },
  ],
  competencia: [
    { key: "competidores", label: "Competidores", from: "competidores" },
    { key: "utes", label: "UTEs", from: "utes" },
  ],
  // Reestructura 2026-09-20: Oportunidades es el espacio de ejecución y reúne
  // las tres preguntas sobre las oportunidades propias. `tablero` es la
  // entrada (por fases, con arrastre); `cartera` (F4.3) es la continuación del
  // contrato ganado —fecha de fin, prórrogas y ventana de relicitación— y
  // `rendimiento` es el embudo de `GET /pursuits/metrics` (win rate, valor
  // ponderado, pérdidas por motivo). Las dos últimas venían de Mi Pipeline;
  // sus `?vista=` viejos (`cartera`, `embudo`) los reenvía aquella página.
  // Ninguna absorbe ruta heredada: siempre fueron vistas de un espacio.
  oportunidades: [
    { key: "tablero", label: "Tablero" },
    { key: "cartera", label: "Cartera" },
    { key: "rendimiento", label: "Rendimiento" },
  ],
  // Rediseño 2026-08: la agenda absorbe pipeline-alertas (inventario de
  // funciones en docs/archive/redesign/mi-pipeline-inventario.md). Reestructura
  // 2026-09-20: el espacio se llama «Agenda» y responde una sola pregunta
  // —qué se me muere si hoy no hago nada—, así que ésta es su única vista.
  // El `key`/slug `mi-pipeline` se conserva para no romper URLs ni
  // telemetría. Los `?vista=` heredados los resuelve la página del espacio:
  // `pipeline` es un alias de la agenda; `embudo`, `cartera`, `horizonte` y
  // `renovaciones` reenvían al espacio donde vive hoy cada vista.
  "mi-pipeline": [{ key: "agenda", label: "Agenda", from: "pipeline-alertas" }],
  // F1.5: `?vista=mercado` **enlaza** a `Mercado → Órganos`, no la incrusta:
  // el corte analítico sigue viviendo en Mercado, con sus filtros de ámbito,
  // porque quien analiza el mercado no está trabajando cuentas. Lo que une las
  // dos pantallas es la acción: el botón «Seguir» del panel de órgano de
  // Mercado crea una cuenta de este espacio (`useSeguimiento` enruta los
  // órganos a `/cuentas`). Por eso esta vista no lleva `from`: no absorbe
  // ninguna ruta.
  cuentas: [
    { key: "seguidas", label: "Cuentas seguidas" },
    { key: "mercado", label: "Todos los órganos" },
  ],
  // F4.2: Dirección nació para añadir al embudo los cortes que un owner
  // necesita (win rate por tecnología y órgano, ciclo, motivos de pérdida).
  // Tuvo una vista `embudo` que era sólo un `EmptyState` devolviendo a Mi
  // Pipeline; la reestructura 2026-09-20 la retiró —no tenía funcionalidad—
  // y el embudo vive en `Oportunidades → Rendimiento`.
  direccion: [
    { key: "resultado", label: "Resultado" },
    { key: "actividad", label: "Actividad del equipo" },
  ],
  // Empresas no absorbe ninguna ruta heredada: sus dos vistas siempre
  // convivieron dentro de `/empresas`. Están aquí para que la cola de revisión
  // sea direccionable —`/empresas?vista=revision` es lo que se pega en un
  // mensaje cuando hay matches que resolver— y para que el conmutador sea el
  // mismo gesto que en Mercado o en Ops, y no unas pestañas propias.
  empresas: [
    { key: "maestro", label: "Maestro" },
    { key: "revision", label: "Revisión" },
  ],
  // Ajustes (C7.5). Nace con contenido real y no como espacio vacío: por eso el
  // plan lo secuenció **después** de C2.1 (sesiones), C2.3 (claves) y C2.7
  // (preferencias) — sin ellos habría sido una pestaña con el tema y poco más.
  //
  // `cuenta` absorbe `/mi-cuenta` con la regla de siempre: consolidar no
  // elimina. La ruta antigua redirige y su cuerpo pasa a ser una vista que las
  // dos entradas montan, igual que hicieron las seis de Ops.
  ajustes: [
    { key: "sesiones", label: "Sesiones" },
    { key: "claves", label: "Claves de API" },
    { key: "notificaciones", label: "Notificaciones" },
    { key: "cuenta", label: "Datos y cuenta", from: "mi-cuenta" },
  ],
  // Reagrupación 2026-10: el orden es el del turno de guardia —¿responde?,
  // ¿corrió?, ¿llegó bien el dato?— y al final lo que no es vigilancia sino
  // trabajo (etiquetar) y gobierno (quién entra, qué está encendido).
  //
  // Los `key` no cambian aunque cambie la etiqueta: son la URL, el redirect de
  // la ruta heredada y la serie de `espacio_abierto`. `ejecuciones` es la única
  // vista nueva (los pasos del cierre y la cola de trabajo, que la API
  // registraba y ninguna pantalla leía) y por eso no absorbe ruta. `flags` y
  // `webhooks` dejaron de ser vistas: en producción eran una fila y ninguna.
  // Viven dentro de `administracion` y siguen entrando — `VISTAS_FUSIONADAS`.
  ops: [
    { key: "observabilidad", label: "Estado", from: "observabilidad" },
    { key: "ejecuciones", label: "Ejecuciones" },
    { key: "calidad", label: "Datos", from: "calidad-datos" },
    { key: "etiquetado", label: "Etiquetado", from: "active-learning" },
    { key: "administracion", label: "Administración", from: "administracion" },
  ],
};

/** Una vista que existió y hoy es una sección de otra del mismo espacio. */
export interface VistaFusionada {
  /** El `?vista=` que tuvo: sigue entrando, y es el destino de su redirect. */
  key: string;
  /** Ruta heredada que absorbía, si absorbía alguna. */
  from?: string;
  /** Vista del mismo espacio donde vive ahora. */
  en: string;
  /** `id` de su sección dentro de esa vista, para aterrizar en ella. */
  ancla?: string;
}

/**
 * slug del espacio → vistas que se fundieron en otra.
 *
 * Es la misma regla de siempre —consolidar no elimina nada— aplicada a una
 * vista en vez de a una ruta. El redirect de la ruta heredada conserva su
 * destino (`/feature-flags` → `/ops?vista=flags`) y es la **página del
 * espacio** la que resuelve ese `vista`: monta la vista `en` y se desplaza a
 * `ancla`. Se hace así, y no reapuntando el redirect a `?vista=administracion`,
 * por dos motivos: un marcador o un enlace pegado con el `?vista=` viejo no
 * pasan por ningún redirect, así que la página tiene que entenderlo igualmente;
 * y el destino nuevo no podría decir a qué sección ir.
 */
export const VISTAS_FUSIONADAS: Record<string, VistaFusionada[]> = {
  ops: [
    { key: "flags", from: "feature-flags", en: "administracion", ancla: "feature-flags" },
    { key: "webhooks", from: "webhooks", en: "administracion", ancla: "webhooks" },
  ],
};

/**
 * Espacios cuya ruta propia ya existe. Se migran por lotes: mientras un espacio
 * no esté construido, sus rutas heredadas siguen siendo las buenas y **no** se
 * redirige — mandar `/tendencias` a un `/mercado` inexistente cambiaría una
 * pantalla viva por un 404.
 */
export const BUILT_SPACE_ROUTES: readonly string[] = [
  "resumen",
  "radar",
  "detalle",
  "oportunidades",
  "mercado",
  "competencia",
  "investigador",
  "mi-pipeline",
  "mi-watchlist",
  "mi-perfil",
  "ajustes",
  "empresas",
  "cuentas",
  "direccion",
  "equipo",
  "ops",
];

export interface LegacyRedirect {
  source: string;
  destination: string;
}

/**
 * Redirects de ruta heredada → vista del espacio, sólo para los espacios ya
 * construidos. Next.js arrastra la query entrante, así que un enlace con
 * filtros (`/tendencias?ccaa=Madrid`) llega al espacio con su ámbito intacto.
 */
/**
 * Subrutas que cambiaron de sitio y conservan su parámetro.
 *
 * No son vistas de un espacio —no caben en `SPACE_VIEWS` ni en
 * `legacyRedirects()`—: son páginas con identidad propia que pasaron a colgar
 * de otro espacio. `next.config.ts` las emite junto a aquéllos, también como
 * 308, y Next arrastra la query entrante igual que en las vistas.
 *
 * - `/competidores/empresa/[empresaId]` → `/competencia/empresa/[empresaId]`
 *   (2026-09-24): la ficha de empresa pasa a vivir en el espacio que el rail
 *   marca; `/competidores` era un slug heredado que no era espacio de nadie.
 *   No choca con el redirect de `/competidores`, que es de path exacto.
 */
export const SUBRUTAS_MOVIDAS: readonly LegacyRedirect[] = [
  {
    source: "/competidores/empresa/:empresaId",
    destination: "/competencia/empresa/:empresaId",
  },
];

export function legacyRedirects(): LegacyRedirect[] {
  return Object.entries(SPACE_VIEWS)
    .filter(([slug]) => BUILT_SPACE_ROUTES.includes(slug))
    .flatMap(([slug, views]) =>
      // Las fusionadas van con las vivas: para un redirect son lo mismo, una
      // ruta heredada que lleva a un `?vista=` que la página sabe resolver.
      [...views, ...(VISTAS_FUSIONADAS[slug] ?? [])]
        .filter((view) => Boolean(view.from))
        .map((view) => ({
          source: `/${view.from}`,
          destination: `/${slug}?vista=${view.key}`,
        })),
    );
}
