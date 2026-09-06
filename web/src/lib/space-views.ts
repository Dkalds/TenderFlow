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
  ],
  competencia: [
    { key: "competidores", label: "Competidores", from: "competidores" },
    { key: "utes", label: "UTEs", from: "utes" },
  ],
  // Rediseño 2026-08: la agenda absorbe pipeline-alertas (inventario de
  // funciones en docs/redesign/mi-pipeline-inventario.md) y el horizonte es la
  // pantalla de renovaciones con el CTA de anticipar. Los `?vista=` heredados
  // (`pipeline`, `renovaciones`) los alias-ea la página del espacio.
  "mi-pipeline": [
    { key: "agenda", label: "Agenda", from: "pipeline-alertas" },
    { key: "embudo", label: "Embudo" },
    { key: "horizonte", label: "Horizonte", from: "renovaciones" },
    // F4.3: `won` deja de ser un estado terminal sin vida posterior. La
    // cartera es la continuación del contrato ganado — su fecha de fin, sus
    // prórrogas y la ventana en que se espera la relicitación.
    { key: "cartera", label: "Cartera" },
  ],
  // F1.5: Cuentas absorbe `Mercado → Órganos` como `?vista=mercado`.
  // Consolidar no elimina: el corte analítico sigue estando, y lo que se añade
  // encima es lo que faltaba —poder seguir un órgano y ver qué tiene el equipo
  // con él—. Órganos sigue además accesible desde Mercado, porque quien
  // analiza el mercado no está trabajando cuentas.
  cuentas: [
    { key: "seguidas", label: "Cuentas seguidas" },
    { key: "mercado", label: "Todos los órganos" },
  ],
  // F4.2: Dirección absorbe `Mi Pipeline → Embudo` como `?vista=embudo`.
  // Mismo criterio: el embudo no desaparece de Mi Pipeline, y aquí se le
  // añaden los cortes que un owner necesita y que allí no caben.
  direccion: [
    { key: "resultado", label: "Resultado" },
    { key: "embudo", label: "Embudo" },
    { key: "actividad", label: "Actividad del equipo" },
  ],
  ops: [
    { key: "observabilidad", label: "Observabilidad", from: "observabilidad" },
    { key: "calidad", label: "Calidad de datos", from: "calidad-datos" },
    { key: "administracion", label: "Administración", from: "administracion" },
    { key: "flags", label: "Feature flags", from: "feature-flags" },
    { key: "etiquetado", label: "Active learning", from: "active-learning" },
    { key: "webhooks", label: "Webhooks", from: "webhooks" },
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
  "mi-cuenta",
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
export function legacyRedirects(): LegacyRedirect[] {
  return Object.entries(SPACE_VIEWS)
    .filter(([slug]) => BUILT_SPACE_ROUTES.includes(slug))
    .flatMap(([slug, views]) =>
      views
        .filter((view): view is Required<SpaceView> => Boolean(view.from))
        .map((view) => ({
          source: `/${view.from}`,
          destination: `/${slug}?vista=${view.key}`,
        })),
    );
}
