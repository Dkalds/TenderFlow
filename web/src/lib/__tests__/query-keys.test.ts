/**
 * Registro de claves de React Query: los invariantes que hacen que la caché
 * sirva el dato correcto.
 *
 * `lib/query-keys.ts` nació de dos incidentes reales que su propia cabecera
 * documenta, y los dos son invisibles para el compilador —una `queryKey` es un
 * array de literales, así que TypeScript no compara nada entre ficheros:
 *
 *  1. **Dos `queryFn` bajo la misma clave.** `["ask-models"]` estaba declarada
 *     en `hooks/use-ask.ts` y otra vez en `investigador/page.tsx` con un
 *     `fetch` crudo. React Query cachea por clave, no por función: ganaba la
 *     que montara primero y el selector de modelos mostraba una cosa u otra
 *     según el orden de navegación.
 *  2. **Dos claves para el mismo dato.** `/analytics/quality` se pedía con
 *     cuatro claves distintas: cuatro entradas de caché y cuatro peticiones
 *     para una respuesta idéntica.
 *
 * Estos tests no comprueban strings: montan un `QueryClient` de verdad y
 * preguntan a su caché, porque lo que importa no es cómo se escribe la clave
 * sino a qué alcanza `invalidateQueries` — que es *prefix matching* sobre el
 * array, no comparación de textos.
 */
import { describe, expect, it } from "vitest";
import { QueryClient } from "@tanstack/react-query";
import * as registro from "@/lib/query-keys";
import {
  adminKeys,
  analyticsKeys,
  askKeys,
  authKeys,
  calendarioKeys,
  competitiveKeys,
  documentosKeys,
  empresasKeys,
  eventosKeys,
  feedbackKeys,
  fichaKeys,
  licitacionKeys,
  licitacionesKeys,
  metaKeys,
  organizationKeys,
  perfilKeys,
  prediccionKeys,
  pursuitCommentKeys,
  pursuitKeys,
  radarKeys,
  renovacionesKeys,
  resolucionesKeys,
  tecnologiasKeys,
  watchlistKeys,
  webhookKeys,
} from "@/lib/query-keys";

type Clave = readonly unknown[];

interface Miembro {
  /** Nombre cualificado, tal y como se escribe en el sitio de uso. */
  readonly nombre: string;
  readonly clave: Clave;
}

interface Fabrica {
  readonly nombre: string;
  /** La raíz `all`, cuando la fábrica la declara. */
  readonly raiz?: Clave;
  readonly miembros: readonly Miembro[];
}

/**
 * El registro entero, materializado.
 *
 * Las fábricas parametrizadas se invocan con un argumento de muestra: una
 * clave sin materializar no se puede comparar con nada, y además así cada
 * fábrica se ejecuta al menos una vez (una que reventara con su propio
 * argumento no llegaría a producción sin que esto se entere).
 */
