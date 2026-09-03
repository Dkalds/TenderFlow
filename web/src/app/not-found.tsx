import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { FileQuestion } from "lucide-react";
import Link from "next/link";

/**
 * 404 de última instancia: URLs que no caen en ningún grupo de rutas.
 *
 * Quién llega aquí, comprobado en local: **sólo alguien con sesión**. Una ruta
 * desconocida sin cookie no llega a renderizar nada — el proxy la trata como
 * privada por defecto y devuelve un 307 a `/login` (ver `proxy.ts` y su test).
 * Las 404 que sí ve un visitante anónimo son las de la superficie pública, y de
 * esas se ocupa `app/(publico)/not-found.tsx`, que conserva cabecera y pie.
 *
 * Aun así el botón deja de llevar a `/resumen`: la portada sirve a los dos
 * públicos —a quien tiene sesión el proxy lo reenvía él mismo a su dashboard—
 * y no da por hecho que quien se topa con un 404 venga de dentro.
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
