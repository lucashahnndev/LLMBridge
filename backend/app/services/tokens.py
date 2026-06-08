import secrets


def generate_app_token(prefix: str = "lk-key") -> str:
    return f"{prefix}-{secrets.token_urlsafe(24)}"


def mask_secret(value: str, head: int = 6, tail: int = 4) -> str:
    if len(value) <= head + tail:
        return value
    return f"{value[:head]}...{value[-tail:]}"
