import asyncio
import json
import unittest
from types import SimpleNamespace

from app.services.ai_engine import AIService, _CIRCUIT_BREAKER_THRESHOLD, _MAX_STREAM_CHUNK_CHARS


class _FakeModels:
    def __init__(self):
        self._responses = []
        self._stream_chunks = []

    def queue_response(self, value):
        self._responses.append(value)

    def queue_stream(self, chunks):
        self._stream_chunks = chunks

    async def generate_content(self, **_kwargs):
        next_item = self._responses.pop(0)
        if isinstance(next_item, Exception):
            raise next_item
        return SimpleNamespace(text=next_item)

    async def generate_content_stream(self, **_kwargs):
        async def _gen():
            for item in self._stream_chunks:
                await asyncio.sleep(0)
                yield SimpleNamespace(text=item)
        return _gen()


class AIResilienceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        AIService._provider_failures = 0
        AIService._provider_open_until = 0.0

    def _service_with_fake_client(self, fake_models: _FakeModels) -> AIService:
        svc = AIService()
        svc._configured = True
        svc._client = SimpleNamespace(aio=SimpleNamespace(models=fake_models))
        return svc

    async def test_generate_trust_report_retries_and_recovers(self):
        models = _FakeModels()
        models.queue_response(RuntimeError("timeout-1"))
        models.queue_response(RuntimeError("timeout-2"))
        models.queue_response(json.dumps({"genel_skor": 70, "musteri_memnuniyeti_skoru": 65, "kalite_skoru": 75, "operasyon_ve_yonetisim_skoru": 68, "risk_summary": "iyi", "kirmizi_bayraklar": [], "tedarikci_karari": "🟢 Tedarik İçin Uygun", "veri_kaynaklari_durumu": {}, "resmi_sicil_detaylari": ""}))
        svc = self._service_with_fake_client(models)
        result = await svc.generate_trust_report("ACME", [], {})
        self.assertEqual(result["genel_skor"], 70)

    async def test_generate_trust_report_handles_malformed_json(self):
        models = _FakeModels()
        models.queue_response("{broken json")
        svc = self._service_with_fake_client(models)
        result = await svc.generate_trust_report("ACME", [], {})
        self.assertEqual(result["genel_skor"], 0)
        self.assertIn("JSON parse", result["risk_summary"])

    async def test_stream_trust_report_caps_chunk_size(self):
        models = _FakeModels()
        too_large = "x" * (_MAX_STREAM_CHUNK_CHARS + 200)
        models.queue_stream([too_large, '{"genel_skor":50}'])
        svc = self._service_with_fake_client(models)

        seen_chunk = False
        async for event in svc.stream_trust_report("ACME", [], {}):
            if '"type": "chunk"' in event:
                seen_chunk = True
                payload = json.loads(event.removeprefix("data: ").strip())
                self.assertLessEqual(len(payload["text"]), _MAX_STREAM_CHUNK_CHARS)
            if event.strip() == "data: [DONE]":
                break
        self.assertTrue(seen_chunk)

    async def test_circuit_breaker_opens_after_repeated_failures(self):
        models = _FakeModels()
        for _ in range(_CIRCUIT_BREAKER_THRESHOLD + 1):
            models.queue_response(RuntimeError("provider_down"))
        svc = self._service_with_fake_client(models)
        for _ in range(_CIRCUIT_BREAKER_THRESHOLD):
            _ = await svc.generate_trust_report("ACME", [], {})
        self.assertTrue(AIService._is_circuit_open())


if __name__ == "__main__":
    unittest.main()
