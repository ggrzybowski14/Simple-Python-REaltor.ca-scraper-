from __future__ import annotations

import json

import ai_underwriting


class FakeHTTPResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def test_call_openai_researched_json_enables_web_search_and_merges_sources(monkeypatch) -> None:
    captured: dict[str, object] = {}
    response_payload = {
        "output": [
            {
                "type": "web_search_call",
                "action": {
                    "sources": [
                        {"title": "Example Market Source", "url": "https://example.com/source"},
                    ]
                },
            },
            {
                "type": "message",
                "content": [
                    {
                        "type": "output_text",
                        "text": json.dumps(
                            {
                                "answer": "researched",
                                "source_names": [],
                                "source_urls": [],
                            }
                        ),
                    }
                ],
            },
        ]
    }

    def fake_urlopen(req, timeout):
        captured["timeout"] = timeout
        captured["url"] = req.full_url
        captured["body"] = json.loads(req.data.decode("utf-8"))
        return FakeHTTPResponse(response_payload)

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_RESEARCH_MODEL", "gpt-test")
    monkeypatch.setattr(ai_underwriting.request, "urlopen", fake_urlopen)

    result = ai_underwriting.call_openai_researched_json(
        system_text="system",
        prompt_text="prompt",
        payload={"market": "Nanaimo"},
        schema_name="test_schema",
        schema={
            "type": "object",
            "properties": {
                "answer": {"type": "string"},
                "source_names": {"type": "array", "items": {"type": "string"}},
                "source_urls": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["answer", "source_names", "source_urls"],
            "additionalProperties": False,
        },
    )

    body = captured["body"]
    assert captured["url"] == ai_underwriting.OPENAI_RESPONSES_URL
    assert body["model"] == "gpt-test"
    assert body["tools"] == [{"type": "web_search"}]
    assert body["tool_choice"] == "auto"
    assert body["text"]["format"]["type"] == "json_schema"
    assert result["parsed_response"]["source_urls"] == ["https://example.com/source"]
    assert result["parsed_response"]["source_names"] == ["Example Market Source"]


def test_rent_suggestions_schema_includes_market_research_fields(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_researched_json(**kwargs):
        captured.update(kwargs)
        return {
            "raw_response_text": "{}",
            "parsed_response": {
                "market_research_summary": "Current market context reviewed.",
                "direct_comps_found": 3,
                "fallback_comps_found": 1,
                "fallback_strategy": "Used nearby same-property comps.",
                "source_names": ["Example"],
                "source_urls": ["https://example.com"],
                "suggestions": [],
            },
            "model": "gpt-test",
            "web_sources": [],
        }

    monkeypatch.setattr(ai_underwriting, "call_openai_researched_json", fake_researched_json)

    result = ai_underwriting.call_openai_rent_suggestions("prompt", {"listings": []})

    schema = captured["schema"]
    assert "market_research_summary" in schema["properties"]
    assert "direct_comps_found" in schema["required"]
    assert "fallback_strategy" in schema["required"]
    assert "source_urls" in schema["required"]
    assert "direct comparable rents" in captured["system_text"].lower()
    assert result["parsed_response"]["suggestions"] == []


def test_rent_ai_prompt_and_schema_support_multi_unit_components(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_researched_json(**kwargs):
        captured.update(kwargs)
        return {
            "raw_response_text": "{}",
            "parsed_response": {
                "market_research_summary": "Current market context reviewed.",
                "direct_comps_found": 3,
                "fallback_comps_found": 1,
                "fallback_strategy": "Used suite comps where supported.",
                "source_names": ["Example"],
                "source_urls": ["https://example.com"],
                "suggestions": [],
            },
            "model": "gpt-test",
            "web_sources": [],
        }

    monkeypatch.setattr(ai_underwriting, "call_openai_researched_json", fake_researched_json)

    ai_underwriting.call_openai_rent_suggestions("prompt", {"listings": []})

    prompt = ai_underwriting.build_rent_ai_prompt_text().lower()
    suggestion_schema = captured["schema"]["properties"]["suggestions"]["items"]
    assert "multiple rentable units" in prompt
    assert "main_unit plus basement_suite" in prompt
    assert "rent_components must include that unit plus the main unit" in prompt
    assert "do not treat ensuite bathrooms" in prompt
    assert "rent_components" in suggestion_schema["properties"]
    assert "rent_components" in suggestion_schema["required"]


def test_rent_ai_prompt_treats_official_baseline_as_fallback_context() -> None:
    prompt = ai_underwriting.build_rent_ai_prompt_text().lower()

    assert "prioritize whole-property rental comps" in prompt
    assert "official market baseline as optional context" in prompt
    assert "must start with the direct whole-property comparable evidence" in prompt
    assert "do not open the summary with cmhc" in prompt
    assert "fallback strategy" in prompt


def test_market_rental_gap_schema_requires_research_trail(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_researched_json(**kwargs):
        captured.update(kwargs)
        return {
            "raw_response_text": "{}",
            "parsed_response": {
                "average_rent_monthly": 3500,
                "vacancy_rate_percent": None,
                "confidence": "low",
                "market_research_summary": "Direct comps were thin.",
                "direct_comps_found": 1,
                "fallback_comps_found": 4,
                "fallback_strategy": "Expanded to 4+ bedroom detached comps.",
                "reasoning": "Few exact matches were available.",
                "source_names": ["Example"],
                "source_urls": ["https://example.com"],
            },
            "model": "gpt-test",
            "web_sources": [],
        }

    monkeypatch.setattr(ai_underwriting, "call_openai_researched_json", fake_researched_json)

    result = ai_underwriting.call_openai_market_rental_gap_estimate("prompt", {"market": {}})

    schema = captured["schema"]
    assert "direct_comps_found" in schema["required"]
    assert "fallback_comps_found" in schema["required"]
    assert "fallback_strategy" in schema["required"]
    assert "segment-specific comparable rental evidence first" in captured["system_text"].lower()
    assert result["parsed_response"]["average_rent_monthly"] == 3500


def test_market_rental_gap_prompt_starts_with_direct_comps() -> None:
    prompt = ai_underwriting.build_market_rental_gap_prompt_text().lower()

    assert "must start with direct whole-property comps" in prompt
    assert "do not lead with cmhc" in prompt


def test_market_appreciation_prompt_prioritizes_target_market_research() -> None:
    prompt = ai_underwriting.build_market_appreciation_gap_prompt_text().lower()

    assert "prioritize current web research" in prompt
    assert "proxy hpi is fallback context" in prompt
