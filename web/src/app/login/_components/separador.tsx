/**
 * Regla horizontal con una etiqueta centrada. La usan los dos cortes de la
 * tarjeta de acceso: el que separa OAuth de la cuenta local y el del bloque de
 * desarrollo. Estaba escrito dos veces con el mismo marcado.
 */

export function Separador({ etiqueta }: { etiqueta: string }) {
  return (
    <div className="relative my-6">
      <div className="absolute inset-0 flex items-center">
        <div className="border-border w-full border-t" />
      </div>
      <div className="relative flex justify-center text-xs uppercase">
        <span className="bg-card text-muted-foreground px-2">{etiqueta}</span>
      </div>
    </div>
  );
}
