"""
HTTP Security Headers Middleware — SIH26017
Applies defense-in-depth HTTP headers to mitigate XSS, Clickjacking, MIME-sniffing, and data leakage.
"""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)

        # 1. Content-Security-Policy: Allow self, reliable CDNs for Chart.js/Leaflet, Tailwind, and OpenStreetMap/Unsplash
        csp = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.jsdelivr.net https://unpkg.com https://cdn.tailwindcss.com; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdn.jsdelivr.net https://unpkg.com; "
            "font-src 'self' https://fonts.gstatic.com data:; "
            "img-src 'self' data: https://*.tile.openstreetmap.org https://images.unsplash.com; "
            "connect-src 'self' https: http://127.0.0.1:* http://localhost:*; "
            "frame-ancestors 'none'; "
            "base-uri 'self';"
        )
        response.headers["Content-Security-Policy"] = csp
        
        # 2. Prevent MIME-type sniffing
        response.headers["X-Content-Type-Options"] = "nosniff"
        
        # 3. Prevent clickjacking / frame embedding
        response.headers["X-Frame-Options"] = "DENY"
        
        # 4. Strict referrer policy
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        
        # 5. Restrict sensitive browser features
        response.headers["Permissions-Policy"] = "geolocation=(), camera=(), microphone=(), payment=()"
        
        # 6. Legacy XSS filter protection
        response.headers["X-XSS-Protection"] = "1; mode=block"

        # 7. Strict Transport Security (HSTS)
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

        return response
