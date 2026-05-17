import asyncio
import json
import time
import tracemalloc
import unittest
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx

from app import main


@asynccontextmanager
async def _fake_service(payload):
    yield payload


class _FakeNewsService:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None

    async def get_news(self, _name):
        await asyncio.sleep(0.01)
        return [{"title": "news", "description": "ok"}]


class _FakeFinnhubService:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None

    async def get_company_profile(self, _name):
        await asyncio.sleep(0.01)
        return {"marketCapitalization": 1}


class _FakeCurrencyService:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None

    async def get_rates(self, target_currencies=None):
        await asyncio.sleep(0.01)
        return {"TRY": 1, "EUR": 1}


class _FakeScraperService:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None

    async def get_scraped_data(self, _name, full_address=""):
        await asyncio.sleep(0.01)
        return {"items": [{"title": "review", "description": f"addr={full_address}"}]}


class _FakeAIService:
    async def stream_trust_report(self, *args, **kwargs):
        yield f"data: {json.dumps({'type': 'status', 'message': 'working'})}\n\n"
        yield f"data: {json.dumps({'type': 'chunk', 'text': 'partial'})}\n\n"
        yield f"data: {json.dumps({'type': 'result', 'data': {'genel_skor': 50, 'musteri_memnuniyeti_skoru': 50, 'kalite_skoru': 50, 'operasyon_ve_yonetisim_skoru': 50, 'risk_summary': 'ok', 'kirmizi_bayraklar': [], 'tedarikci_karari': '🟡 Dikkatli Çalışılmalı', 'veri_kaynaklari_durumu': {}, 'resmi_sicil_detaylari': ''}})}\n\n"
        yield "data: [DONE]\n\n"


class _FakeFlakyAIService:
    async def stream_trust_report(self, *args, **kwargs):
        yield f"data: {json.dumps({'type': 'status', 'message': 'working'})}\n\n"
        raise RuntimeError("provider interrupted")


class Phase4ValidationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        async def _fake_db():
            yield SimpleNamespace()

        main.app.dependency_overrides[main.get_db] = _fake_db
        if not hasattr(main.app.state, "inflight_report_keys"):
            main.app.state.inflight_report_keys = set()
        if not hasattr(main.app.state, "inflight_lock"):
            main.app.state.inflight_lock = asyncio.Lock()
        if not hasattr(main.app.state, "background_tasks"):
            main.app.state.background_tasks = set()

    async def asyncTearDown(self):
        main.app.dependency_overrides.clear()
        await asyncio.sleep(0.05)

    async def _consume_sse(self, client, company_id=1, params=None):
        params = params or {}
        chunks = []
        async with client.stream("POST", f"/generate-report/{company_id}", params=params) as resp:
            self.assertEqual(resp.status_code, 200)
            async for line in resp.aiter_lines():
                if line:
                    chunks.append(line)
                if line.strip() == "data: [DONE]":
                    break
        return chunks

    async def test_concurrent_sse_load_and_cleanup(self):
        fake_company = SimpleNamespace(id=1, name="ACME", tax_number="123")
        with patch("app.main.get_company", new=AsyncMock(return_value=fake_company)):
            with patch("app.main.get_fresh_report_by_company", new=AsyncMock(return_value=None)):
                with patch("app.main.NewsService", _FakeNewsService):
                    with patch("app.main.FinnhubService", _FakeFinnhubService):
                        with patch("app.main.CurrencyService", _FakeCurrencyService):
                            with patch("app.main.ScraperService", _FakeScraperService):
                                with patch("app.main.AIService", return_value=_FakeAIService()):
                                    with patch("app.main.create_company_report", new=AsyncMock(return_value=SimpleNamespace(id=1))):
                                        transport = httpx.ASGITransport(app=main.app)
                                        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                                            started = time.perf_counter()
                                            tasks = [self._consume_sse(client) for _ in range(20)]
                                            results = await asyncio.gather(*tasks, return_exceptions=True)
                                            elapsed = time.perf_counter() - started

                                        failures = [r for r in results if isinstance(r, Exception)]
                                        self.assertEqual(len(failures), 0)
                                        self.assertLess(elapsed, 8.0)
                                        await asyncio.sleep(0.1)
                                        self.assertEqual(len(main.app.state.inflight_report_keys), 0)

    async def test_chaos_provider_interrupt_still_finishes_stream(self):
        fake_company = SimpleNamespace(id=1, name="ACME", tax_number="123")
        with patch("app.main.get_company", new=AsyncMock(return_value=fake_company)):
            with patch("app.main.get_fresh_report_by_company", new=AsyncMock(return_value=None)):
                with patch("app.main.NewsService", _FakeNewsService):
                    with patch("app.main.FinnhubService", _FakeFinnhubService):
                        with patch("app.main.CurrencyService", _FakeCurrencyService):
                            with patch("app.main.ScraperService", _FakeScraperService):
                                with patch("app.main.AIService", return_value=_FakeFlakyAIService()):
                                    transport = httpx.ASGITransport(app=main.app)
                                    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                                        lines = await self._consume_sse(client)
                                    self.assertTrue(any('"type": "error"' in ln for ln in lines))
                                    self.assertTrue(any("[DONE]" in ln for ln in lines))

    async def test_official_scraper_overload_fast_fails(self):
        main.app.state.official_data_cache = {}
        main.app.state.official_data_semaphore = asyncio.Semaphore(0)
        result = await main._fetch_official_data_safely("123", "ACME")
        self.assertEqual(result.get("status"), "official_data_unavailable")

    async def test_long_loop_memory_and_task_growth(self):
        fake_company = SimpleNamespace(id=1, name="ACME", tax_number="123")
        with patch("app.main.get_company", new=AsyncMock(return_value=fake_company)):
            with patch("app.main.get_fresh_report_by_company", new=AsyncMock(return_value=None)):
                with patch("app.main.NewsService", _FakeNewsService):
                    with patch("app.main.FinnhubService", _FakeFinnhubService):
                        with patch("app.main.CurrencyService", _FakeCurrencyService):
                            with patch("app.main.ScraperService", _FakeScraperService):
                                with patch("app.main.AIService", return_value=_FakeAIService()):
                                    with patch("app.main.create_company_report", new=AsyncMock(return_value=SimpleNamespace(id=1))):
                                        tracemalloc.start()
                                        before = tracemalloc.take_snapshot()
                                        transport = httpx.ASGITransport(app=main.app)
                                        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                                            for _ in range(50):
                                                _ = await self._consume_sse(client)
                                        await asyncio.sleep(0.2)
                                        after = tracemalloc.take_snapshot()
                                        stats = after.compare_to(before, "lineno")
                                        total_growth = sum(max(0, s.size_diff) for s in stats[:25])
                                        tracemalloc.stop()

                                        self.assertLess(total_growth, 4 * 1024 * 1024)
                                        self.assertEqual(len(main.app.state.inflight_report_keys), 0)


if __name__ == "__main__":
    unittest.main()
