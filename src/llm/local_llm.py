"""
Local LLM client — connects to ollama, vllm, or any OpenAI-compatible API.
"""

from __future__ import annotations

import httpx
import structlog

logger = structlog.get_logger(__name__)


class LocalLLMClient:
    """Async client for local/self-hosted LLMs via OpenAI-compatible API."""

    def __init__(self, base_url: str, model: str, timeout: float = 60.0):
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout = timeout
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._timeout)
        return self._client

    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        max_tokens: int = 512,
        temperature: float = 0.3,
    ) -> str | None:
        """Send a chat completion request to the local LLM."""
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        try:
            client = await self._get_client()
            response = await client.post(
                f"{self._base_url}/v1/chat/completions",
                json={
                    "model": self._model,
                    "messages": messages,
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                },
            )
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"]
        except httpx.HTTPStatusError as exc:
            logger.warning("local_llm_http_error", status=exc.response.status_code, error=str(exc))
            return None
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            logger.warning("local_llm_connection_error", error=str(exc))
            return None
        except Exception as exc:
            logger.warning("local_llm_error", error=str(exc))
            return None

    async def chat(
        self,
        system_prompt: str,
        user_message: str,
        max_tokens: int = 1024,
        temperature: float = 0.3,
    ) -> str | None:
        """Convenience wrapper for chat-style interaction."""
        return await self.generate(
            prompt=user_message,
            system_prompt=system_prompt,
            max_tokens=max_tokens,
            temperature=temperature,
        )

    async def health_check(self) -> bool:
        """Check if the local LLM server is reachable."""
        try:
            client = await self._get_client()
            resp = await client.get(f"{self._base_url}/v1/models")
            return resp.status_code == 200
        except Exception:
            return False

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None
