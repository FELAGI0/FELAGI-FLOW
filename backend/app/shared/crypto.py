"""Симметричное шифрование секретов credentials (Fernet).

Fernet - аутентифицированное шифрование (AES-128-CBC + HMAC-SHA256), ключ берём
из `settings.fernet_key`. Секреты (bot-токены, OAuth-токены) лежат в БД только в
зашифрованном виде; наружу через API никогда не возвращаются.

`encrypt` возвращает `bytes` для колонки `credentials.encrypted_payload`.
Ошибка расшифровки (чужой/сменённый ключ, повреждённые данные) -> `CryptoError`,
чтобы вызывающий отдал внятную ошибку шага, а не трейсбек наружу.
"""

from cryptography.fernet import Fernet, InvalidToken

from app.shared.config import settings


class CryptoError(Exception):
    """Шифрование/расшифровка невозможны (нет ключа или payload повреждён)."""


def _fernet() -> Fernet:
    if not settings.fernet_key:
        raise CryptoError("FERNET_KEY is not configured")
    return Fernet(settings.fernet_key.encode())


def encrypt(plaintext: str) -> bytes:
    """Строка -> шифротекст (bytes) для хранения в bytea."""
    return _fernet().encrypt(plaintext.encode())


def decrypt(ciphertext: bytes) -> str:
    """Шифротекст -> исходная строка. CryptoError при неверном ключе/данных."""
    try:
        return _fernet().decrypt(ciphertext).decode()
    except InvalidToken as exc:
        raise CryptoError("could not decrypt credential payload") from exc