const FABRICAS: readonly Fabrica[] = [
  {
    nombre: "authKeys",
    raiz: authKeys.all,
    miembros: [{ nombre: "authKeys.me", clave: authKeys.me }],
  },
  {
    nombre: "metaKeys",
    raiz: metaKeys.all,
    miembros: [
      { nombre: "metaKeys.filters", clave: metaKeys.filters },
      { nombre: "metaKeys.lastExtraction", clave: metaKeys.lastExtraction },
    ],
  },
  {
    nombre: "licitacionKeys",
    raiz: licitacionKeys.all,
    miembros: [{ nombre: "licitacionKeys.detail", clave: licitacionKeys.detail("ES-1") }],
  },
  {
    nombre: "licitacionesKeys",
    raiz: licitacionesKeys.all,
    miembros: [{ nombre: "licitacionesKeys.list", clave: licitacionesKeys.list({ q: "obras" }) }],
  },
  {
    nombre: "documentosKeys",
    raiz: documentosKeys.all,
    miembros: [
      { nombre: "documentosKeys.byLicitacion", clave: documentosKeys.byLicitacion("ES-1") },
    ],
  },
  {
    nombre: "eventosKeys",
    raiz: eventosKeys.all,
    miembros: [{ nombre: "eventosKeys.byLicitacion", clave: eventosKeys.byLicitacion("ES-1") }],
  },
  {
    nombre: "resolucionesKeys",
    raiz: resolucionesKeys.all,
    miembros: [
      { nombre: "resolucionesKeys.byLicitacion", clave: resolucionesKeys.byLicitacion("ES-1") },
    ],
  },
  {
    nombre: "tecnologiasKeys",
    raiz: tecnologiasKeys.all,
    miembros: [
      { nombre: "tecnologiasKeys.byLicitacion", clave: tecnologiasKeys.byLicitacion("ES-1") },
    ],
  },
  {
    nombre: "prediccionKeys",
    miembros: [
      { nombre: "prediccionKeys.baja", clave: prediccionKeys.baja("ES-1") },
      { nombre: "prediccionKeys.calibracion", clave: prediccionKeys.calibracion },
      { nombre: "prediccionKeys.escenarios", clave: prediccionKeys.escenarios("ES-1") },
    ],
  },
  {
    nombre: "fichaKeys",
    raiz: fichaKeys.all,
    miembros: [
      { nombre: "fichaKeys.detail", clave: fichaKeys.detail("ES-1") },
      { nombre: "fichaKeys.estado", clave: fichaKeys.estado("ES-1") },
    ],
  },
  {
    nombre: "analyticsKeys",
    raiz: analyticsKeys.all,
    miembros: [
      { nombre: "analyticsKeys.quality", clave: analyticsKeys.quality },
      { nombre: "analyticsKeys.sourceFreshness", clave: analyticsKeys.sourceFreshness },
      { nombre: "analyticsKeys.overview", clave: analyticsKeys.overview({ desde: "2026-01-01" }) },
      { nombre: "analyticsKeys.scoringBatch", clave: analyticsKeys.scoringBatch(["ES-1"]) },
    ],
  },
  {
    nombre: "radarKeys",
    raiz: radarKeys.all,
    miembros: [
      { nombre: "radarKeys.scoring", clave: radarKeys.scoring },
      { nombre: "radarKeys.scopedScoring", clave: radarKeys.scopedScoring(1, "SAP") },
      { nombre: "radarKeys.dismissed", clave: radarKeys.dismissed(1, ["ES-1"]) },
      { nombre: "radarKeys.organo", clave: radarKeys.organo("Ayuntamiento") },
    ],
  },
  {
    nombre: "askKeys",
    raiz: askKeys.all,
    miembros: [{ nombre: "askKeys.models", clave: askKeys.models }],
  },
  {
    nombre: "watchlistKeys",
    raiz: watchlistKeys.all,
    miembros: [
      { nombre: "watchlistKeys.items", clave: watchlistKeys.items },
      { nombre: "watchlistKeys.rules", clave: watchlistKeys.rules },
      { nombre: "watchlistKeys.combined", clave: watchlistKeys.combined("1,2") },
      { nombre: "watchlistKeys.empresas", clave: watchlistKeys.empresas },
    ],
  },
  {
    nombre: "empresasKeys",
    raiz: empresasKeys.all,
    miembros: [
      { nombre: "empresasKeys.list", clave: empresasKeys.list("acme") },
      { nombre: "empresasKeys.stats", clave: empresasKeys.stats },
      { nombre: "empresasKeys.reviews", clave: empresasKeys.reviews },
      { nombre: "empresasKeys.detail", clave: empresasKeys.detail(7) },
      { nombre: "empresasKeys.perfil", clave: empresasKeys.perfil(7) },
    ],
  },
  {
    nombre: "competitiveKeys",
    raiz: competitiveKeys.all,
    miembros: [
      {
        nombre: "competitiveKeys.companyProfile",
        clave: competitiveKeys.companyProfile(7, "organization_id=1"),
      },
      {
        nombre: "competitiveKeys.companyAwards",
        clave: competitiveKeys.companyAwards(7, "limit=20"),
      },
    ],
  },
  {
    nombre: "pursuitKeys",
    raiz: pursuitKeys.all,
    miembros: [
      { nombre: "pursuitKeys.list", clave: pursuitKeys.list({ estado: "abierto" }) },
      { nombre: "pursuitKeys.detail", clave: pursuitKeys.detail("7") },
      { nombre: "pursuitKeys.metrics", clave: pursuitKeys.metrics },
      { nombre: "pursuitKeys.agenda", clave: pursuitKeys.agenda },
    ],
  },
  {
    nombre: "pursuitCommentKeys",
    raiz: pursuitCommentKeys.all,
    miembros: [{ nombre: "pursuitCommentKeys.thread", clave: pursuitCommentKeys.thread(7) }],
  },
  {
    nombre: "organizationKeys",
    raiz: organizationKeys.all,
    miembros: [
      { nombre: "organizationKeys.members", clave: organizationKeys.members(1) },
      { nombre: "organizationKeys.settings", clave: organizationKeys.settings(1) },
    ],
  },
  {
    nombre: "perfilKeys",
    miembros: [{ nombre: "perfilKeys.me", clave: perfilKeys.me }],
  },
  {
    nombre: "calendarioKeys",
    miembros: [{ nombre: "calendarioKeys.enlace", clave: calendarioKeys.enlace }],
  },
  {
    nombre: "feedbackKeys",
    raiz: feedbackKeys.all,
    miembros: [
      { nombre: "feedbackKeys.stats", clave: feedbackKeys.stats },
      { nombre: "feedbackKeys.modelInfo", clave: feedbackKeys.modelInfo },
      { nombre: "feedbackKeys.queue", clave: feedbackKeys.queue("uncertainty") },
    ],
  },
  {
    nombre: "webhookKeys",
    raiz: webhookKeys.all,
    miembros: [
      { nombre: "webhookKeys.eventTypes", clave: webhookKeys.eventTypes },
      { nombre: "webhookKeys.deliveries", clave: webhookKeys.deliveries(3) },
    ],
  },
  {
    nombre: "adminKeys",
    miembros: [
      { nombre: "adminKeys.users", clave: adminKeys.users },
      { nombre: "adminKeys.apiKeys", clave: adminKeys.apiKeys },
      { nombre: "adminKeys.health", clave: adminKeys.health },
      { nombre: "adminKeys.accessGrants", clave: adminKeys.accessGrants },
    ],
  },
  {
    // Sub-fábrica anidada: `adminKeys.solicitudes` tiene su propio `all`, y es
    // el que usa `solicitudes-acceso-card.tsx` al aprobar una solicitud.
    nombre: "adminKeys.solicitudes",
    raiz: adminKeys.solicitudes.all,
    miembros: [
      {
        nombre: "adminKeys.solicitudes.vista",
        clave: adminKeys.solicitudes.vista("pendiente"),
      },
    ],
  },
  {
    nombre: "renovacionesKeys",
    raiz: renovacionesKeys.all,
    miembros: [
      { nombre: "renovacionesKeys.lista", clave: renovacionesKeys.lista(6, "SAP") },
      { nombre: "renovacionesKeys.resumen", clave: renovacionesKeys.resumen(6, "SAP") },
    ],
  },
];

