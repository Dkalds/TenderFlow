/**
 * Regla horizontal con una etiqueta centrada. La usan los dos cortes del panel
 * de acceso: el que separa OAuth del correo y la contraseña, y el del bloque de
 * desarrollo. Estaba escrito dos veces con el mismo marcado.
 *
 * La etiqueta va en frase: «o con correo y contraseña» es una frase con verbo
 * implícito, y en versal se leía como un rótulo gritado.
 */

export function Separador({ etiqueta }: { etiqueta: string }) {
  return (
    <div className="relative my-6">
      <div className="absolute inset-0 flex items-center">
        <div className="border-border w-full border-t" />
      </div>
      <div className="text-tf-meta relative flex justify-center">
        <span className="bg-card text-muted-foreground px-2">{etiqueta}</span>
      </div>
    </div>
  );
}
