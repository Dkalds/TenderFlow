# Registro de actividades de tratamiento

**Responsable del tratamiento:** el declarado en `NEXT_PUBLIC_LEGAL_RESPONSABLE`
(razón social), `NEXT_PUBLIC_LEGAL_NIF` y `NEXT_PUBLIC_LEGAL_DOMICILIO`, que
`/aviso-legal` publica. **Mientras esas tres variables no lleven datos reales,
este registro está incompleto**: `web/src/lib/legal-placeholder.ts` rechaza los
valores de relleno y el build de producción falla, que es el comportamiento
querido.

**Última revisión: 2026-09-06.**

Artículo 30 del RGPD. Este documento no es la política de privacidad —esa es
[`/aviso-legal`](https://tenderflow.app/aviso-legal), escrita para el
visitante— sino el registro interno que hay que poder enseñar.

---

## 1. Por qué existe este documento

Hasta 2026-09 la plataforma trataba datos personales —cuentas, solicitudes de
acceso, logs de acceso, comentarios de equipo— sin ningún registro escrito de
qué se trata, con qué base jurídica y durante cuánto tiempo. Los plazos existían
(en `scheduler/retention.py`) pero no estaban publicados, y las categorías de
datos había que deducirlas leyendo el esquema.

---

## 2. Actividades de tratamiento

### 2.1 Cuentas de usuario y autenticación

| | |
|---|---|
| **Finalidad** | Prestar el servicio: identificar a la persona usuaria, mantener su sesión y su organización. |
| **Base jurídica** | Ejecución de contrato (art. 6.1.b RGPD). |
| **Categorías de interesados** | Personas usuarias registradas. |
| **Categorías de datos** | Email, nombre, hash de contraseña (argon2/bcrypt), proveedor OAuth, secreto TOTP cifrado, marcas temporales. |
| **Destinatarios** | Proveedor de base de datos (Supabase) y de cómputo (Render), ambos como encargados. Proveedores OIDC (Google; Microsoft cuando exista) como responsables independientes del lado de su identidad. |
| **Transferencias internacionales** | Sí, según la región del proveedor. Ver §4. |
| **Plazo** | Mientras la cuenta exista. El borrado autoservicio (`DELETE /me`) anonimiza; `access_log` se purga a los 180 días. |
| **Medidas de seguridad** | Cifrado en tránsito y en reposo, CSRF firmado con HMAC, scopes por API key, rate limiting, auditoría encadenada por SHA-256. |

### 2.2 Solicitudes de acceso desde la superficie pública

| | |
|---|---|
| **Finalidad** | Atender la petición de acceso a la plataforma. |
| **Base jurídica** | Consentimiento explícito en el momento de la recogida (art. 6.1.a). |
| **Categorías de interesados** | Visitantes que rellenan el formulario. |
| **Categorías de datos** | Email y el texto que la persona escriba. |
| **Plazo** | **24 meses**, publicado en el aviso legal y aplicado por `retention_cleanup`. Es el único plazo que además es una promesa hecha al visitante: ver [SECURITY.md](../SECURITY.md#retención-de-datos). |
| **Derechos** | Acceso, rectificación, supresión, oposición y portabilidad por el buzón de `/aviso-legal`. |

### 2.3 Colaboración de equipo (dato corporativo)

| | |
|---|---|
| **Finalidad** | Que una organización trabaje sus oportunidades: seguimiento, comentarios, tareas, decisiones. |
| **Base jurídica** | Ejecución de contrato con la organización cliente. |
| **Categorías de datos** | Identificador de la persona autora, contenido que ella escribe, marcas temporales. |
| **Quién es el responsable** | **La organización cliente**, no la plataforma. La plataforma es **encargada** (ver el [anexo de encargo](anexo-encargo-tratamiento.md)). |
| **Plazo** | Mientras la organización exista. Su borrado se lleva el dato corporativo; el dato personal de cada miembro sobrevive con ellos, según [ADR-030 §D](../adr/ADR-030-identidad-user-id-y-oidc.md). |

### 2.4 Telemetría de producto y errores de cliente

| | |
|---|---|
| **Finalidad** | Detectar regresiones y entender el uso agregado. |
| **Base jurídica** | Interés legítimo (art. 6.1.f): mantener el servicio en funcionamiento. |
| **Categorías de datos** | Ruta sin query string, mensaje de error truncado, versión de build, huella sin identificador. **No** se registran IP, email ni contenido de formularios. |
| **Plazo** | 30 días (`RETENTION_CLIENT_ERRORS_DAYS`). |
| **Nota** | La decisión de no usar un SDK externo (D26 del plan complementario) es también una decisión de privacidad: sin SDK no hay un tercero recibiendo trazas del navegador. |

### 2.5 Datos de contratación pública (sin dato personal por diseño)

| | |
|---|---|
| **Finalidad** | El producto: publicar y analizar licitaciones. |
| **Base jurídica** | No aplica en general — es información pública reutilizable. |
| **Excepción** | Un adjudicatario **persona física** (autónomo) es dato personal, y su NIF lo identifica. La superficie anónima no lo expone: lo verifica `make check-public-surface` con `--strict`. |
| **Plazo** | Sin purga: `licitaciones` y `adjudicaciones` son el dato que el producto existe para conservar. |

---

## 3. Encargados del tratamiento

| Encargado | Qué trata | Instrumento |
|---|---|---|
| Supabase | Base de datos (todas las categorías) | DPA del proveedor |
| Render | Cómputo, logs de aplicación | DPA del proveedor |
| Vercel | Frontend, logs de acceso | DPA del proveedor |
| Proveedor LLM | El texto de las preguntas de `/ask` y el contexto del pliego | DPA del proveedor; **el presupuesto y el modo `enforce` acotan el volumen**, no el tratamiento |

**Pendiente del propietario:** archivar el DPA firmado de cada uno y anotar aquí
su fecha. Un encargado sin DPA archivado es un incumplimiento aunque el
proveedor lo ofrezca en su web.

---

## 4. Transferencias internacionales

Los proveedores de §3 pueden tratar datos fuera del EEE según la región
contratada. Los servicios declarados en `render.yaml` usan `region: frankfurt`.

**Pendiente del propietario:** confirmar la región de Supabase y del proveedor
LLM, y anotar el mecanismo de transferencia (cláusulas contractuales tipo o
decisión de adecuación) de los que estén fuera del EEE.

---

## 5. Qué falta para que este registro esté completo

Estas casillas son acción del propietario y **no** las puede rellenar un agente:

- [ ] Razón social, NIF y domicilio reales en `NEXT_PUBLIC_LEGAL_*`.
- [ ] Buzón de ejercicio de derechos operativo.
- [ ] DPA archivado y fechado por cada encargado de §3.
- [ ] Región y mecanismo de transferencia de §4.
- [ ] Delegado de protección de datos: decidir si procede designarlo y anotarlo.

Mientras haya casillas sin marcar, este documento describe el tratamiento pero
no acredita el cumplimiento. Decirlo aquí es preferible a que parezca completo.