/** Todas las claves del registro, con su nombre cualificado. */
const TODAS: readonly Miembro[] = FABRICAS.flatMap((fabrica) => [
  ...(fabrica.raiz ? [{ nombre: `${fabrica.nombre}.all`, clave: fabrica.raiz }] : []),
  ...fabrica.miembros,
]);

/** ¿Es `posiblePrefijo` un prefijo de `clave`? Es lo que hace React Query. */
function esPrefijo(posiblePrefijo: Clave, clave: Clave): boolean {
  if (posiblePrefijo.length > clave.length) return false;
  return posiblePrefijo.every(
    (segmento, indice) => JSON.stringify(segmento) === JSON.stringify(clave[indice]),
  );
}

/** Una caché real con una entrada por clave, para preguntarle a React Query. */
function cacheCon(claves: readonly Clave[]): QueryClient {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  for (const clave of claves) client.setQueryData(clave, null);
  return client;
}

describe("el registro está completo", () => {
  it("cubre todas las fábricas exportadas", () => {
    // Sin esto, una fábrica nueva se escaparía de todos los tests de abajo
    // simplemente por no aparecer en la tabla. La comparación es contra los
    // exports del módulo, así que añadir una obliga a declararla aquí.
    const exportadas = Object.keys(registro).sort();
    const declaradas = FABRICAS.map((fabrica) => fabrica.nombre)
      .filter((nombre) => !nombre.includes("."))
      .sort();

    expect(declaradas).toEqual(exportadas);
  });
});

