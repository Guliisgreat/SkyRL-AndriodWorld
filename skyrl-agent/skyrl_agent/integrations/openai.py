"""
OpenAI-compatible backend for skyrl-agent.

Supports two API modes:
  - "chat" (default): /v1/chat/completions — works with OpenAI API, Azure, vLLM, SGLang
  - "completions": /v1/completions — raw token-id mode for vLLM/SGLang

Chat mode uses the original ``messages`` passed via kwargs — no tokenizer required.
Images in messages are automatically converted from Qwen VLM format to OpenAI
``image_url`` format.

Config example (YAML):
    generator:
      infer_backend: openai_server
      backend_config:
        model_name: gpt-4o
        api_url: https://api.openai.com   # or http://localhost:8000 for vLLM
        api_type: chat                     # "chat" (default) or "completions"
        model_max_len: 32768
"""

from typing import Any, Dict, List, Optional, Tuple, Union
from skyrl_agent.integrations.base import (
    AsyncInferBackend,
    GeneratorOutput,
    GeneratorInput,
    register_backend,
    BackendSpec,
)
from loguru import logger
import os
import re
import io
import base64
import copy
import aiohttp


# ---------------------------------------------------------------------------
# Message format conversion helpers
# ---------------------------------------------------------------------------

def _convert_messages_for_openai(messages: List[Dict]) -> List[Dict]:
    """
    Convert agent messages (Qwen VLM format) to OpenAI chat-completions format.

    Qwen image format::
        {"type": "image", "image": "data:image/png;base64,...", ...}

    OpenAI image format::
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}}
    """
    converted = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")

        # Plain string content — pass through
        if isinstance(content, str):
            converted.append({"role": role, "content": content})
            continue

        # List of content parts — convert image entries
        if isinstance(content, list):
            new_parts = []
            for part in content:
                ptype = part.get("type", "")
                if ptype == "image" and "image" in part:
                    # Qwen VLM → OpenAI image_url
                    new_parts.append({
                        "type": "image_url",
                        "image_url": {"url": part["image"]},
                    })
                elif ptype == "text":
                    new_parts.append({"type": "text", "text": part.get("text", "")})
                else:
                    # Pass through unknown types
                    new_parts.append(part)
            converted.append({"role": role, "content": new_parts})
            continue

        # Fallback
        converted.append({"role": role, "content": str(content)})

    return converted


def _pil_to_base64(img) -> str:
    """Convert a PIL Image to a base64-encoded PNG string."""
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def _build_chat_content_from_decoded(prompt_text: str, image_data: Optional[List[Any]] = None):
    """
    Fallback: build content from decoded token IDs when messages are unavailable.

    Strips Qwen vision placeholder tokens and interleaves base64 images.
    Returns a plain string (no images) or a list of content parts.
    """
    if not image_data:
        return prompt_text

    placeholder = re.compile(r"<\|vision_start\|>.*?<\|vision_end\|>", re.DOTALL)
    parts = placeholder.split(prompt_text)
    num_placeholders = len(parts) - 1

    content: list = []
    for i, part in enumerate(parts):
        text = part.strip()
        if text:
            content.append({"type": "text", "text": text})
        if i < num_placeholders and i < len(image_data):
            img_b64 = _pil_to_base64(image_data[i])
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{img_b64}"},
            })

    for j in range(num_placeholders, len(image_data)):
        img_b64 = _pil_to_base64(image_data[j])
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{img_b64}"},
        })

    return content


