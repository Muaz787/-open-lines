from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request

# Tool-call endpoints are invoked by Vapi's servers, so all tenants share the
# same originating IPs. Rate-limit those routes by tenant_id instead of IP.
def tenant_key(request: Request) -> str:
    return request.path_params.get("tenant_id") or get_remote_address(request)

limiter = Limiter(key_func=get_remote_address)
