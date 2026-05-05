import base64
import hashlib
import hmac
import os

PBKDF2_ITERATIONS = 600000
SALT_BYTES = 16
ALGORITHM = "sha256"


def hash_password(password: str) -> str:
    salt = os.urandom(SALT_BYTES)
    digest = hashlib.pbkdf2_hmac(ALGORITHM, password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return f"pbkdf2_{ALGORITHM}${PBKDF2_ITERATIONS}${base64.b64encode(salt).decode('ascii')}${base64.b64encode(digest).decode('ascii')}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        scheme, iterations, salt_b64, digest_b64 = stored_hash.split("$", 3)
        _, algorithm = scheme.split("_", 1)
        salt = base64.b64decode(salt_b64.encode("ascii"))
        expected_digest = base64.b64decode(digest_b64.encode("ascii"))
        calculated_digest = hashlib.pbkdf2_hmac(algorithm, password.encode("utf-8"), salt, int(iterations))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(calculated_digest, expected_digest)
