#!/bin/sh
# Entrypoint de Dockerfile.alertmanager — expande la configuración y arranca.
#
# La configuración lleva credenciales SMTP, así que no puede hornearse en una
# capa de imagen (quedaría en el registro y en `docker history`). Se copia como
# plantilla con `${VARIABLE}` y aquí se expande contra el entorno que inyecta
# Render. Alertmanager no interpola variables de entorno por su cuenta: sin este
# paso, `smtp_auth_password` valdría literalmente la cadena
# "${ALERT_SMTP_PASSWORD}" y la autenticación fallaría en cada envío.
set -eu

: "${ALERT_SMTP_HOST:=smtp.gmail.com}"
: "${ALERT_SMTP_PORT:=587}"
: "${ALERT_SMTP_USER:=}"
: "${ALERT_SMTP_PASSWORD:=}"
: "${ALERT_EMAIL_TO:=}"
# El webhook es opcional por diseño (segundo canal). Vacío, se apunta a un
# destino local inexistente: Alertmanager registra el fallo de entrega de ESE
# receptor y sigue sirviendo el de email. Dejar la URL literalmente vacía haría
# fallar la validación de la configuración al arrancar, y un canal opcional que
# impide arrancar deja sin el canal obligatorio.
: "${ALERTMANAGER_WEBHOOK_URL:=http://127.0.0.1:9099/alertmanager-webhook-no-configurado}"

PLANTILLA=/etc/alertmanager/alertmanager.tmpl.yml
RENDERIZADA=/etc/alertmanager/rendered/alertmanager.yml

# Lista explícita de variables: `envsubst` sin argumentos sustituiría TODO lo
# que parezca `${...}`, incluidas las plantillas Go de los receptores
# (`{{ .Labels.severity }}` no, pero `${...}` dentro de un template sí), y
# vaciaría cualquier `${}` que Alertmanager espere recibir literal.
envsubst '${ALERT_SMTP_HOST} ${ALERT_SMTP_PORT} ${ALERT_SMTP_USER} ${ALERT_SMTP_PASSWORD} ${ALERT_EMAIL_TO} ${ALERTMANAGER_WEBHOOK_URL}' \
    < "$PLANTILLA" > "$RENDERIZADA"

if [ -z "$ALERT_EMAIL_TO" ] || [ -z "$ALERT_SMTP_USER" ] || [ -z "$ALERT_SMTP_PASSWORD" ]; then
    # Ruidoso a propósito: un Alertmanager arrancado sin credenciales es
    # exactamente el fallo silencioso que este servicio existe para terminar.
    echo "ALERTMANAGER: faltan ALERT_EMAIL_TO/ALERT_SMTP_USER/ALERT_SMTP_PASSWORD." >&2
    echo "ALERTMANAGER: las alertas se agruparán y enrutarán, pero el envío de email fallará." >&2
fi

# `exec` para que Alertmanager sea PID 1 y reciba SIGTERM en el redeploy.
exec /bin/alertmanager \
    --config.file="$RENDERIZADA" \
    --storage.path=/alertmanager \
    --web.listen-address="0.0.0.0:${PORT:-9093}" \
    "$@"
