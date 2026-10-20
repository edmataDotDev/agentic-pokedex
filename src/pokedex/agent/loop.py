from concurrent.futures import ThreadPoolExecutor

import anthropic
from pokedex.config import get_settings
from pokedex.agent.system_prompt import SYSTEM_PROMPT
from pokedex.agent.message_history import (
    ContentBlock,
    MessageHistory,
    Message
)
from pokedex.agent.tools import (
    execute_tool,
    TOOLS
)
from anthropic.types import (
    TextBlockParam,
    ToolResultBlockParam
)
from pokedex.cli.service import (
    get_user_input,
    display_message,
    display_tool_calls,
    display_usage,
    clear_screen
)

settings = get_settings()
client = anthropic.Anthropic(
    api_key=settings.anthropic_api_key.get_secret_value(),

)

# USD per 1M tokens for claude-sonnet-5-5 — update these if MODEL_NAME changes model.
PRICE_PER_MILLION_INPUT_TOKENS = 2.00
PRICE_PER_MILLION_OUTPUT_TOKENS = 10.00
PRICE_PER_MILLION_CACHE_WRITE_TOKENS = PRICE_PER_MILLION_INPUT_TOKENS * 1.25
PRICE_PER_MILLION_CACHE_READ_TOKENS = PRICE_PER_MILLION_INPUT_TOKENS * 0.1

total_input_tokens = 0
total_output_tokens = 0
total_cache_write_tokens = 0
total_cache_read_tokens = 0

def run_user_turn(history: MessageHistory) -> None | str:
    user_message = get_user_input()

    if not user_message:
        return None

    history.add(message=Message(
        role="user",
        content=[
            TextBlockParam(
                type="text",
                text=user_message
            )
        ]
    ))

    return user_message

def run_llm_turn(history: MessageHistory) -> None | str:
    response = client.messages.create(
        max_tokens=settings.max_tokens,
        messages=history.to_list(),
        model=settings.model_name,
        system=[
            TextBlockParam(
                type="text",
                text=SYSTEM_PROMPT,
                cache_control={"type": "ephemeral"}
            )
        ],
        tools=TOOLS
    )

    global total_input_tokens, total_output_tokens, total_cache_write_tokens, total_cache_read_tokens
    total_input_tokens += response.usage.input_tokens
    total_output_tokens += response.usage.output_tokens
    total_cache_write_tokens += response.usage.cache_creation_input_tokens or 0
    total_cache_read_tokens += response.usage.cache_read_input_tokens or 0

    content: list[ContentBlock]
    last_block = response.content[-1] if response.content else None
    if last_block is not None and last_block.type == "text":
        content = [*response.content[:-1], TextBlockParam(type="text", text=last_block.text.rstrip())]
    else:
        content = list(response.content)

    history.add(message=Message(role="assistant", content=content))

    match response.stop_reason:
        case "tool_use":
            tool_use_blocks = [b for b in response.content if b.type == "tool_use"]

            display_tool_calls([tool.name for tool in tool_use_blocks])

            with ThreadPoolExecutor(max_workers=settings.max_concurrent_tools) as executor:
                futures = [ 
                    executor.submit(execute_tool, name=tool.name, tool_input=tool.input) 
                    for tool in tool_use_blocks 
                ]

                results = [future.result() for future in futures]

            history.add(message=Message(
                role="user",
                content=[
                    ToolResultBlockParam(
                        tool_use_id=tool.id,
                        type="tool_result",
                        content=text,
                        is_error=isError
                    )
                    for tool, (text, isError) in zip(tool_use_blocks, results)
                ]
            ))
            return None
        case _:
            texts_blocks = [b for b in response.content if b.type == "text"]
            text = "".join(b.text for b in texts_blocks)

            if not text:
                display_message(text=f"stop_reason: {response.stop_reason}", speaker="System")

            return text

def agent_loop() -> MessageHistory:
    history = MessageHistory()

    isUserTurn = True

    clear_screen()

    while True:
        answer = None
        while answer == None:
            if isUserTurn:
                answer = run_user_turn(history=history)
            else:
                answer = run_llm_turn(history=history)
                if answer != None:
                    display_message(text=answer)
                    cost = (
                        total_input_tokens / 1_000_000 * PRICE_PER_MILLION_INPUT_TOKENS
                        + total_output_tokens / 1_000_000 * PRICE_PER_MILLION_OUTPUT_TOKENS
                        + total_cache_write_tokens / 1_000_000 * PRICE_PER_MILLION_CACHE_WRITE_TOKENS
                        + total_cache_read_tokens / 1_000_000 * PRICE_PER_MILLION_CACHE_READ_TOKENS
                    )
                    all_input_tokens = total_input_tokens + total_cache_write_tokens + total_cache_read_tokens
                    display_usage(all_input_tokens, total_output_tokens, cost)

        isUserTurn = not isUserTurn
