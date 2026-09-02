from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "test_grounded_generation_behaviors.py"
spec = importlib.util.spec_from_file_location("stage9_smoke_script", SCRIPT_PATH)
assert spec and spec.loader
stage9_smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stage9_smoke)


class FakeResponse:
    def __init__(self, status_code: int, payload: dict, headers: dict[str, str] | None = None):
        self.status_code = status_code
        self._payload = payload
        self.headers = headers or {}
        self.text = __import__("json").dumps(payload)
        self.ok = 200 <= status_code < 400

    def json(self):
        return self._payload


def _wrapped_429(wait: float = 21.81) -> FakeResponse:
    return FakeResponse(
        502,
        {
            "detail": {
                "code": "generation_provider_error",
                "provider_status_code": 429,
                "provider_detail": {
                    "error": {
                        "message": f"Rate limit reached. Please try again in {wait}s.",
                        "code": "rate_limit_exceeded",
                    }
                },
            }
        },
    )


def test_provider_status_code_reads_wrapped_429():
    assert stage9_smoke._provider_status_code(_wrapped_429()) == 429


def test_provider_retry_after_parses_groq_message():
    assert stage9_smoke._provider_retry_after_seconds(_wrapped_429(13.5)) == 13.5


def test_post_retries_wrapped_429_once(monkeypatch):
    responses = [_wrapped_429(1.5), FakeResponse(200, {"status": "answered"})]
    sleeps: list[float] = []

    monkeypatch.setattr(stage9_smoke.requests, "post", lambda *args, **kwargs: responses.pop(0))
    monkeypatch.setattr(stage9_smoke.time, "sleep", sleeps.append)

    response, retries = stage9_smoke._post_with_rate_limit_retry(
        url="http://localhost/test",
        payload={"document_id": "doc", "question": "q"},
        timeout=5,
        max_retries=2,
        retry_buffer_seconds=2.0,
        fallback_retry_seconds=30.0,
    )

    assert response.ok is True
    assert retries == 1
    assert sleeps == [3.5]
