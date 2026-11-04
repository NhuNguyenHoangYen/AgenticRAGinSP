"""Resolve and validate LLM settings without constructing an API client."""

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


load_dotenv(Path(__file__).resolve().parents[2] / ".env")


@dataclass(frozen=True)
class LLMConfig:
    """Validated provider settings; credentials are excluded from repr."""

    provider: str
    api_key: str = field(repr=False)
    model_name: str = None
    endpoint: str = None
    deployment: str = None
    api_version: str = None

    def __post_init__(self):
        if self.provider not in {"cohere", "openai", "azure_openai"}:
            raise ValueError(f"Unsupported LLM type: {self.provider}")
        required = {"api_key": f"{self.provider.upper()}_API_KEY"}
        if self.provider == "azure_openai":
            required.update(
                endpoint="AZURE_OPENAI_ENDPOINT",
                deployment="AZURE_OPENAI_DEPLOYMENT",
                api_version="AZURE_OPENAI_API_VERSION",
            )
        missing = [variable for name, variable in required.items()
                   if not getattr(self, name) or not getattr(self, name).strip()]
        if missing:
            raise ValueError("Missing LLM configuration: " + ", ".join(missing))

    @classmethod
    def from_env(cls, llm_type=None, **overrides):
        """Explicit nonempty arguments take precedence over environment settings."""
        provider = (llm_type if llm_type is not None else
                    os.getenv("LLM_PROVIDER", "cohere")).strip().lower()
        if provider not in {"cohere", "openai", "azure_openai"}:
            raise ValueError(f"Unsupported LLM type: {provider}")
        key_argument = "cohere_api_key" if provider == "cohere" else "openai_api_key"
        api_key = overrides.get(key_argument) or os.getenv(f"{provider.upper()}_API_KEY")
        if provider == "azure_openai":
            values = {
                name: overrides.get(name) or os.getenv(f"AZURE_OPENAI_{name.upper()}")
                for name in ("endpoint", "deployment", "api_version")
            }
            return cls(provider=provider, api_key=api_key, **values)
        default = "command-a-03-2025" if provider == "cohere" else "gpt-4.1-mini"
        return cls(
            provider=provider,
            api_key=api_key,
            model_name=(overrides.get("model_name")
                        or os.getenv(f"{provider.upper()}_MODEL") or default),
        )

    def wrapper_kwargs(self):
        """Translate shared settings into provider wrapper constructor arguments."""
        if self.provider == "azure_openai":
            return dict(openai_api_key=self.api_key, endpoint=self.endpoint,
                        deployment=self.deployment, api_version=self.api_version)
        key = "cohere_api_key" if self.provider == "cohere" else "openai_api_key"
        return {key: self.api_key, "model_name": self.model_name}