describe("una clave, un recurso", () => {
  it("no hay dos entradas del registro que produzcan la misma clave", () => {
    // El incidente de `["ask-models"]`: dos declaraciones de la misma clave con
    // dos `queryFn` distintas. React Query cachea por clave, así que la segunda
    // no crea una entrada nueva — se cuela en la de la primera.
    const porClave = new Map<string, string[]>();
    for (const { nombre, clave } of TODAS) {
      const hash = JSON.stringify(clave);
      porClave.set(hash, [...(porClave.get(hash) ?? []), nombre]);
    }

    const duplicadas = [...porClave.entries()]
      .filter(([, nombres]) => nombres.length > 1)
      .map(([hash, nombres]) => `${hash} ← ${nombres.join(" y ")}`);

    expect(duplicadas).toEqual([]);
  });

  it("ninguna clave es prefijo de la de otro recurso", () => {
    // Un prefijo compartido entre recursos distintos es la colisión silenciosa:
    // `invalidateQueries` del recurso A tiraría la caché del recurso B, y
    // `findAll` del A devolvería entradas del B. Dentro de una misma fábrica el
    // prefijo sí es deliberado (es lo que hace útil a `all`), así que sólo se
    // comprueba entre fábricas.
    const cruces: string[] = [];
    for (const fabricaA of FABRICAS) {
      for (const fabricaB of FABRICAS) {
        if (fabricaA.nombre === fabricaB.nombre) continue;
        // `adminKeys.solicitudes` vive *dentro* de `adminKeys`: no son dos
        // recursos, es el mismo con una sub-fábrica.
        if (
          fabricaA.nombre.startsWith(`${fabricaB.nombre}.`) ||
          fabricaB.nombre.startsWith(`${fabricaA.nombre}.`)
        ) {
          continue;
        }
        const clavesA = [...(fabricaA.raiz ? [fabricaA.raiz] : []), ...fabricaA.miembros.map((m) => m.clave)];
        const clavesB = [...(fabricaB.raiz ? [fabricaB.raiz] : []), ...fabricaB.miembros.map((m) => m.clave)];
        for (const claveA of clavesA) {
          for (const claveB of clavesB) {
            if (esPrefijo(claveA, claveB)) {
              cruces.push(`${fabricaA.nombre}:${JSON.stringify(claveA)} ⊑ ${fabricaB.nombre}:${JSON.stringify(claveB)}`);
            }
          }
        }
      }
    }

    expect(cruces).toEqual([]);
  });

  it("cada fábrica ocupa un primer segmento propio", () => {
    // El prefijo sólo puede cruzarse si dos fábricas comparten primer segmento.
    // Comprobarlo aparte hace que el fallo sea legible: el test de arriba diría
    // «hay una colisión», este dice cuál es el segmento en disputa.
    const dueño = new Map<string, string>();
    const conflictos: string[] = [];
    for (const fabrica of FABRICAS) {
      // La sub-fábrica anidada comparte espacio de nombres con su contenedora.
      const contenedora = fabrica.nombre.split(".")[0];
      const claves = [...(fabrica.raiz ? [fabrica.raiz] : []), ...fabrica.miembros.map((m) => m.clave)];
      for (const clave of claves) {
        const segmento = String(clave[0]);
        const previo = dueño.get(segmento);
        if (previo && previo !== contenedora) {
          conflictos.push(`"${segmento}" lo usan ${previo} y ${contenedora}`);
        }
        dueño.set(segmento, contenedora);
      }
    }

    expect(conflictos).toEqual([]);
  });
});

