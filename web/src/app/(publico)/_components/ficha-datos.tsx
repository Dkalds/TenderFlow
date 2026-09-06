import type { LicitacionPublica } from "@/lib/publico-api";
import { formatCurrency } from "@/lib/utils";
import { fechaOpcional } from "./ficha-formato";
import { plazoPresentacion } from "./plazo";

/** Par etiqueta/valor; `null` en el valor significa "la fuente no lo publica". */
type Par = [string, string | null];

/**
 * Los tres datos que deciden si el anuncio interesa.
 *
 * Todo son valores del endpoint tal cual — aquí no se calcula ni se interpreta
 * nada (ADR-014). Lo único que se decide es el **rótulo** del plazo: la fecha
 * es la que dio el endpoint y lo que se corrige es la promesa que la envolvía.
 * Un «Fecha límite» sobre un plazo vencido se lee como una convocatoria
 * abierta, y esta ficha es lo primero que ve quien llega desde un buscador.
 */
export function destacadosDeAnuncio(lic: LicitacionPublica): Par[] {
  const plazo = plazoPresentacion(lic.fecha_limite);
  return [
    ["Presupuesto", lic.importe ? formatCurrency(lic.importe) : null],
    [plazo?.vencido ? "Plazo cerrado" : "Fecha límite", plazo?.fecha ?? null],
    ["Publicación", fechaOpcional(lic.fecha_publicacion)],
  ];
}

/**
 * El resto del anuncio. Lo que ya está arriba (destacados y chips de cabecera:
 * estado y expediente) no se repite aquí.
 */
export function datosDeAnuncio(lic: LicitacionPublica): Par[] {
  return [
    ["Órgano de contratación", lic.organo_contratacion ?? null],
    ["CPV", lic.cpv ?? null],
    ["Tipo de contrato", lic.tipo_contrato ?? null],
    ["Procedimiento", lic.procedimiento ?? null],
    ["Tramitación", lic.tramitacion ?? null],
    ["Inicio de ejecución", fechaOpcional(lic.fecha_inicio)],
    ["Fin de ejecución", fechaOpcional(lic.fecha_fin)],
    ["Duración", lic.duracion_valor ? `${lic.duracion_valor} ${lic.duracion_unidad ?? ""}`.trim() : null],
    ["Provincia", lic.provincia ?? null],
    ["Comunidad autónoma", lic.ccaa ?? null],
  ];
}

/** Sólo se pintan los pares con valor: un campo vacío no ocupa hueco. */
function conValor(pares: Par[]): [string, string][] {
  return pares.filter((par): par is [string, string] => Boolean(par[1]));
}

export function DatosDelAnuncio({ lic }: { lic: LicitacionPublica }) {
  const destacados = conValor(destacadosDeAnuncio(lic));
  const datos = conValor(datosDeAnuncio(lic));

  return (
    <>
      {destacados.length > 0 && (
        <dl className="mt-8 grid gap-3 sm:grid-cols-3">
          {destacados.map(([etiqueta, valor]) => (
            <div key={etiqueta} className="border-border/70 bg-card rounded-xl border p-4">
              <dt className="text-muted-foreground text-[11px] tracking-wide uppercase">{etiqueta}</dt>
              <dd className="font-display tf-tnum mt-1 text-xl font-semibold tracking-[-0.01em]">{valor}</dd>
            </div>
          ))}
        </dl>
      )}

      <h2 className="font-display mt-12 text-xl font-semibold tracking-[-0.02em]">Datos del anuncio</h2>
      <dl className="border-border/70 bg-card mt-5 grid gap-x-10 gap-y-4 rounded-xl border p-6 sm:grid-cols-2">
        {datos.map(([etiqueta, valor]) => (
          <div key={etiqueta}>
            <dt className="text-muted-foreground text-[11px] tracking-wide uppercase">{etiqueta}</dt>
            <dd className="mt-0.5 text-sm font-medium">{valor}</dd>
          </div>
        ))}
      </dl>
    </>
  );
}
