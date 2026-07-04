---
id: ADR-005
title: "Clustering: MiniBatchKMeans + c-TF-IDF + stopwords externas"
status: accepted
tags: [adr]
---

# ADR-005 — Clustering: MiniBatchKMeans + c-TF-IDF + stopwords externas

* **Estado:** Aceptado
* **Fase:** F1 + F3
* **Contexto previo:** `dashboard/clustering.py` usaba KMeans clásico con
  un `Counter` simple y stopwords inline; los imports estaban tardíos
  y los `except Exception` ocultaban fallos reales.

## Decisión

1. **Imports a nivel de módulo** para `sklearn` y `numpy` — son
   dependencias *core* (`requirements.in`), no opcionales. Los imports
   tardíos sólo se mantienen para *fallbacks opcionales*
   (`dashboard.embeddings`, `dashboard.data_loader.load_mat_clusters`).
2. **MiniBatchKMeans** cuando `n_samples ≥ 50_000`. Para corpus pequeños
   se mantiene KMeans clásico (mejor calidad por iteración).
3. **`k_max ≤ √n / 2`** sólo en modo `auto_k`. Cuando el usuario fuerza
   `n_clusters`, se respeta hasta el cap absoluto (`_MAX_CLUSTERS = 20`).
4. **Stopwords externas** en `shared/stopwords_es.txt` (lista ampliada,
   incluye léxico del dominio público).
5. **Etiquetado c-TF-IDF**: un "documento" por cluster, TF-IDF sobre
   esos agregados, top-N términos. Penaliza términos comunes a todos
   los clusters; mucho más distintivo que `Counter` simple.
6. **Excepciones estrechas**: `ImportError`, `ValueError`, `RuntimeError`,
   `MemoryError`. El `except Exception` solo sobrevive en best-effort
   teardowns documentados.

## Alternativas consideradas

* **BERTopic** — supera a c-TF-IDF en calidad de etiquetas pero arrastra
  `umap-learn`, `hdbscan`, `torch`. Demasiado peso para Streamlit Cloud.
* **HDBSCAN solo** — no requiere `k`, pero genera labels `-1` (ruido)
  que rompen el contrato actual (`cluster_id` int no negativo). Reservado
  para una fase posterior si emerge la necesidad.

## Consecuencias

* ✔ Mejor escalabilidad (>50k filas sin OOM).
* ✔ Etiquetas más interpretables.
* ✔ Errores ya no se enmascaran; los warnings de Streamlit son visibles.
* ✖ Cambia ligeramente la salida (otros términos top); los tests deben
  validar **estructura**, no strings literales.
* ✖ `c-TF-IDF` requiere agregación previa — coste O(n) adicional al
  etiquetar, despreciable frente al `fit_predict`.
