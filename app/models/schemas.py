from __future__ import annotations

import base64
import binascii
import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator


ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_IMAGE_BYTES = 5 * 1024 * 1024
THREAD_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]+$")
DATA_URL_PATTERN = re.compile(
    r"^data:(?P<mime>image/[a-zA-Z0-9.+-]+);base64,(?P<data>[A-Za-z0-9+/=]+)$"
)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    thread_id: str = Field(min_length=1, max_length=100)
    image_data: str | None = Field(default=None, repr=False)

    @field_validator("message")
    @classmethod
    def normalize_message(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("消息不能为空")
        return value

    @field_validator("thread_id")
    @classmethod
    def validate_thread_id(cls, value: str) -> str:
        value = value.strip()
        if not THREAD_ID_PATTERN.fullmatch(value):
            raise ValueError("thread_id 只能包含字母、数字、点、下划线、冒号和短横线")
        return value

    @field_validator("image_data")
    @classmethod
    def validate_image_data(cls, value: str | None) -> str | None:
        if not value:
            return None

        match = DATA_URL_PATTERN.fullmatch(value)
        if not match:
            raise ValueError("图片必须是有效的 Base64 Data URL")

        mime_type = match.group("mime").lower()
        if mime_type not in ALLOWED_IMAGE_TYPES:
            allowed = "、".join(sorted(ALLOWED_IMAGE_TYPES))
            raise ValueError(f"图片类型必须是：{allowed}")

        encoded = match.group("data")
        estimated_size = len(encoded) * 3 // 4 - encoded[-2:].count("=")
        if estimated_size > MAX_IMAGE_BYTES:
            raise ValueError("图片不能超过 5 MB，请压缩后重试")

        try:
            decoded = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("图片 Base64 内容无效") from exc

        signatures_valid = {
            "image/jpeg": decoded.startswith(b"\xff\xd8\xff"),
            "image/png": decoded.startswith(b"\x89PNG\r\n\x1a\n"),
            "image/webp": (
                len(decoded) >= 12
                and decoded.startswith(b"RIFF")
                and decoded[8:12] == b"WEBP"
            ),
        }
        if not signatures_valid[mime_type]:
            raise ValueError("图片内容与声明的文件类型不一致")

        return value


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class MessageHistory(BaseModel):
    messages: list[ChatMessage]
