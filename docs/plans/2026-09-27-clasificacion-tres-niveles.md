# Clasificación de licitaciones en tres niveles, con etiquetas que no salgan de las reglas

**Estado:** propuesta, 2026-09-27. Pendiente de revisión del propietario (§7).
**Alcance:** qué entra en el corpus como TI, con qué familia y de qué fabricante,
y cómo se entrenan, evalúan y sirven los modelos que lo deciden. Fuera de
alcance: la ficha del pliego, los modelos de baja y de retención.

## 1. Por qué (medido el 2026-09-27)

- **Las etiquetas son circulares.** El binario «SAP» se entrena con «alguna
  keyword de cualquier tecnología» (`scraper/ml_training.py`), y el
  multi-tecnología de hoy tuvo 7.010 etiquetas de keywords frente a 39
  humanas y 260 del LLM. Resultado:
  - Fabricantes: F1 de 0,93-0,995, es decir, imitan el regex.
  - Categorías: F1 de 0,0-0,46.
  - El reentrenamiento del binario de hoy quedó rechazado con
    `recall_no_keyword = 0`: no encuentra nada que las keywords no encuentren.
- **El modelo servido no discrimina donde se usa.**
  - Es el artefacto de mayo, sin fila en `model_versions`.
  - El rescate de ingesta solo puntúa CPV 48/72 sin keyword, y el modelo lleva
    un token `CPV_TI` que en esa población vale siempre lo mismo.
  - En PSCP deja por encima del umbral el 99,5 % de lo que puntúa.
- **La taxonomía es plana y centrada en fabricantes.**
  - Tras la purga, 46k de 60k filas (77 %) están en el corpus solo por CPV, sin
    familia.
  - En una muestra revisada a mano de 40 filas de PSCP de ese grupo, ~31 eran TI
    claro (desarrollo a medida, hosting, licencias de SUSE, Qlik o Alfresco) y 5
    no lo eran (revistas de Wiley, un acto público, la revisión de un texto
    legal).
- **El LLM no puede decir «es TI pero no encaja».** Recibía solo los nombres de
  las 22 etiquetas. A TI genérica respondía `__no_signal__`, y eso entrenaba
  como negativo por encima de las keywords.
- **No hay evaluación que decida nada.**
  - El golden de SAP tiene 27 ejemplos y el umbral sale de 10.
  - El golden multi-tecnología tiene 23 ejemplos inventados.
  - Validación cruzada: F1 0,94. Test temporal: 0,52.
- **No hay bucle humano.** Hay 59 feedbacks humanos desde mayo, cero descartes
  en el Radar y 8 pursuits.

Ya hecho (rama `claude/clasificacion-licitaciones-mejora-5d1f43`, 2026-09-27):

- El matcher casa sin tildes, en plural y devolviendo todas las keywords
  canónicas.
- La puerta de keywords ambiguas decide también en PLACSP y el `summary` deja
  de contar.
- Con sesión, solo un admin escribe etiquetas.
- El LLM recibe las definiciones de cada etiqueta y se comprueba su evidencia.
- El «sin señal» del LLM ya no pisa a las keywords.

Este plan cubre el resto.

## 2. Qué se clasifica: tres niveles

| Nivel | Pregunta | Forma | Quién decide |
|---|---|---|---|
| 1 | ¿Es TI? | binario, con banda «dudoso» | reglas → modelo → LLM → humano |
| 2 | ¿Qué familia? | multi-etiqueta sobre las categorías | modelo (+ LLM en la banda dudosa) |
| 3 | ¿Qué fabricante? | extracción con alias | reglas (diccionario) |

Hoy fabricantes y categorías van en la misma lista, y por eso unos «funcionan»
(el nombre del fabricante está en el texto) y las otras no (son conceptos).

- **Los fabricantes dejan de entrenarse.** Se detectan por diccionario, que ya
  acierta, y el tier `rules` existente basta.
- **Crecer el diccionario sin desplegar.** Los fabricantes que el LLM nombra y
  no están en él (Qlik, Alfresco, SUSE, EasyVista…) entran como propuesta en
  `tecnologias_keywords`, que existe y está vacía en producción, y un admin los
  aprueba desde `/ops`.
- **Compatibilidad.** Los códigos se conservan en el mismo campo `tecnologia`
  (API, filtros, ámbito de organización y avisos los usan), y el tipo
  (`TECH_LABEL_TIPO`) distingue los niveles 2 y 3.

## 3. Etiquetas independientes (el cambio con más palanca)

