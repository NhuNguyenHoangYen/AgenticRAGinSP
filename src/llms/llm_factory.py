"""Create Cohere, OpenAI or Azure OpenAI LLM wrappers using explicit or .env configuration."""

import os
from pathlib import Path

from dotenv import load_dotenv

from src.llms.azure_openai_llm import AzureOpenAILLM
from src.llms.cohere_llm import CohereLLM
from src.llms.openai_llm import OpenAILLM


# Resolve from this file so loading does not depend on the working directory.
# Existing environment variables take precedence over .env values.
load_dotenv(Path(__file__).resolve().parents[2] / ".env")


class LLMFactory:
    """Select a provider and validate its credentials before model creation."""

    @staticmethod
    def create_llm(llm_type: str, **kwargs):
        """Create a wrapper; explicit key/model arguments override environment values.

        Providers are ``cohere``, ``openai`` and ``azure_openai``. Azure requires
        openai_api_key, endpoint, deployment and api_version, or their
        AZURE_OPENAI_* environment settings. Other providers use
        COHERE_API_KEY / COHERE_MODEL or OPENAI_API_KEY / OPENAI_MODEL.
        Raises ValueError for an unsupported provider or missing configuration.
        """
        provider = llm_type.strip().lower()
        if provider == "azure_openai":
            variables = {
                "openai_api_key": "AZURE_OPENAI_API_KEY",
                "endpoint": "AZURE_OPENAI_ENDPOINT",
                "deployment": "AZURE_OPENAI_DEPLOYMENT",
                "api_version": "AZURE_OPENAI_API_VERSION",
            }
            config = {
                argument: kwargs.get(argument) or os.getenv(variable)
                for argument, variable in variables.items()
            }
            missing = [
                variables[argument] for argument, value in config.items()
                if not value or not value.strip()
            ]
            if missing:
                raise ValueError("Missing Azure OpenAI configuration: " + ", ".join(missing))
            return AzureOpenAILLM(**config)

        if provider == "cohere":
            wrapper = CohereLLM
            key_argument = "cohere_api_key"
            default_model = "command-a-03-2025"
        elif provider == "openai":
            wrapper = OpenAILLM
            key_argument = "openai_api_key"
            default_model = "gpt-4.1-mini"
        else:
            raise ValueError(f"Unsupported LLM type: {llm_type}")

        key_variable = key_argument.upper()
        api_key = kwargs.get(key_argument) or os.getenv(key_variable)
        if not api_key or not api_key.strip():
            raise ValueError(f"Set {key_variable} in .env or pass {key_argument}.")

        kwargs[key_argument] = api_key
        kwargs["model_name"] = (
            kwargs.get("model_name")
            or os.getenv(f"{provider.upper()}_MODEL")
            or default_model
        )
        return wrapper(**kwargs)
