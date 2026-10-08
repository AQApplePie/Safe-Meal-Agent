"""实现身份认证与令牌安全适配。"""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from argon2 import PasswordHasher as Argon2Hasher
from argon2.exceptions import InvalidHashError, VerificationError
import jwt

from safemeal.modules.identity.contracts import AccessTokenClaims


class Argon2PasswordHasher:
    def __init__(self) -> None:
        self._hasher = Argon2Hasher()

    def hash(self, password: str) -> str:
        return self._hasher.hash(password)

    def verify(self, password_hash: str, password: str) -> bool:
        try:
            return self._hasher.verify(password_hash, password)
        except (VerificationError, InvalidHashError):
            return False

    def needs_rehash(self, password_hash: str) -> bool:
        try:
            return self._hasher.check_needs_rehash(password_hash)
        except InvalidHashError:
            return True


class JwtTokenIssuer:
    def __init__(
        self,
        *,
        secret: str,
        issuer: str,
        audience: str,
        access_token_minutes: int,
    ) -> None:
        self._secret = secret
        self._issuer = issuer
        self._audience = audience
        self._access_token_minutes = access_token_minutes

    def issue_access_token(
        self,
        *,
        subject: str,
        tenant_id: str,
        roles: tuple[str, ...],
        token_version: int,
    ) -> tuple[str, datetime]:
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(minutes=self._access_token_minutes)
        token = jwt.encode(
            {
                "sub": subject,
                "tid": tenant_id,
                "roles": list(roles),
                "ver": token_version,
                "typ": "access",
                "jti": uuid4().hex,
                "iat": now,
                "nbf": now,
                "exp": expires_at,
                "iss": self._issuer,
                "aud": self._audience,
            },
            self._secret,
            algorithm="HS256",
        )
        return token, expires_at

    def decode_access_token(self, token: str) -> AccessTokenClaims:
        payload = jwt.decode(
            token,
            self._secret,
            algorithms=["HS256"],
            issuer=self._issuer,
            audience=self._audience,
            options={"require": ["sub", "tid", "ver", "typ", "exp", "iat"]},
        )
        if payload.get("typ") != "access":
            raise jwt.InvalidTokenError("unexpected token type")
        roles = payload.get("roles")
        return AccessTokenClaims(
            subject=str(payload["sub"]),
            tenant_id=str(payload["tid"]),
            roles=tuple(str(item) for item in roles) if isinstance(roles, list) else (),
            token_version=int(payload["ver"]),
            expires_at=datetime.fromtimestamp(float(payload["exp"]), timezone.utc),
        )