1. **Prompt v3 del LLM** (el v2 es el de hoy, con definiciones). Añade:
   - un campo `es_ti` separado de las familias;
   - `fabricantes` como texto libre;
   - `confianza`;
   - la evidencia verificada contra el texto.

   `es_ti = false` se guarda como el sentinel nuevo `__no_ti__` en
   `licitacion_tecnologia_pliego`, sin migración.
2. **Muestra estratificada** de 4.000 licitaciones:
   - estratos: fuente × CPV (48, 72, otros) × idioma × si tienen keyword ×
     banda del modelo actual;
   - se lanza con el drenado manual del job existente;
   - coste estimado: ~2 $ a la tarifa actual (0,07 $ por cada 200).
3. **Revisión humana de ~500** en `/ops?vista=etiquetado`:
   - La cola deja de ordenarse por la incertidumbre del modelo actual, que es
     constante, y pasa a ordenarse por **desacuerdo** (reglas ↔ LLM ↔ modelo).
   - El formulario pide `es_ti`, familias y fabricantes.
   - `ml_feedback.relevante` pasa a significar `es_ti`, y solo eso. Las 59
     filas antiguas, cuyo `relevante` significaba «es SAP», se marcan como
     legado y se vuelven a revisar en la cola.
   - Confirmar o corregir la propuesta del LLM son unas 4 horas.
4. **Golden set real:** `tests/fixtures/golden_ti.jsonl`.
   - Campos: fuente, fecha, `etiquetado_por` y un reparto temporal fijo
     (holdout = el 50 % más reciente).
   - Incluye casos de «tiene keyword pero no es TI», que hoy no existen.
   - Sustituye al golden de SAP como gate de promoción. El de SAP se queda como
     test de regresión del nivel 3.
5. **Regla de uso:**
   - Las etiquetas del LLM solo entrenan si su acuerdo con los humanos en el
     golden es ≥ 0,90 en `es_ti` y ≥ 0,80 de F1 por familia. Si no, se afina el
     prompt antes de seguir.
   - Una fila sin etiqueta **no** es un negativo.

## 4. Los modelos

**Nivel 1: ¿es TI?**

- **Qué se compara.** Tres candidatos, y gana el mejor PR-AUC en el holdout
  temporal, con intervalo por bootstrap:
  - A: TF-IDF de palabras y de caracteres + regresión logística;
  - B: embeddings `paraphrase-multilingual-MiniLM-L12-v2` (ya en el repo para
    RAG) + regresión logística;
  - A+B.

  Si hay empate, gana el más simple.
- **Features:**
  - título + descripción real; en PLACSP no se usa el `summary`, que es
    metadatos;
  - CPV como tokens jerárquicos (2, 3 y 4 cifras), sin el `CPV_TI` duplicado
    que satura;
  - idioma.
- **Datos y calibración:**
  - Se entrena con las filas etiquetadas (LLM + humanas) de la población que se
    puntúa, que tras la purga es el corpus entero.
  - No se submuestrean negativos. La calibración es isotónica sobre un pliegue
    temporal, con la prevalencia real, y al final se reentrena con todos los
    datos.
- **Salida.** Dos umbrales dan tres bandas: TI (precisión ≥ 0,95), no TI (se
  pierde como mucho un 5 % de recall) y dudoso, que va al LLM y después a la
  cola.
- **Gate de promoción.** Debe batir a los dos baselines (solo keywords y solo
  CPV 48/72) en el holdout, y se mide aparte dentro de «CPV 48/72 sin keyword».
  Se registra en `model_versions` y pasa una semana en sombra con un informe de
  qué entra y qué sale.
- **Nombre técnico.** Conserva `sap_classifier` y `train-model.yml` hasta la
  fase F5, para no tocar workflows antes de tiempo. `ml_proba` pasa a
  significar P(es TI), que es lo que el binario ya aprende hoy.

**Nivel 2: familias.**

- Es un one-vs-rest solo sobre `es_ti = true`, con split agrupado y temporal
  (el del binario; hoy el multi-tecnología parte al azar y se cuelan títulos
  casi idénticos como «… edició 01»).
- Umbral por familia con precisión mínima de 0,80.
- Las familias con menos de 50 positivos independientes siguen en el tier
  `rules`.
- Se registra en `model_versions`, cosa que hoy no pasa.

**Nivel 3: fabricantes.** Diccionario. Se mide su precisión en el golden (≥ 0,95).

## 5. Cadena de decisión, reclasificación y vigilancia

- **Ingesta.**
  - La puerta sigue siendo el filtro de admisión: no cambia qué entra.
  - Sobre lo admitido, las reglas de alta precisión deciden directamente y el
    resto pasa por el modelo.
  - Cada decisión guarda quién la tomó, la confianza y las versiones
    (diccionario, modelo, prompt).
