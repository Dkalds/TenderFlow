# Product

<!-- impeccable:product-schema 1 -->

Verdad de producto de TenderFlow para el trabajo de diseño. El lenguaje visual
vive en [DESIGN.md](DESIGN.md); las decisiones del dueño y las reglas de la casa,
en [docs/UX_AUDIT.md](docs/UX_AUDIT.md); los recorridos, en
[docs/casos-de-uso.md](docs/casos-de-uso.md). Si algo de aquí contradice a esas
fuentes, se corrige aquí en el mismo cambio.

## Platform

web

## Users

**Usuario principal: el responsable de ofertas de un partner tecnológico** que
vende SAP, Salesforce, Microsoft o ServiceNow a la administración pública
española. Cada mañana abre la bandeja de concursos abiertos, ordenada por lo que
encaja con su empresa, y decide dónde pujar, a qué precio y contra quién. Es
quien compra el producto y para quien se diseña primero.

Usuarios secundarios dentro de la misma organización (docs/casos-de-uso.md):
comercial y preventa (trabajan cada oportunidad), responsable de cuenta,
dirección (lee el resultado agregado), propietaria/administradora de la
organización (equipo, accesos, claves) e integrador (API, webhooks, RSS). Fuera
del cliente: el administrador de plataforma (`/ops`) y el visitante anónimo de la
superficie pública.

Fuera de público: quien vende obra pública, sanidad o suministros generales
(«esto no te sirve», `web/src/app/(publico)/_content/landing.ts`).

## Product Purpose

Inteligencia de licitaciones TI del sector público español: «dónde pujar, a qué
precio, contra quién». Ingiere los anuncios oficiales, se queda solo con los
contratos tecnológicos y los convierte en una bandeja diaria priorizada, con el
contexto de mercado (bajas de referencia, competidores, renovaciones) que hace
falta para decidir una oferta.

Éxito: el responsable de ofertas decide cada mañana qué concursos trabajar sin
salir a buscarlos, y cada cifra en la que se apoya dice de dónde sale.

## Positioning

**Confianza en el dato** («TenderFlow vende confianza en el dato»,
docs/UX_AUDIT.md). Cada número dice de dónde sale y cuándo no hay bastante para
decirlo; las estimaciones se rotulan como «estimación», «parcial» o «sin datos
suficientes». El producto no devuelve probabilidad de ganar, y lo dice.

Es un radar tecnológico, no un censo de toda la contratación pública, y no
sustituye a la fuente oficial: enlaza a ella.

Alternativa real con la que se compara: buscar a mano en PLACSP, con sus
alertas por email. No hay un competidor de
referencia nombrado; el trabajo de diseño no inventa uno ni tablas comparativas.

## Operating Context

- Ritual diario: triaje de la bandeja (Radar) por la mañana; el trabajo de cada
  oportunidad sigue en la ficha y el pipeline (matriz Go/No-Go, tareas, adjuntos,
  simulador de precio).
- Fuentes: PLACSP (feed ATOM cada 4 h, ZIP mensual de respaldo), TED, Galicia y
  Euskadi activas; PSCP y TACRC solo cuando su fuente está configurada. Un mismo
  contrato puede llegar de varias fuentes y se cuenta una vez (ADR-026).
- Documentos: los pliegos son materia prima; el Investigador responde citándolos.
- Escritorio para el trabajo completo. Móvil cubre consulta y triaje (Radar,
  ficha, watchlist, agenda), no la edición de matrices.
- Salidas hacia otras herramientas: alertas y resúmenes por correo, campana,
  webhooks, RSS, exportación CSV, API REST con claves y un servidor MCP de solo
  lectura.

## Capabilities and Constraints

- Filtro tecnológico: 13 familias de fabricante y 12 categorías TI, en
  castellano, catalán, euskera y gallego, más CPV 48 y 72.
