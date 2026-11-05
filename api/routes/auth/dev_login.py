"""``POST /auth/dev-login``: entrada sin credenciales, solo con ``ENV=dev``."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response, status

from api.concurrency import run_db
from api.routes.auth.comun import UserInfo, _set_session_cookie
from config import settings
from db.users import get_user_by_id, is_admin, log_access
from observability.logging import get_logger

# El nombre de antes de partir el módulo: `logger` sale en cada línea de log.
log = get_logger("api.routes.auth")

router = APIRouter()


# ---------------------------------------------------------------------------
# Dev-only quick login (no password required)
# ---------------------------------------------------------------------------

if settings.ENV == "dev":

    @router.post("/dev-login", response_model=UserInfo)
    async def dev_login(response: Response, request: Request) -> UserInfo:
        """DEV ONLY: Set session cookie for user_id=1 without credentials.

        This endpoint is only available when ENV=dev. It allows quick
        login during local development without requiring Google OAuth
        or password setup.
        """

        def _dev_login() -> UserInfo:
            user = get_user_by_id(1)
            if user is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Dev user (id=1) not found",
                )
            _set_session_cookie(response, user["id"], request)
            log_access(auth_method="dev_login", user_id=user["id"])
            log.info("dev_login_success", user_id=user["id"])
            return UserInfo(
                user_id=user["id"],
                email=user.get("email"),
                display_name=user.get("display_name"),
                is_admin=is_admin(user["id"]),
            )

        return await run_db(_dev_login)
