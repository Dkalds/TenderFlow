/**
 * Qué páginas se sirven sin sesión, cuáles rastrea un buscador y cuáles se
 * prerenderizan. **Una sola lista**, porque hasta ahora eran cuatro.
 *
 * La misma decisión —«esta página es pública»— estaba escrita por separado en
 * `proxy.ts` (dos listas: acceso sin sesión y CSP sin nonce), `app/robots.ts`
 * (allow-list) y `app/sitemap.ts` (estáticas del fichero 0). Nada obligaba a
 * las cuatro a coincidir, y no coincidieron: `/cobertura`, `/metodologia` y
 * `/seguridad` se publicaron completas y quedaron fuera de las cuatro, así que
 * el visitante anónimo —el público entero de esa superficie— recibía un 307 a
 * `/login`, Google no podía rastrearlas y el sitemap no las anunciaba. Estaban
 * escritas, desplegadas y muertas.
 *
 * Con esta lista, publicar una página es añadir una fila. El test
 * `src/__tests__/rutas-publicas.test.ts` enumera los `page.tsx` del grupo
 * `(publico)` desde el sistema de ficheros y falla si alguno no está aquí, de
 * modo que la próxima página no puede nacer huérfana en silencio.
 *
 * ## Lo que esta lista NO cubre
 *
 * Los recursos técnicos que también viajan sin sesión (`/_next`, `/_vercel`,
 * `robots.txt`, el sitemap, las imágenes de metadatos) siguen en `proxy.ts`: no
 * son páginas, nadie las enlaza y no tienen nada que hacer en un sitemap. Ahí su
 * comentario explica por qué cada una está exenta.
 */

/** Frecuencias de cambio que admite el sitemap de Next. */
type Frecuencia = "daily" | "weekly" | "monthly" | "yearly";

export interface PaginaPublica {
  /** Ruta exacta, o prefijo del que cuelgan rutas dinámicas. */
  ruta: string;
  /**
   * `prefijo` para lo que tiene descendencia (`/licitaciones/[ccaa]/[slug]/[ref]`).
   *
   * La portada es **exacta** por una razón que no es de estilo:
   * `"/cualquier/cosa".startsWith("/")` es cierto siempre, así que declararla
   * como prefijo no abriría la portada — abriría la aplicación entera y dejaría
   * el dashboard accesible sin sesión.
   */
  coincidencia: "exacta" | "prefijo";
  /**
   * Su HTML se genera en el build (estático + ISR) y por eso recibe una CSP sin
   * nonce.
   *
   * Un nonce se genera por request; el HTML de una página prerenderizada se
   * generó en el build, cuando ese valor no existía. Servir `'nonce-…'` +
   * `'strict-dynamic'` sobre HTML horneado significa que **ningún** script
   * inline de arranque de Next lleva el nonce que la cabecera exige: el
   * navegador los bloquea todos y la página queda en blanco. Lo documenta el
   * propio framework — «to use a nonce, your page must be dynamically
   * rendered» (`next/dist/docs/01-app/02-guides/content-security-policy.md`).
   *
   * Antes esto no se notaba porque `app/layout.tsx` leía `headers()` para
   * pasarle el nonce a next-themes, y una API dinámica en el layout raíz sacaba
   * a la aplicación **entera** del prerender: nada era estático, así que el
   * nonce siempre valía. El coste era que cada visita y cada rastreo de la
   * landing pagaba un render de servidor, y que los `revalidate` de la
   * superficie de datos no se aplicaban nunca.
   */
  prerenderizada: boolean;
  /**
   * Entra en el `Allow` de robots.txt. No implica indexable: `/login` se rastrea
   * a propósito **para** que Google pueda leer el `noindex` que declara — una
   * página bloqueada por robots nunca se lee, y por tanto nunca sale del índice.
   */
  rastreable: boolean;
  /** Entrada en el sitemap, o `null` si no debe anunciarse. */
  sitemap: { prioridad: number; frecuencia: Frecuencia } | null;
}

