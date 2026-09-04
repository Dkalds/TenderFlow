import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { FileQuestion } from "lucide-react";
import Link from "next/link";

/**
 * 404 de última instancia: URLs que no caen en ningún grupo de rutas.
 *
 * Quién llega aquí. Una ruta desconocida **sin relación con nada público** la
 * corta antes el proxy, que la trata como privada y devuelve un 307 a `/login`
 * (ver `proxy.ts` y su test). Pero también aterrizan aquí las URLs sin ruta que
 * sí cuelgan de un prefijo público —una ficha con un segmento de más, un enlace
 * viejo de un buscador— y ésas las ve un visitante anónimo. Por eso el botón
 * lleva a la portada y no a `/resumen`, que para él es otro muro de login.
 *
 * Las 404 de las rutas que sí existen —un hub sin resultados, una ficha
 * despublicada— las atiende `app/(publico)/not-found.tsx`, que conserva la
 * cabecera y el pie del sitio.
 */
export default function RootNotFound() {
  return (
    <div className="flex items-center justify-center min-h-screen bg-background">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <FileQuestion className="h-5 w-5" />
            Página no encontrada
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-sm text-muted-foreground">
            La página que buscas no existe o ha sido movida.
          </p>
          <Button asChild>
            <Link href="/">Ir a la portada</Link>
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}
