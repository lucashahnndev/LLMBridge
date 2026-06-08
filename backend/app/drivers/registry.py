from __future__ import annotations

from backend.app.core.config import get_settings
from backend.app.drivers.base import ProviderDriver
from backend.app.drivers.google import GoogleDriver
from backend.app.drivers.openai import OpenAIDriver
from backend.app.drivers.openrouter import OpenRouterDriver


def get_provider_driver(provider: str) -> ProviderDriver:
    settings = get_settings()
    provider_map = {
        "openai": OpenAIDriver("openai", settings.openai_api_base),
        "openrouter": OpenRouterDriver("openrouter", settings.openrouter_api_base),
        "google": GoogleDriver("google", settings.google_api_base),
    }
    if provider not in provider_map:
        raise KeyError(provider)
    return provider_map[provider]
