from __future__ import annotations

from fastapi import HTTPException, status

from backend.app.drivers.base import OpenAICompatibleDriver


class GithubModelsDriver(OpenAICompatibleDriver):
    def __init__(self, provider: str, base_url: str, api_version: str) -> None:
        super().__init__(provider, base_url)
        self.api_version = api_version

    def resolve_model_name(self, model_name: str) -> str:
        normalized = model_name.strip().strip("/")
        if "/" not in normalized:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="github model routes must use github/<publisher>/<model_name>",
            )
        publisher, downstream_model = normalized.split("/", 1)
        if not publisher.strip() or not downstream_model.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="github model routes must use github/<publisher>/<model_name>",
            )
        return normalized

    def build_url(self, model_name: str) -> str:
        _ = model_name
        return f"{self.base_url}/chat/completions"

    def build_headers(self, provider_token: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {provider_token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": self.api_version,
        }