- Score de Radar en seis dimensiones con pesos ajustables y cuatro bandas
  (Caliente, Atractiva, Tibia, Descarte); baja de referencia por segmento; cuota
  de mercado y competencia; renovaciones con riesgo de cambio de proveedor;
  reglas de watchlist con previsualización; Investigador (RAG sobre pliegos);
  caducidad de documentación administrativa; páginas públicas indexables por
  CCAA, órgano y CPV.
- **Acceso B2B por invitación**: no hay alta self-service, ni pasarela de pago,
  ni planes, ni precio publicado. Se solicita acceso, un operador habilita el
  email o el dominio, y se entra con contraseña (alta con correo de activación)
  o con Google. Microsoft es un tercer método que solo aparece donde está
  configurado `OAUTH_MICROSOFT_CLIENT_ID` (D17); sin él, el backend responde 501
  y el botón no se muestra.
- Roles de organización: propietaria, administradora, miembro y lector (solo
  lectura); además, administrador de plataforma.
- El frontend solo consume la API tipada; no hay atajos a la base de datos
  (AGENTS.md §3.8).
- Terminología fija (D8): se mantienen «Score», «Pipeline», «Watchlist» y
  «Go/No-Go»; se traducen sync, win rate, dashboard, owner/admin, lead time,
  secret y API keys.
- Dominio propio: pendiente, sin elegir. El sitio vive en `*.vercel.app`; ningún
  trabajo de diseño cita un dominio ni un buzón de ese dominio.
- Identidad societaria: la sociedad está pendiente de constituir. La superficie
  pública no puede mostrar razón social, NIF ni domicilio, y no se rellenan con
  marcadores; las variables de entorno que los publicarán siguen vacías.
- Portada del día (F27): descartada por decisión, no pendiente
  (docs/UX_AUDIT.md).

## Brand Commitments

- Nombre: TenderFlow. No encabeza los títulos SEO de la superficie pública.
  Monograma «TF» con fuente única en `web/src/lib/marca.ts`
  (`web/src/components/layout/tenderflow-logo.tsx`, `web/public/favicon.svg`).
- Voz: solo castellano peninsular, con tuteo; nada de voseo ni vosotros. La
  interfaz no narra su implementación. Lo verifica
  `web/src/__tests__/voz-de-la-interfaz.test.ts`.
- La IA se nombra, no se adorna (D5).
- Los errores dan un mensaje humano, el detalle técnico plegado y «Reintentar»,
  con un solo aviso por fallo (D6).
- La landing habla con una sola voz y tiene presupuesto de palabras.

## Evidence on Hand

- Datos reales en vivo: la landing muestra anuncios reales y cifras del corpus
  leídas de la API; las capturas salen de `npm run capturas:landing`.
- **Ausencias que no se fabrican**: no hay clientes nombrados, testimonios,
  métricas de clientes, cifras de ahorro, benchmarks ni precios. Un «desde X €» o
  un logo de cliente sería inventarse el dato.
- Costes facturados: por medir (docs/COSTES.md).

## Product Principles

1. **El dato dice de dónde sale.** Toda cifra lleva su fuente y su grado de
   certeza; donde no hay bastante, se dice en vez de rellenar.
2. **Primero la decisión de la mañana.** El responsable de ofertas tiene que
   saber qué trabajar hoy antes que cualquier otra cosa; lo demás es contexto
   para esa decisión.
3. **Acotado a TI.** Un radar para quien vende tecnología a la administración, no
   un buscador de toda la contratación pública.
4. **Superficie con datos reales o no hay superficie.** Nada de placeholders ni
   cifras fabricadas; antes de añadir una pantalla se comprueba que ninguna
   existente cubre el caso (AGENTS.md §0).
5. **La fuente oficial manda.** TenderFlow ordena y explica; el anuncio oficial
   es la referencia y siempre está a un enlace.

## Accessibility & Inclusion

Objetivo: **WCAG 2.2 AA** en la consola y en la superficie pública. Ya en vigor:
contraste de tokens medido por test
(`web/src/lib/__tests__/contraste-tokens.test.ts`), jsx-a11y en error, foco
visible, respeto de reduced-motion, reduced-transparency y contraste, regiones
aria-live, capa accesible en gráficos y skip link.
