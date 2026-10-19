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
    display_message
)

settings = get_settings()
client = anthropic.Anthropic(
    api_key=settings.anthropic_api_key.get_secret_value(),
    
)

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
        system=SYSTEM_PROMPT,
        tools=TOOLS
    )

    content: list[ContentBlock]
    last_block = response.content[-1] if response.content else None
    if last_block is not None and last_block.type == "text":
        content = [*response.content[:-1], TextBlockParam(type="text", text=last_block.text.rstrip())]
    else:
        content = list(response.content)

    history.add(message=Message(role="assistant", content=content))

    match response.stop_reason:
        case "end_turn":
            texts_blocks = [b for b in response.content if b.type == "text"]
            return "".join(b.text for b in texts_blocks)
        case "tool_use":
            tool_use_blocks = [b for b in response.content if b.type == "tool_use"]

            for tool in tool_use_blocks:
                display_message(text=tool.name + " in progress...", speaker="System")
                text, isError = execute_tool(name=tool.name, tool_input=tool.input)

                history.add(message=Message(
                    role="user",
                    content=[
                        ToolResultBlockParam(
                            tool_use_id=tool.id,
                            type="tool_result",
                            content=text,
                            is_error=isError
                        )
                    ]
                ))
    return None

def agent_loop() -> MessageHistory:
    history = MessageHistory()

    isUserTurn = True

    while True:
        answer = None
        while answer == None:
            if isUserTurn:
                answer = run_user_turn(history=history)
            else:
                answer = run_llm_turn(history=history)
                if answer != None:
                    display_message(text=answer)

        isUserTurn = not isUserTurn
