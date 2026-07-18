import base64
import unittest

from pydantic import ValidationError

from app.models.schemas import ChatRequest


class ChatRequestTests(unittest.TestCase):
    def test_normalizes_message(self) -> None:
        request = ChatRequest(message="  我有鸡蛋  ", thread_id="test-001")
        self.assertEqual(request.message, "我有鸡蛋")

    def test_rejects_blank_message(self) -> None:
        with self.assertRaises(ValidationError):
            ChatRequest(message="   ", thread_id="test-001")

    def test_rejects_unsafe_thread_id(self) -> None:
        with self.assertRaises(ValidationError):
            ChatRequest(message="你好", thread_id="../../data")

    def test_accepts_small_png_data_url(self) -> None:
        encoded = base64.b64encode(b"\x89PNG\r\n\x1a\nsmall-image").decode("ascii")
        request = ChatRequest(
            message="识别图片",
            thread_id="test-001",
            image_data=f"data:image/png;base64,{encoded}",
        )
        self.assertIsNotNone(request.image_data)

    def test_rejects_unsupported_image_type(self) -> None:
        encoded = base64.b64encode(b"image").decode("ascii")
        with self.assertRaises(ValidationError):
            ChatRequest(
                message="识别图片",
                thread_id="test-001",
                image_data=f"data:image/gif;base64,{encoded}",
            )

    def test_rejects_mismatched_image_signature(self) -> None:
        encoded = base64.b64encode(b"not-a-real-png").decode("ascii")
        with self.assertRaises(ValidationError):
            ChatRequest(
                message="识别图片",
                thread_id="test-001",
                image_data=f"data:image/png;base64,{encoded}",
            )


if __name__ == "__main__":
    unittest.main()