describe("las fábricas parametrizadas", () => {
  /**
   * Cada entrada invoca la fábrica dos veces con el mismo argumento y una
   * tercera con otro distinto. Comprueba las dos mitades del contrato:
   * estabilidad (misma entrada ⇒ misma clave, o cada render sería un fallo de
   * caché) y discriminación (entradas distintas ⇒ claves distintas, o un
   * recurso serviría los datos de otro).
   */
  const PARAMETRIZADAS: ReadonlyArray<{
    readonly nombre: string;
    readonly conA: () => Clave;
    readonly conB: () => Clave;
  }> = [
    { nombre: "licitacionKeys.detail", conA: () => licitacionKeys.detail("ES-1"), conB: () => licitacionKeys.detail("ES-2") },
    { nombre: "licitacionesKeys.list", conA: () => licitacionesKeys.list({ q: "obras" }), conB: () => licitacionesKeys.list({ q: "software" }) },
    { nombre: "documentosKeys.byLicitacion", conA: () => documentosKeys.byLicitacion("ES-1"), conB: () => documentosKeys.byLicitacion("ES-2") },
    { nombre: "eventosKeys.byLicitacion", conA: () => eventosKeys.byLicitacion("ES-1"), conB: () => eventosKeys.byLicitacion("ES-2") },
    { nombre: "resolucionesKeys.byLicitacion", conA: () => resolucionesKeys.byLicitacion("ES-1"), conB: () => resolucionesKeys.byLicitacion("ES-2") },
    { nombre: "tecnologiasKeys.byLicitacion", conA: () => tecnologiasKeys.byLicitacion("ES-1"), conB: () => tecnologiasKeys.byLicitacion("ES-2") },
    { nombre: "prediccionKeys.baja", conA: () => prediccionKeys.baja("ES-1"), conB: () => prediccionKeys.baja("ES-2") },
    { nombre: "prediccionKeys.escenarios", conA: () => prediccionKeys.escenarios("ES-1"), conB: () => prediccionKeys.escenarios(null) },
    { nombre: "fichaKeys.detail", conA: () => fichaKeys.detail("ES-1"), conB: () => fichaKeys.detail("ES-2") },
    { nombre: "fichaKeys.estado", conA: () => fichaKeys.estado("ES-1"), conB: () => fichaKeys.estado("ES-2") },
    { nombre: "analyticsKeys.overview", conA: () => analyticsKeys.overview({ desde: "2026-01-01" }), conB: () => analyticsKeys.overview({ desde: "2026-02-01" }) },
    { nombre: "analyticsKeys.scoringBatch", conA: () => analyticsKeys.scoringBatch(["ES-1"]), conB: () => analyticsKeys.scoringBatch(["ES-1", "ES-2"]) },
    { nombre: "radarKeys.scopedScoring", conA: () => radarKeys.scopedScoring(1, "SAP"), conB: () => radarKeys.scopedScoring(2, "SAP") },
    { nombre: "radarKeys.dismissed", conA: () => radarKeys.dismissed(1, ["ES-1"]), conB: () => radarKeys.dismissed(1, ["ES-2"]) },
    { nombre: "radarKeys.organo", conA: () => radarKeys.organo("Ayuntamiento"), conB: () => radarKeys.organo(null) },
    { nombre: "watchlistKeys.combined", conA: () => watchlistKeys.combined("1,2"), conB: () => watchlistKeys.combined("1,3") },
    { nombre: "empresasKeys.list", conA: () => empresasKeys.list("acme"), conB: () => empresasKeys.list("globex") },
    { nombre: "empresasKeys.detail", conA: () => empresasKeys.detail(7), conB: () => empresasKeys.detail(8) },
    { nombre: "empresasKeys.perfil", conA: () => empresasKeys.perfil(7), conB: () => empresasKeys.perfil(8) },
    { nombre: "competitiveKeys.companyProfile", conA: () => competitiveKeys.companyProfile(7, "organization_id=1"), conB: () => competitiveKeys.companyProfile(7, "organization_id=2") },
    { nombre: "competitiveKeys.companyAwards", conA: () => competitiveKeys.companyAwards(7, "limit=20"), conB: () => competitiveKeys.companyAwards(7, { limit: "20" }) },
    { nombre: "pursuitKeys.list", conA: () => pursuitKeys.list({ estado: "abierto" }), conB: () => pursuitKeys.list({ estado: "ganado" }) },
    { nombre: "pursuitKeys.detail", conA: () => pursuitKeys.detail("7"), conB: () => pursuitKeys.detail("8") },
    { nombre: "pursuitCommentKeys.thread", conA: () => pursuitCommentKeys.thread(7), conB: () => pursuitCommentKeys.thread(8) },
    { nombre: "organizationKeys.members", conA: () => organizationKeys.members(1), conB: () => organizationKeys.members(2) },
    { nombre: "organizationKeys.settings", conA: () => organizationKeys.settings(1), conB: () => organizationKeys.settings(null) },
    { nombre: "feedbackKeys.queue", conA: () => feedbackKeys.queue("uncertainty"), conB: () => feedbackKeys.queue("random") },
    { nombre: "webhookKeys.deliveries", conA: () => webhookKeys.deliveries(3), conB: () => webhookKeys.deliveries(null) },
    { nombre: "adminKeys.solicitudes.vista", conA: () => adminKeys.solicitudes.vista("pendiente"), conB: () => adminKeys.solicitudes.vista("historico") },
    { nombre: "renovacionesKeys.lista", conA: () => renovacionesKeys.lista(6, "SAP"), conB: () => renovacionesKeys.lista(12, "SAP") },
    { nombre: "renovacionesKeys.resumen", conA: () => renovacionesKeys.resumen(6, "SAP"), conB: () => renovacionesKeys.resumen(6, null) },
  ];

  it("cubre todas las fábricas que reciben argumentos", () => {
    // Igual que el test de completitud del registro, pero para la tabla de esta
    // sección: una fábrica parametrizada nueva que no se liste aquí no vería
    // comprobadas ni su estabilidad ni su discriminación, y la ausencia pasaría
    // desapercibida porque no hay nada rojo.
    const listadas = PARAMETRIZADAS.map((entrada) => entrada.nombre).sort();

    expect(listadas).toEqual([...FABRICAS_CON_ARGUMENTOS].sort());
  });

  it.each(PARAMETRIZADAS)("$nombre es estable con el mismo argumento", ({ conA }) => {
    // React Query hashea la clave estructuralmente: si la fábrica metiera algo
    // volátil (un `Date.now()`, un objeto con identidad nueva y campos
    // distintos), cada render pediría de nuevo y la caché no serviría de nada.
    expect(conA()).toEqual(conA());
  });

  it.each(PARAMETRIZADAS)("$nombre distingue argumentos distintos", ({ conA, conB }) => {
    // Una fábrica que ignore su parámetro devuelve la misma entrada de caché
    // para dos recursos: la licitación B mostraría los documentos de la A.
    expect(conA()).not.toEqual(conB());
  });

  it("el hilo de comentarios normaliza el id a texto", () => {
    // `pursuitCommentKeys.thread` hace `String(pursuitId)` a propósito: la
    // página pasa el número y el hilo la cadena. Sin normalizar serían dos
    // entradas de caché para el mismo hilo, y publicar un comentario sólo
    // refrescaría una de las dos.
    expect(pursuitCommentKeys.thread(7)).toEqual(pursuitCommentKeys.thread("7"));
  });
});

