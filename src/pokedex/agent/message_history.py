from typing import Literal

from anthropic.types import (
    MessageParam,
    TextBlockParam,
    ToolResultBlockParam,
    ToolUseBlockParam,
)

Role = Literal["user", "assistant", "system"]
ContentBlock = TextBlockParam | ToolUseBlockParam | ToolResultBlockParam


class Message:
    def __init__(self, role: Role, content: list[ContentBlock]):
        self.role: Role = role
        self.content: list[ContentBlock] = content


class MessageHistory:
    def __init__(self):
        self.messages: list[Message] = []

    def add(self, message: Message) -> None:
        self.messages.append(message)

    def remove(self, index: int) -> None:
        del self.messages[index]

    def to_list(self) -> list[MessageParam]:
        return [MessageParam(role=m.role, content=m.content) for m in self.messages]
