import unittest

from app.api.v1.chat import sse_stream
from app.models.schemas import ChatRequest


class FakeChef:
    async def stream_tokens(self, **_kwargs):
        yield "番茄"
        yield "炒蛋"


class FailingChef:
    async def stream_tokens(self, **_kwargs):
        raise RuntimeError("secret internal error")
        yield ""  # pragma: no cover


async def collect_events(service) -> str:
    payload = ChatRequest(message="推荐一道菜", thread_id="sse-test")
    return "".join([event async for event in sse_stream(service, payload)])


class SseStreamTests(unittest.IsolatedAsyncioTestCase):
    async def test_stream_contains_status_tokens_and_done(self) -> None:
        stream = await collect_events(FakeChef())
        self.assertIn("event: status", stream)
        self.assertIn('event: token\ndata: {"text":"番茄"}', stream)
        self.assertIn("event: done", stream)

    async def test_stream_hides_internal_error(self) -> None:
        stream = await collect_events(FailingChef())
        self.assertIn("event: error", stream)
        self.assertIn("AGENT_ERROR", stream)
        self.assertNotIn("secret internal error", stream)


if __name__ == "__main__":
    unittest.main()