class OpenAIBackend(AsyncInferBackend):
    """
    Async inference backend that calls any OpenAI-compatible API.

    In **chat** mode (default), the backend uses the original ``messages``
    passed as a kwarg — no tokenizer needed.  Images in Qwen VLM format are
    automatically converted to OpenAI ``image_url`` format.

    In **completions** mode, raw token IDs are sent to ``/v1/completions``
    (for vLLM / SGLang).
    """

    def __init__(
        self,
        infer_engine: Any = None,
        tokenizer: Any = None,
        cfg: Dict[str, Any] = None,
    ):
        cfg = cfg or {}
        self.api_key = os.environ.get("OPENAI_API_KEY", "")
        if not self.api_key:
            logger.warning("OPENAI_API_KEY not set — requests may fail for authenticated endpoints")

        self.model_name = cfg["model_name"]
        self.api_url = str(cfg.get("api_url", "https://api.openai.com")).rstrip("/")
        self.tokenizer = tokenizer

        # "chat" → /v1/chat/completions  |  "completions" → /v1/completions
        self.api_type = str(cfg.get("api_type", "chat")).lower()

        try:
            self.model_max_len = int(cfg["model_max_len"])
        except (KeyError, TypeError):
            self.model_max_len = 32768
            logger.info(f"model_max_len not in config, defaulting to {self.model_max_len}")

    # ------------------------------------------------------------------
    # Main interface expected by the agent
    # ------------------------------------------------------------------

    async def async_generate_ids(
        self,
        input_ids: List[int],
        sampling_params: Dict[str, Any],
        request_id: str = None,
        image_data: List[Any] = None,
        return_token_ids: bool = False,
        **kwargs,
    ) -> Union[Tuple[str, str], Tuple[str, str, List[int], List[int]]]:
        """
        Generate text via an OpenAI-compatible API.

        In chat mode the ``messages`` kwarg (original OpenAI-format messages
        from the agent) is used directly — no tokenizer round-trip needed.
        Falls back to decoding *input_ids* if messages are not provided.

        Returns:
            (response_text, finish_reason)  when *return_token_ids* is False
            (response_text, finish_reason, prompt_ids, response_ids)  when True
        """
        if not isinstance(sampling_params, dict):
            sampling_params = dict(sampling_params)

        messages = kwargs.get("messages")  # Passed by agent; None for legacy callers

        if self.api_type == "chat":
            if messages is not None:
                # Direct path: send messages to chat API (no tokenizer needed)
                response_text, finish_reason, data = await self._chat_generate_from_messages(
                    messages, sampling_params,
                )
                # Use API usage so image + text tokens are counted (e.g. for Combo agent)
                api_usage = (data or {}).get("usage") or {}
            else:
                # Fallback: decode input_ids (requires tokenizer)
                response_text, finish_reason = await self._chat_generate_from_ids(
                    input_ids, sampling_params, image_data,
                )
                api_usage = {}
        else:
            response_text, finish_reason = await self._completions_generate(
                input_ids, sampling_params,
            )
            api_usage = {}

        if return_token_ids:
            # Prefer API-reported prompt_tokens (includes image tokens for vision models)
            prompt_tokens = api_usage.get("prompt_tokens")
            if prompt_tokens is not None:
                prompt_token_ids = [0] * int(prompt_tokens)
            else:
                prompt_token_ids = list(input_ids)
            if self.tokenizer is None:
                completion_tokens = api_usage.get("completion_tokens")
                response_ids = [0] * int(completion_tokens) if completion_tokens is not None else []
                return response_text, finish_reason, prompt_token_ids, response_ids
            response_ids = self.tokenizer.encode(response_text, add_special_tokens=False)
            return response_text, finish_reason, prompt_token_ids, list(response_ids)

        return response_text, finish_reason

    async def async_generate_prompts(
        self,
        prompts: Any,
        sampling_params: Any,
        **kwargs,
    ) -> str:
        """Generate a response from a plain-text or message-list prompt."""
        if not isinstance(sampling_params, dict):
            sampling_params = dict(sampling_params)

        if isinstance(prompts, list):
            messages = prompts
        else:
            messages = [{"role": "user", "content": prompts}]

        payload = self._base_sampling_payload(sampling_params)
        payload["messages"] = messages

        data = await self._api_call(f"{self.api_url}/v1/chat/completions", payload)

        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as e:
            logger.error(f"Unexpected chat response: {data} — {e}")
            raise RuntimeError(f"OpenAI chat completion failed: {data}") from e

    # ------------------------------------------------------------------
    # Internal: Chat from messages (preferred — no tokenizer needed)
    # ------------------------------------------------------------------

    async def _chat_generate_from_messages(
        self,
        messages: List[Dict],
        sampling_params: Dict[str, Any],
    ) -> Tuple[str, str, Dict[str, Any]]:
        """Convert agent messages to OpenAI format and call chat completions.

        Returns:
            (response_text, finish_reason, data) so callers can read usage (e.g. prompt_tokens).
        """
        openai_messages = _convert_messages_for_openai(messages)

        payload = self._base_sampling_payload(sampling_params)
        payload["messages"] = openai_messages

        data = await self._api_call(f"{self.api_url}/v1/chat/completions", payload)

        try:
            choice = data["choices"][0]
            response_text = choice["message"]["content"]
            finish_reason = choice.get("finish_reason", "stop") or "stop"
            return response_text, finish_reason, data
        except (KeyError, IndexError, TypeError) as e:
            logger.error(f"Unexpected chat response: {data} — {e}")
            raise RuntimeError(f"OpenAI chat completion failed: {data}") from e

    # ------------------------------------------------------------------
    # Internal: Chat from input_ids (fallback — needs tokenizer)
    # ------------------------------------------------------------------

    async def _chat_generate_from_ids(
        self,
        input_ids: List[int],
        sampling_params: Dict[str, Any],
        image_data: Optional[List[Any]],
    ) -> Tuple[str, str]:
        """Decode token IDs → text, attach images, call chat completions."""
        if self.tokenizer is None:
            raise RuntimeError(
                "Chat API fallback requires a tokenizer to decode input_ids. "
                "Either pass messages= or provide a tokenizer."
            )

        prompt_text = self.tokenizer.decode(input_ids, skip_special_tokens=False)
        content = _build_chat_content_from_decoded(prompt_text, image_data)

        messages = [{"role": "user", "content": content}]
        payload = self._base_sampling_payload(sampling_params)
        payload["messages"] = messages

        data = await self._api_call(f"{self.api_url}/v1/chat/completions", payload)

        try:
            choice = data["choices"][0]
            response_text = choice["message"]["content"]
            finish_reason = choice.get("finish_reason", "stop") or "stop"
            return response_text, finish_reason
        except (KeyError, IndexError, TypeError) as e:
            logger.error(f"Unexpected chat response: {data} — {e}")
            raise RuntimeError(f"OpenAI chat completion failed: {data}") from e

    # ------------------------------------------------------------------
    # Internal: Completions (/v1/completions) — raw token-id mode
    # ------------------------------------------------------------------

    async def _completions_generate(
        self,
        input_ids: List[int],
        sampling_params: Dict[str, Any],
    ) -> Tuple[str, str]:
        """Send raw token IDs to /v1/completions (vLLM / SGLang)."""
        payload = self._base_sampling_payload(sampling_params)
        payload["prompt"] = input_ids

        data = await self._api_call(f"{self.api_url}/v1/completions", payload)

        try:
            choice = data["choices"][0]
            response_text = choice["text"]
            finish_reason = choice.get("finish_reason", "stop") or "stop"
            return response_text, finish_reason
        except (KeyError, IndexError, TypeError) as e:
            logger.error(f"Unexpected completions response: {data} — {e}")
            raise RuntimeError(f"OpenAI completion failed: {data}") from e

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _base_sampling_payload(self, sampling_params: Dict[str, Any]) -> Dict[str, Any]:
        """Build the common payload fields (model + sampling params)."""
        payload: Dict[str, Any] = {"model": self.model_name}
        for key in ("temperature", "top_p", "max_tokens", "stop", "n",
                     "presence_penalty", "frequency_penalty", "seed"):
            if key in sampling_params:
                payload[key] = sampling_params[key]
        return payload

    async def _api_call(self, url: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """POST *payload* to *url* and return the parsed JSON response."""
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=600)) as session:
            resp = await session.post(url, json=payload, headers=headers)
            data = await resp.json()

            if resp.status != 200:
                error_msg = data.get("error", {}).get("message", str(data)) if isinstance(data, dict) else str(data)
                logger.error(f"API error {resp.status} from {url}: {error_msg}")
                raise RuntimeError(f"OpenAI API error {resp.status}: {error_msg}")

            return data


# ---------------------------------------------------------------------------
# Generator wrappers
# ---------------------------------------------------------------------------

class OpenAIGeneratorOutput(GeneratorOutput):
    def __init__(self, result: Any):
        self.result = result


class OpenAIGeneratorInput(GeneratorInput):
    def __init__(self, input_batch: Any):
        self.input_batch = input_batch


register_backend(
    "openai_server",
    BackendSpec(
        infer_backend_cls=OpenAIBackend,
        generator_output_cls=OpenAIGeneratorOutput,
        generator_input_cls=OpenAIGeneratorInput,
    ),
)
