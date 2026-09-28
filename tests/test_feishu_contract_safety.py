from concurrent.futures import ThreadPoolExecutor
from threading import Lock

import pytest

from integrations.base import AdapterError
from integrations.feishu import FeishuAdapter


PROPOSAL = {"proposal_id": "p", "status": "approved", "idempotency_key": "same", "title": "任务"}


def test_concurrent_identical_mock_writes_use_one_external_call():
    class Client:
        def __init__(self):
            self.calls = 0
            self.lock = Lock()

        def create_task(self, payload, *, idempotency_key):
            with self.lock:
                self.calls += 1
            return {"task_id": "fake-1"}

    client = Client()
    adapter = FeishuAdapter(client=client, enable_external_writes=True)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: adapter.submit_task(PROPOSAL), range(8)))
    assert client.calls == 1
    assert all(result == results[0] for result in results)


def test_mock_write_requires_explicit_enable_and_external_confirmation():
    class SilentClient:
        def create_task(self, payload, *, idempotency_key):
            return {"ok": True}

    with pytest.raises(AdapterError, match="unverified"):
        FeishuAdapter(client=SilentClient()).submit_task(PROPOSAL)
    with pytest.raises(AdapterError, match="task_id"):
        FeishuAdapter(client=SilentClient(), enable_external_writes=True).submit_task(PROPOSAL)