export const PAGINAS_PUBLICAS: readonly PaginaPublica[] = [
  {
    ruta: "/",
    coincidencia: "exacta",
    prerenderizada: true,
    rastreable: true,
    sitemap: { prioridad: 1, frecuencia: "daily" },
  },
  {
    // Prefijo: de aquí cuelgan los hubs por comunidad y las fichas, que llevan
    // cuatro segmentos. Sus URLs concretas las anuncia el sitemap particionado.
    ruta: "/licitaciones",
    coincidencia: "prefijo",
    prerenderizada: true,
    rastreable: true,
    sitemap: { prioridad: 0.9, frecuencia: "daily" },
  },
  {
    ruta: "/cpv",
    coincidencia: "prefijo",
    prerenderizada: true,
    rastreable: true,
    sitemap: { prioridad: 0.8, frecuencia: "daily" },
  },
  // Las tres páginas de evidencia. Son lo que pregunta quien está evaluando el
  // producto —qué entra en el corpus, cómo se calcula cada señal, qué protege
  // los datos— y la portada las enlaza en vez de intentar responderlo entera.
  {
    ruta: "/cobertura",
    coincidencia: "exacta",
    prerenderizada: true,
    rastreable: true,
    sitemap: { prioridad: 0.6, frecuencia: "monthly" },
  },
  {
    ruta: "/metodologia",
    coincidencia: "exacta",
    prerenderizada: true,
    rastreable: true,
    sitemap: { prioridad: 0.6, frecuencia: "monthly" },
  },
  {
    ruta: "/seguridad",
    coincidencia: "exacta",
    prerenderizada: true,
    rastreable: true,
    sitemap: { prioridad: 0.6, frecuencia: "monthly" },
  },
  {
    ruta: "/aviso-legal",
    coincidencia: "exacta",
    prerenderizada: true,
    rastreable: true,
    sitemap: { prioridad: 0.1, frecuencia: "yearly" },
  },
  {
    // Acuse de recibo del formulario: destino del 303 de la API, así que lo
    // alcanza gente sin sesión por definición. Dinámica (lee `searchParams`),
    // luego conserva la CSP con nonce; `noindex` en sus propios metadatos.
    ruta: "/solicitud-recibida",
    coincidencia: "prefijo",
    prerenderizada: false,
    rastreable: false,
    sitemap: null,
  },
  {
    // Superficie de credenciales: dinámica y con CSP estricta a propósito.
    ruta: "/login",
    coincidencia: "prefijo",
    prerenderizada: false,
    rastreable: true,
    sitemap: null,
  },
  {
    ruta: "/restablecer-contrasena",
    coincidencia: "prefijo",
    prerenderizada: false,
    rastreable: false,
    sitemap: null,
  },
];

/**
 * Un prefijo casa la ruta exacta y lo que cuelga de ella con `/`, no cualquier
 * cosa que empiece igual.
 *
 * Con `startsWith` a secas, `/cpv` abría también `/cpvfoo` y `/login` abría
 * `/loginfalso`: rutas que no existen, que el proxy servía como públicas y que
 * acababan en el 404 raíz —fuera del layout público— en vez de en el del grupo.
 * La frontera lo cierra sin tocar ninguna URL real.
 */
function casa(pagina: PaginaPublica, pathname: string): boolean {
  if (pagina.ruta === pathname) return true;
  return pagina.coincidencia === "prefijo" && pathname.startsWith(`${pagina.ruta}/`);
}

/** ¿Se sirve sin sesión? */
export function esPaginaPublica(pathname: string): boolean {
  return PAGINAS_PUBLICAS.some((pagina) => casa(pagina, pathname));
}

/** ¿Su HTML viene del build, y por tanto va sin nonce? */
export function esPaginaPrerenderizada(pathname: string): boolean {
  return PAGINAS_PUBLICAS.some((pagina) => pagina.prerenderizada && casa(pagina, pathname));
}

/**
 * Rutas del `Allow` de robots.txt.
 *
 * La portada se ancla con `$` para que abra la portada **y sólo la portada**:
 * sin el ancla, `Allow: /` anularía el `Disallow: /` y expondría el dashboard
 * entero al rastreo. Google resuelve los conflictos por especificidad, así que
 * las reglas más largas de aquí ganan sobre ese `Disallow`.
 */
export function rutasRastreables(): string[] {
  return PAGINAS_PUBLICAS.filter((p) => p.rastreable).map((p) => (p.ruta === "/" ? "/$" : p.ruta));
}

/** Páginas estáticas que anuncia el fichero 0 del sitemap. */
export function paginasDeSitemap(): { ruta: string; prioridad: number; frecuencia: Frecuencia }[] {
  return PAGINAS_PUBLICAS.filter((p) => p.sitemap !== null).map((p) => ({
    ruta: p.ruta,
    prioridad: p.sitemap!.prioridad,
    frecuencia: p.sitemap!.frecuencia,
  }));
}
