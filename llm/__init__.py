"""Paquete LLM — abstracción multi-proveedor para streaming de respuestas.

Uso:
    from llm.client import stream_llm_response

    for chunk in stream_llm_response(question, docs, model="gpt-4o-mini", keywords=[...]):
        print(chunk, end="", flush=True)

Proveedores soportados:
    * OpenAI  — modelos ``gpt-*``  (requiere ``openai`` + ``OPENAI_API_KEY``)
    * Anthropic — modelos ``claude-*`` (requiere ``anthropic`` + ``ANTHROPIC_API_KEY``)
"""
