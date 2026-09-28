import { EnlaceIrPublico } from "@/app/(publico)/_components/enlace-ir";
import { Puerta } from "@/app/(publico)/_components/puerta";

/**
 * 404 de última instancia: URLs que no caen en ningún grupo de rutas.
 *
 * Quién llega aquí. Una ruta desconocida **sin relación con nada público** la
 * corta antes el proxy, que la trata como privada y devuelve un 307 a `/login`
 * (ver `proxy.ts` y su test). Pero también aterrizan aquí las URLs sin ruta que
 * sí cuelgan de un prefijo público —una ficha con un segmento de más, un enlace
 * viejo de un buscador— y ésas las ve un visitante anónimo. Por eso los destinos
 * son la portada y los índices públicos y no `/resumen`, que para él es otro
 * muro de login.
 *
 * Va con la carcasa de la puerta (decisión D4): la cabecera mínima con el logo
 * enlazado y la composición editorial de la portada. Era una `Card` centrada
 * con un icono de interrogación, el 404 por defecto de las plantillas.
 *
 * Las 404 de las rutas que sí existen —un hub sin resultados, una ficha
 * despublicada— las atiende `app/(publico)/not-found.tsx`, que conserva la
 * cabecera y el pie del sitio.
 */
export default function RootNotFound() {
  return (
    <Puerta
      kicker="Error 404"
      titulo="Esta página no existe"
      lede="Puede que el enlace sea antiguo o que la dirección esté mal escrita."
    >
      <ul className="space-y-3">
        <li>
          <EnlaceIrPublico href="/" className="text-base">
            Ir a la portada
          </EnlaceIrPublico>
        </li>
        <li>
          <EnlaceIrPublico href="/licitaciones" className="text-base">
            Licitaciones por comunidad autónoma
          </EnlaceIrPublico>
        </li>
      </ul>
    </Puerta>
  );
}
