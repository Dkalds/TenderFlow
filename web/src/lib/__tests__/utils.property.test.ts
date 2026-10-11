import fc from "fast-check";
import { describe, expect, it } from "vitest";
import {
  EMPTY,
  foldText,
  formatCompactCurrency,
  formatCurrency,
  formatDate,
  formatDateTime,
  formatDiaCorto,
  formatDiaSemana,
  formatDiaYHora,
  formatHoraMinuto,
  formatMonth,
  formatNumber,
  formatPercent,
  formatRelativeHours,
  formatRelativeTime,
  formatTime,
  truncate,
} from "@/lib/utils";
import { comprobar, textoUnicode } from "@/test/propiedades";

/**
 * Los formateadores pintan lo que venga de la API en todas las pantallas. Sus
 * tests de ejemplo fijan el formato («12,5%», «1,2 M €»); lo que no dicen es
 * que **ningún** valor los hace lanzar ni deja en pantalla un `NaN`, un
 * `undefined` o un `Invalid Date`. Eso es lo que se comprueba aquí.
 */

/** Lo que nunca debe leerse en una celda. */
const BASURA = /NaN|undefined|null|Invalid|Infinity|∞/;

const NUMERO_FINITO = fc.oneof(
  fc.integer(),
  fc.double({ noNaN: true, noDefaultInfinity: true }),
  // Los importes reales: hasta miles de millones, con céntimos.
  fc.double({ min: -1e10, max: 1e10, noNaN: true }),
);
const FECHA_VALIDA = fc.date({ noInvalidDate: true });
/** Fechas del dominio: de la primera licitación electrónica a bastante después de hoy. */
const FECHA_DEL_DOMINIO = fc.date({ min: new Date("2000-01-01"), max: new Date("2099-12-31"), noInvalidDate: true });

describe("formateadores numéricos · con cualquier número finito", () => {
  it("ninguno lanza ni deja basura en el texto", () => {
    comprobar(
      fc.property(NUMERO_FINITO, fc.integer({ min: 0, max: 4 }), (valor, decimales) => {
        const textos = [
          formatCurrency(valor),
          formatCompactCurrency(valor),
          formatNumber(valor),
          formatNumber(valor, "es-ES", { agruparSiempre: true }),
          formatPercent(valor, decimales),
          formatRelativeHours(valor),
        ];
        for (const texto of textos) {
          expect(texto).not.toBe("");
          expect(texto).not.toBe(EMPTY);
          expect(texto).not.toMatch(BASURA);
        }
      }),
      // Seis formateadores de `Intl` por caso: es la propiedad cara del bloque.
      { numRuns: 100 },
    );
  });

  it("formatCurrency lleva el símbolo del euro y ningún decimal", () => {
    comprobar(
      fc.property(fc.double({ min: -1e12, max: 1e12, noNaN: true }), (valor) => {
        const texto = formatCurrency(valor);
        expect(texto.endsWith("€")).toBe(true);
        expect(texto).not.toContain(",");
      }),
    );
  });

  it("formatNumber sólo añade puntos de millar: quitándolos queda el mismo entero", () => {
    comprobar(
      fc.property(fc.maxSafeInteger(), fc.boolean(), (entero, agruparSiempre) => {
        const texto = formatNumber(entero, "es-ES", { agruparSiempre });
        expect(texto.replaceAll(".", "")).toBe(String(entero));
      }),
    );
  });

  it("agruparSiempre sólo cambia los números de cuatro cifras", () => {
    // Es el motivo de la opción: `es-ES` no agrupa «1038» y sí «10.380».
    comprobar(
      fc.property(fc.oneof(fc.integer({ min: -200_000, max: 200_000 }), fc.maxSafeInteger()), (entero) => {
        const normal = formatNumber(entero);
        const agrupado = formatNumber(entero, "es-ES", { agruparSiempre: true });
        const cuatroCifras = Math.abs(entero) >= 1000 && Math.abs(entero) <= 9999;

        expect(agrupado !== normal).toBe(cuatroCifras);
      }),
    );
  });

  it("formatPercent redondea a los decimales pedidos y no se aleja del valor", () => {
    comprobar(
      fc.property(
        fc.double({ min: -1e6, max: 1e6, noNaN: true }),
        fc.integer({ min: 0, max: 4 }),
        (valor, decimales) => {
          const texto = formatPercent(valor, decimales);

          expect(texto).toMatch(decimales === 0 ? /^-?\d+%$/ : new RegExp(`^-?\\d+,\\d{${decimales}}%$`));
          const leido = Number(texto.slice(0, -1).replace(",", "."));
          // Medio paso del último decimal, más el error de coma flotante.
          expect(Math.abs(leido - valor)).toBeLessThanOrEqual(0.5 * 10 ** -decimales + 1e-9);
        },
      ),
    );
  });
});

