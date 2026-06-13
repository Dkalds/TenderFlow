"""Vercel serverless entry point — re-exports the FastAPI ASGI app."""

from api.app import app  # noqa: F401

# Vercel's @vercel/python runtime auto-detects `app` as an ASGI application.
