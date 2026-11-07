"""DeepEval adapter using the same LLMConfig as the application.

Provider SDKs keep scoring independent of the app's LangChain dependencies.
"""
import asyncio
import json

from deepeval.models import DeepEvalBaseLLM

from src.llms.llm_config import LLMConfig


class EvaluationLLM(DeepEvalBaseLLM):
    def __init__(self, config=None):
        self.config = config or LLMConfig.from_env()
        self.provider = self.config.provider
        self.model_name = self.config.deployment or self.config.model_name
        super().__init__(model_name=self.model_name)

    def load_model(self):
        if self.provider == "cohere":
            from cohere import ClientV2
            return ClientV2(api_key=self.config.api_key)
        from openai import AzureOpenAI, OpenAI
        if self.provider == "azure_openai":
            return AzureOpenAI(
                api_key=self.config.api_key, azure_endpoint=self.config.endpoint,
                api_version=self.config.api_version,
            )
        return OpenAI(api_key=self.config.api_key)

    def get_model_name(self):
        return f"{self.provider}:{self.model_name}"

    def generate(self, prompt, schema=None):
        if schema is not None:
            prompt += "\nReturn only a JSON object matching this schema:\n" + json.dumps(schema.model_json_schema())
        kwargs = dict(model=self.model_name, messages=[{"role": "user", "content": prompt}])
        if schema is not None:
            kwargs["response_format"] = {"type": "json_object"}
        if self.provider == "cohere":
            response = self.model.chat(**kwargs)
            content = "".join(getattr(block, "text", "") for block in response.message.content or [])
        else:
            response = self.model.chat.completions.create(**kwargs)
            content = response.choices[0].message.content
        if not content:
            raise ValueError("Evaluation model returned no text")
        # Invalid judge JSON becomes a reported evaluation error, never a pass.
        return schema.model_validate_json(content) if schema is not None else content

    async def a_generate(self, prompt, schema=None):
        return await asyncio.to_thread(self.generate, prompt, schema)