describe("formateadores numéricos · sin dato", () => {
  it("null y undefined dan siempre la raya, en todos", () => {
    for (const ausente of [null, undefined]) {
      expect(formatCurrency(ausente)).toBe(EMPTY);
      expect(formatCompactCurrency(ausente)).toBe(EMPTY);
      expect(formatNumber(ausente)).toBe(EMPTY);
      expect(formatPercent(ausente)).toBe(EMPTY);
      expect(formatRelativeHours(ausente)).toBe(EMPTY);
    }
  });

  it("formatRelativeHours trata como «sin dato» lo que no es un número finito", () => {
    comprobar(
      fc.property(fc.constantFrom(Number.NaN, Number.POSITIVE_INFINITY, Number.NEGATIVE_INFINITY), (valor) => {
        expect(formatRelativeHours(valor)).toBe(EMPTY);
      }),
    );
  });

  /**
   * Lo mismo sin el «finito» del enunciado. La API no puede mandar un `NaN`
   * (JSON no lo tiene), pero una división en el cliente sí lo fabrica:
   * `formatPercent((tramo.n / total) * 100)` con el total a cero es `0 / 0`.
   * Pintaban «NaN%», «NaN €» y «∞ €»; ahora es «sin dato», con la misma guarda
   * que ya tenía `formatRelativeHours`.
   */
  it("un NaN o un infinito se pinta como «sin dato», no como «NaN %»", () => {
    for (const valor of [Number.NaN, Number.POSITIVE_INFINITY, Number.NEGATIVE_INFINITY]) {
      expect(formatPercent(valor)).toBe(EMPTY);
      expect(formatCurrency(valor)).toBe(EMPTY);
      expect(formatCompactCurrency(valor)).toBe(EMPTY);
      expect(formatNumber(valor)).toBe(EMPTY);
    }
  });
});

describe("formateadores de fecha", () => {
  it("con una fecha válida, ninguno lanza ni deja basura en el texto", () => {
    comprobar(
      fc.property(FECHA_VALIDA, (fecha) => {
        const textos = [
          formatDate(fecha),
          formatDate(fecha, "es-ES", "Europe/Madrid"),
          formatDate(fecha.toISOString()),
          formatDateTime(fecha),
          formatDateTime(fecha.toISOString()),
          formatDiaYHora(fecha),
          formatTime(fecha),
          formatHoraMinuto(fecha),
          formatDiaSemana(fecha),
          formatDiaCorto(fecha),
          formatRelativeTime(fecha),
        ];
        for (const texto of textos) {
          expect(texto).not.toBe("");
          expect(texto).not.toBe(EMPTY);
          expect(texto).not.toMatch(BASURA);
        }
      }),
      // Once formateos de fecha por caso, cada uno con su `Intl` nuevo: con 200
      // casos este test solo pasaba de medio segundo, y en la suite completa
      // un caso cuesta varias veces lo que aislado.
      { numRuns: 40 },
    );
  });

  it("con un texto cualquiera, ninguno lanza ni se inventa una fecha inválida", () => {
    // Lo que no se entiende como fecha vuelve tal cual o como raya; lo que no
    // puede salir es el «Invalid Date» del motor.
    comprobar(
      fc.property(textoUnicode({ maxLength: 20 }), (texto) => {
        fc.pre(!BASURA.test(texto));
        const textos = [
          formatDate(texto),
          formatDateTime(texto),
          formatDiaYHora(texto),
          formatTime(texto),
          formatHoraMinuto(texto),
          formatRelativeTime(texto),
          formatMonth(texto),
          formatMonth(texto, true),
        ];
        for (const salida of textos) {
          expect(typeof salida).toBe("string");
          expect(salida).not.toMatch(BASURA);
        }
      }),
    );
  });

  it("formatDate acepta el formato heredado DD/MM/AAAA y da lo mismo que con ISO", () => {
    comprobar(
      fc.property(FECHA_DEL_DOMINIO, fc.constantFrom("/", "-"), (fecha, separador) => {
        const [año, mes, dia] = fecha.toISOString().slice(0, 10).split("-");
        const heredado = [dia, mes, año].join(separador);

        expect(formatDate(heredado)).toBe(formatDate(`${año}-${mes}-${dia}`));
      }),
    );
  });

  it("con un Date inválido, los que reciben fecha y hora devuelven la raya", () => {
    const invalida = new Date(Number.NaN);
    for (const formatear of [formatDateTime, formatDiaYHora, formatTime, formatHoraMinuto, formatRelativeTime]) {
      expect(formatear(invalida)).toBe(EMPTY);
    }
    expect(formatDiaSemana(invalida)).toBe(EMPTY);
    expect(formatDiaCorto(invalida)).toBe(EMPTY);
  });

  /**
   * Era el único de la familia que no cumplía lo de arriba. Un texto que no es
   * fecha lo devuelve tal cual (bien: se ve el dato crudo), pero un objeto
   * `Date` inválido caía en la misma rama y salía su `toString()`, que es
   * literalmente «Invalid Date». Lo encontró `fc.date()`, que genera también
   * fechas inválidas.
   */
  it("formatDate con un Date inválido devuelve la raya, como los demás", () => {
    expect(formatDate(new Date(Number.NaN))).toBe(EMPTY);
    // El texto que no es fecha sigue saliendo crudo.
    expect(formatDate("pendiente de fecha")).toBe("pendiente de fecha");
  });
});

