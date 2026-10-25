import { PrefetchServidor } from "@/components/prefetch-servidor";
import { consultasFicha } from "./_lib/prefetch";
import { FichaOportunidad } from "./_components/ficha-view";

/**
 * Ficha de la oportunidad en servidor: pide mientras renderiza lo único de la
 * ficha que no depende de la organización activa —el listado de
 * organizaciones, primer eslabón de su cascada— y se lo entrega hidratado a
 * `FichaOportunidad`, la pantalla cliente de siempre. Por qué no se pide nada
 * más, en `_lib/prefetch.ts`; el patrón, en `web/AGENTS.md` (S7.1).
 */
export default function OportunidadPage() {
  return (
    <PrefetchServidor consultas={consultasFicha()}>
      <FichaOportunidad />
    </PrefetchServidor>
  );
}
