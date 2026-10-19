from rich.console import Console
from rich.markdown import Markdown
from rich.prompt import Prompt

console = Console()


def clear_screen() -> None:
    """Clear the terminal and move the cursor to the top-left, so the chat starts from the top."""
    console.clear()

def get_user_input() -> str:
    """Block until the user types something and hits Enter; return the raw text."""
    return Prompt.ask("[bold cyan]You[/bold cyan]").strip()


def display_message(text: str, *, speaker: str = "Pokédex") -> None:
    """Print a single message to the terminal, labeled by who said it."""
    console.print(f"[bold green]{speaker}:[/bold green]")
    console.print(Markdown(text))


def display_usage(input_tokens: int, output_tokens: int, cost: float) -> None:
    """Print a running token/cost tally; meant to be the last thing printed after a reply."""
    total_tokens = input_tokens + output_tokens
    console.print(
        f"[dim]Tokens — in: {input_tokens:,} · out: {output_tokens:,} · "
        f"total: {total_tokens:,} · est. cost: ${cost:.4f}[/dim]"
    )
