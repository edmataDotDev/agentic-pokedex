from rich.console import Console
from rich.prompt import Prompt

console = Console()

def get_user_input() -> str:
    """Block until the user types something and hits Enter; return the raw text."""
    return Prompt.ask("[bold cyan]You[/bold cyan]").strip()


def display_message(text: str, *, speaker: str = "Pokédex") -> None:
    """Print a single message to the terminal, labeled by who said it."""
    console.print(f"[bold green]{speaker}:[/bold green] {text}")
