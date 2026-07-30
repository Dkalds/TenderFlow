# Cobertura regional de contratación

| Fuente | Conector | Alcance honesto | Limitación principal |
|---|---|---|---|
| Catalunya (PSCP) | `PscpConnector` | Dataset Socrata incremental | Depende del dataset configurado y de sus campos publicados. |
| Galicia | `GaliciaRssConnector` | Publicaciones recientes del RSS oficial, filtradas por señal tecnológica | El feed no es histórico ni comunica todos los cambios de expediente. |
| País Vasco | `EuskadiRssConnector` | Anuncios recientes del RSS oficial de Open Data Euskadi, filtrados por señal tecnológica | No se trata como censo: el RSS tiene ventana/tamaño limitado; la API REST oficial requiere una integración paginada validada aparte. |

Los tres conectores usan `run_connector`: IDs namespaceados, upsert idempotente,
DLQ por aviso y estado de salud/frescura en `source_ingestion_health`. El panel
de SLA debe mostrar la fuente y su universo, nunca sumar estos feeds como una
cuota de mercado completa.
