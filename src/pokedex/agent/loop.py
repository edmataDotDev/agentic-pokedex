import anthropic
from pokedex.config import get_settings
from pokedex.agent.system_prompt import SYSTEM_PROMPT
from pokedex.agent.message_history import (
    MessageHistory,
    Message
)
from pokedex.agent.tools import (
    execute_tool,
    TOOLS
)
from anthropic.types import (
    ToolResultBlockParam
)

settings = get_settings()
client = anthropic.Anthropic(
    api_key=settings.anthropic_api_key.get_secret_value()
)

def run_llm_turn(history: MessageHistory) -> None | str:
    response = client.messages.create(
        max_tokens=settings.max_tokens, 
        messages=history.to_list(),
        model=settings.model_name,
        system=SYSTEM_PROMPT,
        tools=TOOLS
    )

    history.add(message=Message(role="assistant", content=response.content))

    match response.stop_reason:
        case "end_turn":
            texts_blocks = [b for b in response.content if b.type == "text"]
            return "".join(b.text for b in texts_blocks)
        case "tool_use":
            tool_use_blocks = [b for b in response.content if b.type == "tool_use"]

            for tool in tool_use_blocks:
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