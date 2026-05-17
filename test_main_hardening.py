import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app import main


class MainHardeningTests(unittest.IsolatedAsyncioTestCase):
    async def test_global_exception_hides_detail_when_not_debug(self):
        with patch.object(main.settings, "debug", False):
            response = await main.global_exception_handler(
                SimpleNamespace(url=SimpleNamespace(path="/boom")),
                RuntimeError("secret detail"),
            )
        body = json.loads(response.body.decode("utf-8"))
        self.assertEqual(response.status_code, 500)
        self.assertEqual(body["message"], "Internal server error")
        self.assertNotIn("detail", body)

    async def test_global_exception_includes_detail_when_debug(self):
        with patch.object(main.settings, "debug", True):
            response = await main.global_exception_handler(
                SimpleNamespace(url=SimpleNamespace(path="/boom")),
                RuntimeError("debug detail"),
            )
        body = json.loads(response.body.decode("utf-8"))
        self.assertEqual(response.status_code, 500)
        self.assertEqual(body.get("detail"), "debug detail")

    async def test_track_background_task_discards_completed_tasks(self):
        main.app.state.background_tasks = set()

        async def _done():
            return 1

        task = asyncio.create_task(_done())
        main._track_background_task(task)
        self.assertIn(task, main.app.state.background_tasks)
        await task
        await asyncio.sleep(0)
        self.assertNotIn(task, main.app.state.background_tasks)

    async def test_save_report_background_handles_timeout(self):
        async def _raise_timeout(awaitable, timeout):
            awaitable.close()
            raise asyncio.TimeoutError

        with patch("app.main.create_company_report", new=AsyncMock()) as _create_report:
            with patch("app.main.asyncio.wait_for", side_effect=_raise_timeout):
                await main._save_report_background(10, {"genel_skor": 40}, {"raw": []})

    async def test_market_analysis_requires_non_empty_fields(self):
        with self.assertRaises(main.HTTPException) as ctx:
            await main.api_market_analysis(main.MarketAnalysisRequest(company_name=" ", full_address=" "))
        self.assertEqual(ctx.exception.status_code, 422)

    async def test_market_analysis_contract_success(self):
        fake_scraped = {"items": [{"title": "yorum", "description": "hizmet iyi"}]}
        fake_analysis = {"pazar_algisi_skoru": 88, "guclu_yonler": ["hizli"], "zayif_yonler": []}

        class _FakeScraperService:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_):
                return None

            async def get_scraped_data(self, *_args, **_kwargs):
                return fake_scraped

        class _FakeAIService:
            async def generate_market_analysis(self, **_kwargs):
                return fake_analysis

        with patch("app.main.ScraperService", return_value=_FakeScraperService()):
            with patch("app.main.AIService", return_value=_FakeAIService()):
                response = await main.api_market_analysis(
                    main.MarketAnalysisRequest(company_name="Nova Cafe", full_address="Ankara")
                )
        body = json.loads(response.body.decode("utf-8"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(body["pazar_algisi_skoru"], 88)

    async def test_retry_once_retries_then_succeeds(self):
        state = {"count": 0}

        async def _op():
            state["count"] += 1
            if state["count"] < 2:
                raise asyncio.TimeoutError
            return "ok"

        result = await main._retry_once(_op, timeout_seconds=1)
        self.assertEqual(result, "ok")
        self.assertEqual(state["count"], 2)

    async def test_report_key_normalizes_inputs(self):
        key1 = main._report_key(1, " Ankara ", " Sub ")
        key2 = main._report_key(1, "ankara", "sub")
        self.assertEqual(key1, key2)


if __name__ == "__main__":
    unittest.main()
