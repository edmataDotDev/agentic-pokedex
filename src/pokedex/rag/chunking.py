import re
from dataclasses import dataclass
from pathlib import Path

HEADING_RE = re.compile(r"^(#{2,3})[ \t]+(.+?)[ \t]*$", re.MULTILINE)

FRONT_MATTER_RE = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)

PARAGRAPH_RE = re.compile(r"\n\s*\n")


@dataclass(frozen=True)
class Chunk:
    pokemon: str
    generation: str
    source: str
    section: str
    text: str


def _parse_front_matter(raw: str) -> tuple[dict[str, str], str]:
    match = FRONT_MATTER_RE.match(raw)
    if match is None:
        return {}, raw
    meta: dict[str, str] = {}
    for line in match.group(1).splitlines():
        key, _, value = line.partition(": ")
        meta[key.strip()] = value.strip()
    return meta, raw[match.end():]


def chunk_markdown(path: Path) -> list[Chunk]:
    meta, body = _parse_front_matter(path.read_text(encoding="utf-8"))
    pokemon = meta.get("pokemon", path.stem)

    headings = list(HEADING_RE.finditer(body))
    chunks: list[Chunk] = []
    current_h2 = ""

    for i, heading in enumerate(headings):
        level, title = len(heading.group(1)), heading.group(2)
        if level == 2:
            current_h2 = title
            section = title
        else:
            section = f"{current_h2} > {title}" if current_h2 else title

        end = headings[i + 1].start() if i + 1 < len(headings) else len(body)
        section_text = body[heading.end():end].strip()

        for paragraph in PARAGRAPH_RE.split(section_text):
            if not paragraph:
                continue
            chunks.append(
                Chunk(
                    pokemon=pokemon,
                    generation=meta.get("generation", ""),
                    source=meta.get("source", ""),
                    section=section,
                    text=f"{pokemon} — {section}\n\n{paragraph}",
                )
            )
    return chunks
