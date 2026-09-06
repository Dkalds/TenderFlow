# Anexo de encargo del tratamiento (clientes B2B)

**Estado: borrador técnico. Requiere revisión jurídica del propietario antes de
ofrecerlo a un cliente.** Lo que sigue describe con exactitud lo que la
plataforma hace; no sustituye a un contrato revisado por quien pueda firmarlo.

**Última revisión: 2026-09-06.**

Artículo 28 del RGPD. Se anexa al contrato de servicio cuando el cliente es una
organización que sube o genera datos personales dentro de la plataforma.

---

## 1. Reparto de papeles

Es la parte que más se equivoca en la práctica, y la plataforma tiene dos
papeles a la vez según el dato:

| Dato | Responsable | Encargado |
|---|---|---|
| Cuentas, autenticación, facturación | **La plataforma** | Sus proveedores de infraestructura |
| Oportunidades, comentarios, tareas, notas, capacidades de la organización | **El cliente** | **La plataforma** |
| Adjuntos que el cliente sube | **El cliente** | **La plataforma** |
| Datos de contratación pública ingeridos de fuentes oficiales | — (información pública) | — |

La regla que separa las dos primeras filas está en
[ADR-030 §D](../adr/ADR-030-identidad-user-id-y-oidc.md): dato personal frente a
dato corporativo, con quién lo posee y qué pasa al borrar cada cosa.

---

## 2. Objeto, duración y naturaleza

- **Objeto.** Alojar y procesar el contenido que el cliente genera al usar la
  plataforma para trabajar sus oportunidades.
- **Duración.** La del contrato de servicio.
- **Naturaleza y finalidad.** Almacenamiento, consulta, análisis y
  notificación, exclusivamente para prestar el servicio contratado.
- **Categorías de interesados.** Personas empleadas del cliente con cuenta en la
  plataforma; personas de contacto que el cliente registre.
- **Categorías de datos.** Identificadores de persona usuaria, contenido escrito
  por ella y marcas temporales. Los adjuntos pueden contener lo que el cliente
  suba, y esa es su decisión.

---

## 3. Obligaciones de la plataforma como encargada

1. **Tratar solo por instrucción documentada** del cliente. El uso del servicio
   es la instrucción; cualquier otro tratamiento requiere acuerdo escrito.
2. **No entrenar modelos con el contenido del cliente.** Los modelos de la
   plataforma se entrenan con datos de contratación pública, nunca con
   oportunidades, comentarios ni adjuntos de una organización.
3. **Confidencialidad** de quien acceda a los datos.
4. **Medidas del artículo 32**, detalladas en §4.
5. **Subencargados**: los de
   [registro-tratamientos.md §3](registro-tratamientos.md#3-encargados-del-tratamiento).
   Un subencargado nuevo se comunica con antelación razonable y el cliente puede
   oponerse.
6. **Asistencia** al cliente en el ejercicio de derechos de los interesados y en
   las evaluaciones de impacto que le correspondan.
7. **Notificación de brecha** sin dilación indebida desde que la plataforma tenga
   constancia, con lo que se sepa en ese momento — no se espera a tener el
   informe completo para avisar.
8. **Devolución o supresión al terminar**, a elección del cliente.

---

## 4. Medidas técnicas y organizativas

Estas son las que existen hoy, no las que se querría tener:

| Medida | Cómo está implementada |
|---|---|
| Aislamiento entre clientes | `organization_id` en toda escritura corporativa, con tests de aislamiento en las dos direcciones |
| Autenticación | Argon2/bcrypt, TOTP con secreto cifrado, CSRF firmado con HMAC |
| Autorización de máquina | Scopes por API key, resueltos en un solo sitio (`api/scopes.py`) y publicados en `docs/api-design.md` |
| Cifrado | En tránsito (TLS) y en reposo (proveedor). Secretos de webhook cifrados en BD |
| Trazabilidad | `audit_log` encadenado por SHA-256; se purga por el extremo antiguo, nunca por el medio |
| Retención | Plazos publicados y aplicados a diario: [SECURITY.md](../SECURITY.md#retención-de-datos) |
| Gestión de vulnerabilidades | Plazos por severidad: [SECURITY.md](../SECURITY.md#política-de-vulnerabilidades) |
| Enlaces de descarga | Firmados y con caducidad; nunca URL pública ([ADR-029](../adr/ADR-029-almacen-de-objetos.md)) |

**Lo que hoy no hay, y conviene decirlo antes de que lo pregunte un cliente:**

- **Sin cifrado por cliente con clave propia** (BYOK).
- **Sin residencia de datos elegible por cliente**: la región es la del
  despliegue, común a todos.
- **Sin SSO SAML ni aprovisionamiento SCIM.** Solo OIDC — decisión explícita del
  plan v2, revisable cuando una organización lo pida.
- **Backup y restore drill fuera del alcance** del plan vigente por decisión del
  mantenedor. Un cliente que exija RPO/RTO contractual necesita que eso se
  aborde primero.

---

## 5. Devolución y supresión

Al terminar el contrato, a elección del cliente:

- **Devolución**: export de sus datos en formato estructurado.
- **Supresión**: borrado de la organización, que se lleva su dato corporativo.
  El dato personal de cada miembro sobrevive con su cuenta personal
  (ADR-030 §D), y cada persona puede borrarlo por su cuenta con `DELETE /me`.

En ambos casos, `audit_log` conserva el registro de la acción con el actor
anonimizado: es el mínimo necesario para acreditar que la supresión ocurrió.

---

## 6. Casillas pendientes del propietario

- [ ] Revisión jurídica del texto completo.
- [ ] Identificación de las partes (la plataforma como encargada) con datos reales.
- [ ] Régimen de responsabilidad y de auditoría del cliente.
- [ ] Plazo concreto para la notificación de brecha, si se quiere fijar uno más
      estricto que «sin dilación indebida».
