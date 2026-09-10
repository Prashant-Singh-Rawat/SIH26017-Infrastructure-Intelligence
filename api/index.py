"""
Vercel Python Serverless Function Entry Point -- SIH26017
This module is discovered by @vercel/python as the serverless function handler.
It re-exports the FastAPI ASGI application from the backend package.
"""
from backend.server import app

# Vercel's @vercel/python runtime calls this as an ASGI app.
# FastAPI is ASGI-native, so no adapter is needed.
__all__ = ["app"]
