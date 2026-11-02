"""OpenAI chat model wrapper for LangChain-based generation and tool calling."""

from typing import Iterator, Union

from langchain_openai import ChatOpenAI

from src.llms.base_llm import BaseLLM


class OpenAILLM(BaseLLM):
    """Initialize an OpenAI chat model, matching the CohereLLM interface."""

    def __init__(self, openai_api_key: str, model_name: str = "gpt-4.1-mini"):
        super().__init__()
        self.chat_model = ChatOpenAI(model=model_name, api_key=openai_api_key)

    def get_llm(self):
        """Return the underlying LangChain model for the agent."""
        return self.chat_model

    def generate(self, prompt: str, stream: bool = False) -> Union[str, Iterator[str]]:
        """Return an answer, or an iterator of text fragments when streaming."""
        if stream:
            return self._stream_text(prompt)
        return self.chat_model.invoke(prompt).content

    def _stream_text(self, prompt: str) -> Iterator[str]:
        """Convert LangChain message chunks to text fragments."""
        for chunk in self.chat_model.stream(prompt):
            yield chunk.content
