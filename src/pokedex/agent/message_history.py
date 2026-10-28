from collections.abc import Sequence
from typing import Literal, cast

from anthropic.types import ContentBlock as ResponseContentBlock
from anthropic.types import (
    MessageParam,
    TextBlockParam,
    ToolResultBlockParam,
    ToolUseBlockParam,
)

Role = Literal["user", "assistant", "system"]
ContentBlock = TextBlockParam | ToolUseBlockParam | ToolResultBlockParam | ResponseContentBlock


class Message:
    def __init__(self, role: Role, content: Sequence[ContentBlock]):
        self.role: Role = role
        self.content: Sequence[ContentBlock] = content


class MessageHistory:
    def __init__(self):
        self.messages: list[Message] = []

    def add(self, message: Message) -> None:
        self.messages.append(message)

    def remove(self, index: int) -> None:
        del self.messages[index]

    def to_list(self) -> list[MessageParam]:
        cache_breakpoint_index = len(self.messages) - 2

        params = []
        for i, m in enumerate(self.messages):
            content = list(m.content)
            if i == cache_breakpoint_index:
                last_block = content[-1]
                last_block_dict = (
                    last_block if isinstance(last_block, dict)
                    else last_block.model_dump(exclude_unset=True)
                )
                content[-1] = cast(ContentBlock, {**last_block_dict, "cache_control": {"type": "ephemeral"}})
            params.append(MessageParam(role=m.role, content=content))

        return params
