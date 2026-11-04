"""Construct provider wrappers from shared, validated LLM configuration."""

from src.llms.azure_openai_llm import AzureOpenAILLM
from src.llms.cohere_llm import CohereLLM
from src.llms.openai_llm import OpenAILLM
from src.llms.llm_config import LLMConfig


class LLMFactory:
    """Keep provider construction out of UI and workflow code."""

    @staticmethod
    def create_llm(llm_type=None, *, config=None, **kwargs):
        """Accept shared configuration or legacy provider/keyword arguments."""
        if config is not None and (llm_type is not None or kwargs):
            raise ValueError("Pass config or provider settings, not both.")
        settings = config if config is not None else LLMConfig.from_env(llm_type, **kwargs)
        wrappers = {
            "cohere": CohereLLM,
            "openai": OpenAILLM,
            "azure_openai": AzureOpenAILLM,
        }
        return wrappers[settings.provider](**settings.wrapper_kwargs())
