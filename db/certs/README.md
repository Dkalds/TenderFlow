# CA raíz para TLS verificado a Supabase (`sslmode=verify-full`)

`sslmode=require` cifra la conexión pero **no valida el certificado del
servidor** → un atacante capaz de interponerse (MITM) puede capturar la
credencial embebida en `DATABASE_URL`. `verify-full` valida cadena + hostname y
cierra ese vector, pero necesita la **CA raíz de Supabase**.

## Cómo obtenerla

Ya está commiteado en este directorio: `prod-ca-2021.crt` (descargado desde
Supabase Dashboard → tu proyecto → **Database → SSL Configuration** → *Download
certificate*, verificado con `openssl x509 -noout -subject -issuer -dates`:
subject/issuer = `Supabase Root 2021 CA`, válido hasta 2031-04-26).

Si tu proyecto de Supabase usa otra CA (proyectos más nuevos, o rotación de CA),
repetí la descarga y reemplazá el fichero.

Variables de entorno (Render u otro despliegue):
```
DATABASE_SSL_ROOT_CERT=/app/db/certs/prod-ca-2021.crt
DATABASE_URL=postgresql://<user>:<pass>@<host>:5432/<db>?sslmode=verify-full
```

`/app` es el `WORKDIR` de la imagen Docker (`docker/Dockerfile.api`) — ajustá la
ruta si el despliegue usa otro directorio de trabajo.

El certificado de la CA es **público** (no es un secreto); podés commitearlo o
montarlo como fichero en el despliegue. `db/connection.py` lo pasa como
`sslrootcert` a cada conexión del pool cuando `DATABASE_SSL_ROOT_CERT` está
definida.