describe("formatMonth", () => {
  const AÑO = fc.integer({ min: 1900, max: 2100 });
  const MES = fc.integer({ min: 1, max: 12 });
  const clave = (año: number, mes: number) => `${año}-${String(mes).padStart(2, "0")}`;

  it("la etiqueta depende sólo del mes, y no lleva el punto de la abreviatura", () => {
    comprobar(
      fc.property(AÑO, AÑO, MES, (año, otroAño, mes) => {
        const etiqueta = formatMonth(clave(año, mes));

        expect(etiqueta).toBe(formatMonth(clave(otroAño, mes)));
        expect(etiqueta).toMatch(/^\p{L}{3,4}$/u);
      }),
    );
  });

  it("con año, es la misma etiqueta seguida del año", () => {
    comprobar(
      fc.property(AÑO, MES, (año, mes) => {
        expect(formatMonth(clave(año, mes), true)).toBe(`${formatMonth(clave(año, mes))} ${año}`);
      }),
    );
  });

  it("doce meses dan doce etiquetas distintas", () => {
    const etiquetas = Array.from({ length: 12 }, (_, indice) => formatMonth(clave(2026, indice + 1)));
    expect(new Set(etiquetas).size).toBe(12);
  });
});

describe("truncate", () => {
  it("nunca pasa del máximo (más la elipsis) y conserva el principio", () => {
    comprobar(
      fc.property(textoUnicode({ maxLength: 60 }), fc.integer({ min: 0, max: 80 }), (texto, max) => {
        const corto = truncate(texto, max);

        expect(corto.length).toBeLessThanOrEqual(max + 1);
        if (texto.length <= max) {
          expect(corto).toBe(texto);
        } else {
          // El principio del texto y la elipsis. Se queda una unidad por debajo
          // del máximo sólo cuando cortar en él partiría un carácter en dos.
          const cuerpo = corto.slice(0, -1);
          expect(corto.endsWith("…")).toBe(true);
          expect(texto.startsWith(cuerpo)).toBe(true);
          expect(max - cuerpo.length).toBeLessThanOrEqual(1);
        }
      }),
    );
  });

  it("truncar lo ya truncado no vuelve a recortar", () => {
    comprobar(
      fc.property(textoUnicode({ maxLength: 60 }), fc.integer({ min: 0, max: 80 }), (texto, max) => {
        const corto = truncate(texto, max);
        expect(truncate(corto, max)).toBe(corto);
      }),
    );
  });

  /**
   * `slice` corta por unidades UTF-16 y un emoji ocupa dos: si el corte caía en
   * medio quedaba media pareja suelta, que el navegador pinta «�…». Lo encontró
   * el generador de texto Unicode. Los títulos de la contratación pública no
   * llevan emoji, pero `truncate` también recorta nombres de vistas, de reglas
   * y comentarios, que escribe el usuario.
   */
  it("no parte un carácter por la mitad", () => {
    expect(truncate("😀😀", 1)).toBe("…");
    expect(truncate("😀😀", 3)).toBe("😀…");
    comprobar(
      fc.property(textoUnicode({ maxLength: 12 }), fc.integer({ min: 0, max: 12 }), (texto, max) => {
        fc.pre(texto.isWellFormed());
        expect(truncate(texto, max).isWellFormed()).toBe(true);
      }),
    );
  });
});

describe("foldText", () => {
  /** El alfabeto con el que se escribe y se busca en la aplicación. */
  const TEXTO_CASTELLANO = fc.stringMatching(/^[a-zñçáéíóúüàèòïA-ZÑÇÁÉÍÓÚÜ0-9 .,/-]{0,30}$/);

  it("plegar dos veces es lo mismo que plegar una", () => {
    comprobar(
      fc.property(textoUnicode({ maxLength: 30 }), (texto) => {
        const plegado = foldText(texto);
        expect(foldText(plegado)).toBe(plegado);
      }),
    );
  });

  it("no distingue cómo está codificado el acento (NFC o NFD)", () => {
    // El mismo «á» puede llegar compuesto (teclado de Windows, la API) o
    // descompuesto (macOS, texto pegado de un PDF): la búsqueda no debe notarlo.
    comprobar(
      fc.property(textoUnicode({ maxLength: 30 }), (texto) => {
        expect(foldText(texto.normalize("NFC"))).toBe(foldText(texto.normalize("NFD")));
      }),
    );
  });

  it("no distingue mayúsculas ni acentos en castellano", () => {
    comprobar(
      fc.property(TEXTO_CASTELLANO, (texto) => {
        const plegado = foldText(texto);

        expect(foldText(texto.toUpperCase())).toBe(plegado);
        expect(foldText(texto.toLowerCase())).toBe(plegado);
        expect(plegado).toMatch(/^[a-z0-9 .,/-]*$/);
      }),
    );
  });
});
