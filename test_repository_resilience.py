import unittest
from datetime import datetime, timezone
from types import SimpleNamespace

from app.models import Report
from app.repository import create_company_report


class _FakeResult:
    def __init__(self, report):
        self._report = report

    def scalar_one_or_none(self):
        return self._report


class _FakeSession:
    def __init__(self, latest_report=None, fail_commit=False):
        self.latest_report = latest_report
        self.fail_commit = fail_commit
        self.added = []
        self.committed = False
        self.rolled_back = False

    async def execute(self, _stmt):
        return _FakeResult(self.latest_report)

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        if self.fail_commit:
            raise RuntimeError("commit_failed")
        self.committed = True

    async def refresh(self, _obj):
        return None

    async def rollback(self):
        self.rolled_back = True


class RepositoryResilienceTests(unittest.IsolatedAsyncioTestCase):
    async def test_create_company_report_is_idempotent_for_recent_duplicate(self):
        latest = Report(
            company_id=1,
            trust_score=80,
            risk_summary="Ayni",
            market_data="{}",
            created_at=datetime.now(timezone.utc),
        )
        db = _FakeSession(latest_report=latest)
        result = await create_company_report(
            db=db,
            company_id=1,
            ai_data={"genel_skor": 80, "risk_summary": "Ayni"},
            raw_market_data={},
        )
        self.assertIs(result, latest)
        self.assertEqual(db.committed, False)
        self.assertEqual(len(db.added), 0)

    async def test_create_company_report_rolls_back_on_commit_error(self):
        db = _FakeSession(latest_report=None, fail_commit=True)
        with self.assertRaises(RuntimeError):
            await create_company_report(
                db=db,
                company_id=1,
                ai_data={"genel_skor": 70, "risk_summary": "Yeni"},
                raw_market_data={},
            )
        self.assertTrue(db.rolled_back)


if __name__ == "__main__":
    unittest.main()
