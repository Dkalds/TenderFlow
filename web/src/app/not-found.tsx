import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { FileQuestion } from "lucide-react";
import Link from "next/link";

/**
 * 404 de última instancia: URLs que no caen en ningún grupo de rutas.
 *
 * El botón llevaba a `/resumen`, y eso convertía un 404 en un muro para quien
 * no tiene sesión —que es la mayoría de quien llega aquí desde fuera—: el proxy
 * responde a esa ruta con un 307 a `/login`. La portada sirve a los dos
 * públicos, porque a quien sí tiene sesión el proxy lo reenvía él mismo a su
 * dashboard. Las 404 de la superficie pública las atiende
 * `app/(publico)/not-found.tsx`, que además conserva cabecera y pie.
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
