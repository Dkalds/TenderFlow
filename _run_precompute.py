"""Script temporal para precomputar ml_proba en todas las licitaciones pendientes."""
from scraper.ml_training import precompute_ml_proba

print("Clasificando licitaciones pendientes...")
result = precompute_ml_proba(force=False)
print(f"Resultado: {result}")
