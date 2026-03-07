from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from jose import JWTError, jwt

from src.core.config import get_settings

settings = get_settings()

# Paths that don't require tenant context
PUBLIC_PATHS = {"/health", "/docs", "/redoc", "/openapi.json"}


class TenantMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        path = request.url.path
        # Skip public/auth paths
        if path in PUBLIC_PATHS or path.startswith(f"{settings.api_prefix}/auth"):
            return await call_next(request)

        auth_header = request.headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
            try:
                payload = jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])
                request.state.tenant_id = payload.get("tenant_id")
            except JWTError:
                # Let the route-level dependency handle auth errors
                pass

        return await call_next(request)
