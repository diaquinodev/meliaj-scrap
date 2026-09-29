"""Adapters de inferência. Nenhum retry automático de chamadas faturáveis."""

from dataclasses import dataclass
from typing import Protocol

from .contracts import Draft, ProductInput
from .prompts import SYSTEM_PROMPT


class ProviderUnavailable(RuntimeError):
    pass


class ProviderTimeout(ProviderUnavailable):
    pass


@dataclass(frozen=True)
class Completion:
    text: str
    input_tokens: int | None = None
    output_tokens: int | None = None


class Provider(Protocol):
    def generate(self, product: ProductInput) -> Completion: ...


class DemoProvider:
    """Fixture determinística, não um modelo de IA nem evidência de qualidade."""

    def generate(self, product):
        draft = Draft(
            title=product.name[:60],
            description=f"Produto: {product.name}. " + (product.details or "Detalhes não informados."),
            material=product.material,
        )
        return Completion(draft.model_dump_json())


class GeminiProvider:
    def __init__(self, *, api_key, model, timeout_seconds, max_output_tokens):
        from google import genai
        from google.genai import types

        self.model = model
        provider_schema = Draft.model_json_schema()
        # O SDK aceita boolean, mas não Literal[True] no schema remoto.
        # A restrição continua obrigatória na validação local de Draft.
        provider_schema["properties"]["requires_review"].pop("const", None)
        self.config = types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            response_mime_type="application/json",
            response_schema=provider_schema,
            temperature=0,
            max_output_tokens=max_output_tokens,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        self.client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(
                timeout=int(timeout_seconds * 1000),
                retry_options=types.HttpRetryOptions(attempts=1),
            ),
        )

    def generate(self, product):
        import httpx
        from google.genai import errors

        try:
            response = self.client.models.generate_content(
                model=self.model, config=self.config, contents=product.model_dump_json())
        except httpx.TimeoutException as exc:
            raise ProviderTimeout("Tempo limite de inferência excedido.") from exc
        except (httpx.HTTPError, errors.APIError) as exc:
            raise ProviderUnavailable("Provedor de inferência indisponível.") from exc
        usage = response.usage_metadata
        # Thinking tokens também podem ser faturáveis; contar junto da saída.
        output = None
        if usage and usage.candidates_token_count is not None:
            output = usage.candidates_token_count + (usage.thoughts_token_count or 0)
        return Completion(
            text=response.text or "",
            input_tokens=usage.prompt_token_count if usage else None,
            output_tokens=output,
        )

    def close(self):
        self.client.close()