/**
 * Miembros del registro que son funciones. Se escribe a mano a propósito: una
 * lista derivada del propio módulo se «actualizaría sola» y dejaría de avisar
 * cuando se añade una fábrica sin tests.
 */
const FABRICAS_CON_ARGUMENTOS: readonly string[] = [
  "licitacionKeys.detail",
  "licitacionesKeys.list",
  "documentosKeys.byLicitacion",
  "eventosKeys.byLicitacion",
  "resolucionesKeys.byLicitacion",
  "tecnologiasKeys.byLicitacion",
  "prediccionKeys.baja",
  "prediccionKeys.escenarios",
  "fichaKeys.detail",
  "fichaKeys.estado",
  "analyticsKeys.overview",
  "analyticsKeys.scoringBatch",
  "radarKeys.scopedScoring",
  "radarKeys.dismissed",
  "radarKeys.organo",
  "watchlistKeys.combined",
  "empresasKeys.list",
  "empresasKeys.detail",
  "empresasKeys.perfil",
  "competitiveKeys.companyProfile",
  "competitiveKeys.companyAwards",
  "pursuitKeys.list",
  "pursuitKeys.detail",
  "pursuitCommentKeys.thread",
  "organizationKeys.members",
  "organizationKeys.settings",
  "feedbackKeys.queue",
  "webhookKeys.deliveries",
  "adminKeys.solicitudes.vista",
  "renovacionesKeys.lista",
  "renovacionesKeys.resumen",
];

