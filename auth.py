"""Middleware de autenticacion: exige una sesion valida de Supabase para /api/*.

Requiere dos variables de entorno:
  SUPABASE_URL       - la URL del proyecto (ej. https://xxxxx.supabase.co)
  SUPABASE_ANON_KEY  - la key publica/anon del proyecto (no es secreta)

ponytail: se verifica la sesion llamando a Supabase (GET /auth/v1/user) en vez
de decodificar el JWT localmente -- evita tener que manejar el JWT secret
como otro secreto mas en Vercel. El costo es una llamada HTTP extra por
request, aceptable al volumen de este CRM.
"""
import os
import httpx
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY", "")


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if request.url.path.startswith("/api/"):
            authorization = request.headers.get("authorization", "")
            if not authorization.startswith("Bearer "):
                return JSONResponse({"error": "No autenticado"}, status_code=401)
            if not SUPABASE_URL or not SUPABASE_ANON_KEY:
                return JSONResponse({"error": "Autenticacion no configurada en el servidor"}, status_code=500)

            token = authorization.removeprefix("Bearer ")
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    resp = await client.get(
                        f"{SUPABASE_URL}/auth/v1/user",
                        headers={"Authorization": f"Bearer {token}", "apikey": SUPABASE_ANON_KEY},
                    )
            except httpx.HTTPError:
                return JSONResponse({"error": "No se pudo verificar la sesion"}, status_code=502)

            if resp.status_code != 200:
                return JSONResponse({"error": "Sesion invalida o expirada"}, status_code=401)

        return await call_next(request)
