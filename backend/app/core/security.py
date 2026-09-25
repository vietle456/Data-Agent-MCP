import os
from datetime import UTC, datetime, timedelta

from jose import JWTError, jwt
from passlib.context import CryptContext

# ---------------------------------------------------------------------------
# Configuration – pull from env or fall back to safe defaults for development
# ---------------------------------------------------------------------------
SECRET_KEY: str = os.getenv("SECRET_KEY", "change-me-in-production-please-use-a-long-random-string")
ALGORITHM: str = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))

# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain: str) -> str:
    """Return the bcrypt hash of *plain*."""
    return pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """Return ``True`` if *plain* matches the stored *hashed* password."""
    return pwd_context.verify(plain, hashed)


# ---------------------------------------------------------------------------
# JWT helpers
# ---------------------------------------------------------------------------


def create_access_token(subject: str, expires_delta: timedelta | None = None) -> str:
    """Create a signed JWT access token whose *sub* claim is *subject*."""
    expire = datetime.now(UTC) + (
        expires_delta if expires_delta else timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    payload = {"sub": subject, "exp": expire}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str) -> str:
    """Decode *token* and return the *sub* claim.

    Raises :class:`jose.JWTError` on any validation failure.
    """
    payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    sub: str | None = payload.get("sub")
    if sub is None:
        raise JWTError("Token is missing the 'sub' claim.")
    return sub
