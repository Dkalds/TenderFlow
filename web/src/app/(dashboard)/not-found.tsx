import Link from "next/link";
import { Button } from "@/components/ui/button";

/**
 * 404 dentro de la consola: un `notFound()` de una pantalla del dashboard (una
 * oportunidad o una cuenta que ya no existe) o una dirección mal escrita con
 * sesión abierta. El marco sigue en pie, así que basta con decir qué pasó y
 * ofrecer una salida.
 *
 * `h2` y no `h1`: `DashboardShell` ya pinta el `h1` de la página. Sin tarjeta ni
 * icono de interrogación: era el bloque de 404 por defecto de las plantillas,
 * con «Página no encontrada» dentro de una `Card` centrada.
 */
export default function DashboardNotFound() {
  return (
    <section className="mx-auto w-full max-w-2xl px-6 py-16">
      <h2 className="font-display text-tf-title text-balance">Esta pantalla no existe</h2>
      <p className="text-tf-body text-muted-foreground mt-2 max-w-[58ch]">
        Puede que el enlace sea antiguo, que lo que abría se haya borrado o que la dirección esté mal escrita.
      </p>
      <Button asChild size="sm" className="mt-5">
        <Link href="/resumen">Ir a Resumen</Link>
      </Button>
    </section>
  );
}
