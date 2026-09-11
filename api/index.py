import sys
import os

# Ensure project root directory is on sys.path in Vercel lambda execution environment
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from backend.server import app

# Vercel's @vercel/python runtime calls this as an ASGI app.
__all__ = ["app"]