- **Diario.** El LLM trabaja primero la banda dudosa, por fecha e importe, y no
  por «lo más nuevo» como hoy. Los desacuerdos van a la cola humana.
- **Reclasificación.**
  - Un job recalcula, por la vía de ADR-026, las filas cuya versión no es la
    vigente.
  - Hoy una etiqueta solo se refresca reingiriendo la fila: 318 de las 365
    licitaciones con «VMware» en el título siguen sin etiqueta aunque `vmware`
    ya está en el diccionario.
- **Vigilancia semanal por fuente:**
  - % TI, % dudoso y acuerdo LLM↔modelo;
  - alerta si un modelo dice «sí» a más del 90 % de una fuente (el 99,5 % de
    PSCP habría saltado);
  - `domain-truth` cambia su criterio de `ml_proba > 0,7` al % TI por fuente.

## 6. Fases (cada una, un PR)

| Fase | Qué | Necesita |
|---|---|---|
| F0 | Arreglos rápidos (§1) | hecho |
| F1 | Política de frontera y familias nuevas; prompt v3 (`es_ti`); esquema del golden; formulario y cola por desacuerdo en `/ops`; `relevante` = `es_ti` | decisiones D1, D2 |
| F2 | Muestra LLM en producción + revisión humana → `golden_ti.jsonl` | OK a lanzar el LLM; tu tiempo |
| F3 | Modelo de nivel 1 con baselines, gate y sombra | — |
| F4 | Modelo de nivel 2 | — |
| F5 | Tabla de decisión con procedencia, cambio de los consumidores del universo (Radar, Mercado, superficie pública) a «es TI», reclasificación, vigilancia, renombre del binario | migración + reconstrucción de vistas materializadas + revisión de ADR-026 + workflows (OK explícito, AGENTS.md §6) |

- **Qué dice ADR-026 y cuándo cambia.** ADR-026 fija la precedencia keyword >
  modelo > LLM > pliego y que el merge nunca borra; F1-F4 no la contradicen.
  F5 sí, porque «no es TI» oculta filas del universo, y por eso la acompaña
  una revisión del ADR.
- **Hasta F5 no hay migraciones.** `ml_proba` guarda P(es TI),
  `licitacion_tecnologia_pliego` guarda la salida del LLM (sentinels
  incluidos) y `ml_feedback` guarda la humana.

## 7. Decisiones pendientes (del propietario)

- **D1. Frontera de «TI».** Propuesta:
  - Dentro: software (licencias, SaaS, desarrollo, mantenimiento de
    aplicaciones), servicios TI (soporte, CAU, outsourcing, consultoría TI),
    infraestructura (cloud, hosting, CPD, redes de datos, virtualización,
    servidores, almacenamiento, backup), ciberseguridad, datos/BI/IA,
    administración electrónica, sanidad digital, GIS y hardware de puesto.
  - Fuera: formación sobre herramientas (salvo dentro de una implantación),
    suscripciones a contenidos (revistas, bases de datos bibliográficas o
    clínicas), telefonía de voz, publicidad y eventos, y obra civil o
    climatización del CPD.
  - Los contratos menores ya adjudicados siguen siendo TI: si son oportunidad
    lo dicen el estado y el procedimiento, no este clasificador.
- **D2. Familias nuevas.** Añadir `RRHH_NOMINA`, `GESTION_DOCUMENTAL` y
  `PUESTO_TRABAJO` (hardware de usuario, ofimática, soporte a usuario) a las 9
  actuales. Las redes de datos van dentro de `CLOUD_INFRA`, que pasa a
  llamarse «Infraestructura, cloud y redes».
- **D3. Lanzar el LLM sobre la muestra de 4.000 en producción** (escribe en
  `licitacion_tecnologia_pliego`; ~2 $).
- **D4. Tu revisión de ~500 ejemplos** (~4 h, repartible).
- **D5.** La migración y los workflows de F5 se piden cuando lleguemos, con el
  diseño de la tabla delante.

## 8. Riesgos

- **Cambio de consumidores (F5).** Es lo más delicado: cambia qué ven el Radar,
  Mercado y la superficie pública. Va detrás de un flag, con un informe del
  delta y en ventana.
- **Calidad del LLM.** Se mide contra el golden humano antes de usarlo como
  etiqueta (§3.5).
- **Tamaño del golden.** Con 500, un intervalo de precisión de ±3 puntos es
  alcanzable. Con menos, las métricas del gate vuelven a ser ruido, que es el
  problema de hoy.