describe("`all` invalida de verdad a sus hijas", () => {
  it("alcanza por prefijo a todas las claves que comparten su raíz", () => {
    // No se compara texto: se llena un `QueryCache` real y se le pregunta con
    // los mismos filtros que usa `invalidateQueries`. Si React Query cambiara
    // su semántica de prefijo, este test lo vería; uno que comparase strings,
    // no.
    for (const fabrica of FABRICAS) {
      if (!fabrica.raiz) continue;
      const raiz = fabrica.raiz;
      const esperadas = fabrica.miembros
        .filter((miembro) => esPrefijo(raiz, miembro.clave))
        .map((miembro) => JSON.stringify(miembro.clave))
        .sort();

      const client = cacheCon(fabrica.miembros.map((miembro) => miembro.clave));
      const alcanzadas = client
        .getQueryCache()
        .findAll({ queryKey: raiz })
        .map((query) => JSON.stringify(query.queryKey))
        .sort();

      expect({ fabrica: fabrica.nombre, alcanzadas }).toEqual({
        fabrica: fabrica.nombre,
        alcanzadas: esperadas,
      });
    }
  });

  it("invalidar la raíz de `pursuits` marca lista, detalle, métricas y agenda", () => {
    // El caso que sí se ejerce en producción: `use-pursuits.ts` y
    // `use-pursuit-comments.ts` invalidan `pursuitKeys.all` tras cada mutación
    // y esperan que las cuatro vistas del pipeline se refresquen a la vez.
    const claves = [
      pursuitKeys.list({ estado: "abierto" }),
      pursuitKeys.detail("7"),
      pursuitKeys.metrics,
      pursuitKeys.agenda,
    ];
    const client = cacheCon(claves);

    void client.invalidateQueries({ queryKey: pursuitKeys.all });

    const invalidadas = client
      .getQueryCache()
      .getAll()
      .filter((query) => query.state.isInvalidated)
      .map((query) => JSON.stringify(query.queryKey))
      .sort();
    expect(invalidadas).toEqual(claves.map((clave) => JSON.stringify(clave)).sort());
  });

  it("invalidar `pursuits` no toca el hilo de comentarios, que tiene su propia raíz", () => {
    // `["pursuits"]` y `["pursuit-comments"]` se parecen al leerlos, pero son
    // segmentos distintos: el prefijo no los relaciona. Es deliberado —
    // `use-pursuit-comments.ts` invalida las dos raíces por separado.
    const client = cacheCon([pursuitKeys.agenda, pursuitCommentKeys.thread(7)]);

    void client.invalidateQueries({ queryKey: pursuitKeys.all });

    const hilo = client
      .getQueryCache()
      .find({ queryKey: pursuitCommentKeys.thread(7), exact: true });
    expect(hilo?.state.isInvalidated).toBe(false);
  });

  /**
   * Claves que su propia `all` **no** alcanza.
   *
   * No es cobertura de relleno ni una excusa: es el inventario de la deuda que
   * quedó al unificar el registro. Estas claves conservaron su literal
   * histórico (`["feedback-stats"]`, `["organization-members", id]`…) en vez de
   * pasar a `["feedback", "stats"]`, porque renombrarlas invalida de golpe
   * todas las entradas vivas de los clientes ya desplegados. Mientras sigan
   * así, `invalidateQueries({ queryKey: X.all })` NO las refresca y cada sitio
   * de uso tiene que invalidarlas a mano — que es justo lo que hacen hoy
   * `empresas/page.tsx` (invalida `reviews`, `stats` y `all` por separado) y
   * `use-organization.ts` (invalida `members(id)`, no `all`).
   *
   * La lista se fija aquí para que crezca sólo a conciencia: añadir una clave
   * nueva fuera de la raíz de su fábrica rompe este test, y quien la añada
   * tiene que decidir si es deuda deliberada o un descuido.
   */
  it("el inventario de claves huérfanas de su `all` no crece por descuido", () => {
    const huerfanas = FABRICAS.flatMap((fabrica) =>
      fabrica.raiz
        ? fabrica.miembros
            .filter((miembro) => !esPrefijo(fabrica.raiz!, miembro.clave))
            .map((miembro) => miembro.nombre)
        : [],
    ).sort();

    expect(huerfanas).toEqual([
      "analyticsKeys.scoringBatch",
      "askKeys.models",
      "competitiveKeys.companyAwards",
      "competitiveKeys.companyProfile",
      "empresasKeys.detail",
      "empresasKeys.perfil",
      "empresasKeys.reviews",
      "empresasKeys.stats",
      "feedbackKeys.modelInfo",
      "feedbackKeys.queue",
      "feedbackKeys.stats",
      "fichaKeys.estado",
      "organizationKeys.members",
      "organizationKeys.settings",
      "renovacionesKeys.resumen",
      "watchlistKeys.combined",
      "watchlistKeys.empresas",
      "watchlistKeys.items",
      "watchlistKeys.rules",
    ]);
  });
});
