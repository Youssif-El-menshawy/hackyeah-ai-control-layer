from types import SimpleNamespace

import pytest

from control_layer.core.types import FailureKind, SanitizedContent
from control_layer.semantic.openai_adapter import OpenAIResponsesClassifier


class _Responses:
    def __init__(self):
        self.kwargs = None

    async def create(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(output_text='{"prompt_injection":0.2,"data_exfiltration":0.3}')


@pytest.mark.asyncio
async def test_openai_adapter_uses_configured_model_structured_output_and_no_storage():
    responses = _Responses()
    client = SimpleNamespace(responses=responses)
    adapter = OpenAIResponsesClassifier("configured-model-snapshot", 1000, client=client)
    result = await adapter.classify(SanitizedContent("hello [REDACTED_SECRET_1]"))
    assert result.signals.prompt_injection == 0.2
    assert responses.kwargs["model"] == "configured-model-snapshot"
    assert responses.kwargs["store"] is False
    assert responses.kwargs["text"]["format"]["type"] == "json_schema"
    assert responses.kwargs["input"][1]["content"] == "hello [REDACTED_SECRET_1]"


@pytest.mark.asyncio
async def test_openai_adapter_maps_malformed_output_to_typed_failure():
    responses = _Responses()
    responses.create = _malformed_create
    adapter = OpenAIResponsesClassifier("configured-model", 1000, client=SimpleNamespace(responses=responses))
    result = await adapter.classify(SanitizedContent("safe"))
    assert result.failure is FailureKind.MALFORMED_OUTPUT


async def _malformed_create(**kwargs):
    del kwargs
    return SimpleNamespace(output_text="not-json")
