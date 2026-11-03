"""Azure OpenAI chat wrapper using an explicit deployment and API version."""

from typing import Iterator, Union

from langchain_openai import AzureChatOpenAI

from src.llms.base_llm import BaseLLM


class AzureOpenAILLM(BaseLLM):
    """Expose Azure chat through the same interface as the other LLM wrappers."""

    def __init__(
        self,
        openai_api_key: str,
        endpoint: str,
        deployment: str,
        api_version: str,
    ):
        super().__init__()
        self.chat_model = AzureChatOpenAI(
            api_key=openai_api_key,
            azure_endpoint=endpoint,
            azure_deployment=deployment,
            api_version=api_version,
        )

    def get_llm(self):
        """Return the LangChain model, including its tool-calling interface."""
        return self.chat_model

    def generate(self, prompt: str, stream: bool = False) -> Union[str, Iterator[str]]:
        """Return an answer or an iterator of streamed text fragments."""
        if stream:
            return self._stream_text(prompt)
        return self.chat_model.invoke(prompt).content

    def _stream_text(self, prompt: str) -> Iterator[str]:
        """Convert LangChain message chunks to text fragments."""
        for chunk in self.chat_model.stream(prompt):
            yield chunk.content
