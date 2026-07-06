# CA raíz para TLS verificado a Supabase (`sslmode=verify-full`)

`sslmode=require` cifra la conexión pero **no valida el certificado del
servidor** → un atacante capaz de interponerse (MITM) puede capturar la
credencial embebida en `DATABASE_URL`. `verify-full` valida cadena + hostname y
cierra ese vector, pero necesita la **CA raíz de Supabase**.

## Cómo obtenerla

No se versiona aquí un certificado fabricado. Descargá el real:

1. Supabase Dashboard → tu proyecto → **Database → SSL Configuration** →
   *Download certificate* (fichero tipo `prod-ca-2021.crt`).
2. Colocalo en este directorio: `db/certs/prod-ca-2021.crt`.
3. Apuntá la variable de entorno:
   ```
   DATABASE_SSL_ROOT_CERT=db/certs/prod-ca-2021.crt
   DATABASE_URL=postgresql://<user>:<pass>@<host>:5432/<db>?sslmode=verify-full
   ```

El certificado de la CA es **público** (no es un secreto); podés commitearlo o
montarlo como fichero en el despliegue. `db/connection.py` lo pasa como
`sslrootcert` a cada conexión del pool cuando `DATABASE_SSL_ROOT_CERT` está
definida.
