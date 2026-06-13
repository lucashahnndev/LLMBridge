from __future__ import annotations

from backend.app.core.config import get_settings
from backend.app.drivers.base import OpenAICompatibleDriver, ProviderDriver
from backend.app.drivers.github_models import GithubModelsDriver
from backend.app.drivers.google import GoogleDriver
from backend.app.drivers.openai import OpenAIDriver
from backend.app.drivers.openrouter import OpenRouterDriver


OPENAI_COMPATIBLE_DOWNSTREAM_PROVIDERS = frozenset(
    {
        "openai",
        "anthropic",
        "cohere",
        "deepseek",
        "meta",
        "microsoft",
        "mistral",
        "mistral-ai",
        "perplexity",
        "xai",
    }
)

def get_provider_driver(provider: str) -> ProviderDriver:
    settings = get_settings()
    provider_map = {
        "openai": OpenAIDriver("openai", settings.openai_api_base),
        "openrouter": OpenRouterDriver("openrouter", settings.openrouter_api_base),
        "google": GoogleDriver("google", settings.google_api_base),
        "github": GithubModelsDriver("github", settings.github_models_api_base, settings.github_models_api_version),
    }
    if provider not in provider_map:
        raise KeyError(provider)
    return provider_map[provider]


def get_output_adapter_driver(provider: str) -> ProviderDriver:
    if provider in {"openai", "openrouter", "google"}:
        return get_provider_driver(provider)
    if provider in OPENAI_COMPATIBLE_DOWNSTREAM_PROVIDERS:
        settings = get_settings()
        return OpenAICompatibleDriver(provider, settings.openai_api_base)
    raise KeyError(provider)
