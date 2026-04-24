"""
processor.py — Build prompts from YAML templates and call LLM APIs with streaming.
Supports Anthropic and OpenAI. Falls back to mock mode when no API key is set.
"""

import os
import pathlib
import time
from typing import Callable, Generator

import yaml
from dotenv import load_dotenv

load_dotenv()

# Resolve paths relative to this file's location
_SRC_DIR = pathlib.Path(__file__).parent
_PROJECT_ROOT = _SRC_DIR.parent
_TEMPLATES_DIR = _PROJECT_ROOT / "templates"
_MOCK_DIR = _PROJECT_ROOT / "mock_responses"


def is_mock_mode() -> bool:
    """Return True if no API key is available in the environment."""
    return not os.getenv("ANTHROPIC_API_KEY") and not os.getenv("OPENAI_API_KEY")


def load_template(name: str) -> list[dict]:
    """Load a YAML template by name (without extension) and return its fields list."""
    path = _TEMPLATES_DIR / f"{name}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Template not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data.get("fields", [])


def build_prompt(
    text: str,
    mode: str,
    template_name: str = "contract",
    custom_question: str = "",
) -> dict:
    """Construct a system + user prompt dict for the given mode.

    Args:
        text: The document text to process.
        mode: One of 'summary', 'extract', or 'qa'.
        template_name: Template name used in extract mode.
        custom_question: Question string used in qa mode.

    Returns:
        dict with keys 'system' and 'user'.
    """
    mode = mode.lower()

    if mode == "summary":
        system = (
            "You are a professional document analyst. "
            "Produce clear, concise bullet-point summaries of documents. "
            "Focus on the most important facts, figures, and decisions."
        )
        user = (
            "Please summarize the following document in structured bullet points. "
            "Group related points under short bold headings where appropriate.\n\n"
            f"DOCUMENT:\n{text}"
        )

    elif mode == "extract":
        fields = load_template(template_name)
        field_lines = "\n".join(
            f"  - {f['name']}: {f.get('description', '')}" for f in fields
        )
        field_names = ", ".join(f['name'] for f in fields)
        system = (
            "You are a precise data extraction engine. "
            "Extract structured information from documents and return valid JSON only. "
            "Do not include any explanation or markdown — output raw JSON."
        )
        user = (
            f"Extract the following fields from the document and return a JSON object "
            f"with these keys: {field_names}.\n\n"
            f"Field descriptions:\n{field_lines}\n\n"
            f"If a field is not found, use null as the value.\n\n"
            f"DOCUMENT:\n{text}"
        )

    elif mode == "qa":
        if not custom_question:
            raise ValueError("A question is required for Q&A mode.")
        system = (
            "You are a helpful document assistant. "
            "Answer questions accurately based solely on the provided document. "
            "If the answer is not in the document, say so clearly."
        )
        user = (
            f"Answer the following question based on the document below.\n\n"
            f"QUESTION: {custom_question}\n\n"
            f"DOCUMENT:\n{text}"
        )

    else:
        raise ValueError(f"Unknown mode: '{mode}'. Choose from: summary, extract, qa.")

    return {"system": system, "user": user}


def call_llm(
    prompt: dict,
    provider: str = "anthropic",
    stream_callback: Callable[[str], None] | None = None,
) -> str:
    """Call the LLM API with streaming and return the full response text.

    Args:
        prompt: Dict with 'system' and 'user' keys from build_prompt().
        provider: 'anthropic' or 'openai'.
        stream_callback: Optional callable invoked with each text chunk as it arrives.

    Returns:
        The complete response text.
    """
    full_text = []

    if provider == "anthropic":
        import anthropic

        client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        with client.messages.stream(
            model="claude-3-5-haiku-20241022",
            max_tokens=2048,
            system=prompt["system"],
            messages=[{"role": "user", "content": prompt["user"]}],
        ) as stream:
            for chunk in stream.text_stream:
                full_text.append(chunk)
                if stream_callback:
                    stream_callback(chunk)

    elif provider == "openai":
        from openai import OpenAI

        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            max_tokens=2048,
            stream=True,
            messages=[
                {"role": "system", "content": prompt["system"]},
                {"role": "user", "content": prompt["user"]},
            ],
        )
        for chunk in response:
            delta = chunk.choices[0].delta.content
            if delta:
                full_text.append(delta)
                if stream_callback:
                    stream_callback(delta)

    else:
        raise ValueError(f"Unknown provider: '{provider}'. Choose 'anthropic' or 'openai'.")

    return "".join(full_text)


def mock_response(doc_name: str, mode: str) -> Generator[str, None, None]:
    """Yield a pre-written mock response word by word to simulate streaming.

    Looks up a file in mock_responses/ based on doc_name and mode.
    Falls back to a generic placeholder if no matching file is found.

    Args:
        doc_name: The filename of the uploaded document (basename).
        mode: One of 'summary', 'extract', or 'qa'.

    Yields:
        Individual words (with trailing space) from the mock response.
    """
    mode = mode.lower()
    stem = pathlib.Path(doc_name).stem.lower()  # e.g. "sample_contract"

    # Determine which mock file to use
    candidate = None
    if mode == "extract" and "contract" in stem:
        candidate = _MOCK_DIR / "contract_extract.json"
    elif mode == "summary" and "contract" in stem:
        candidate = _MOCK_DIR / "contract_summary.txt"
    elif mode == "summary" and "report" in stem:
        candidate = _MOCK_DIR / "report_summary.txt"

    if candidate and candidate.exists():
        text = candidate.read_text(encoding="utf-8")
    else:
        text = (
            f"[Mock mode] No pre-written response found for '{doc_name}' in '{mode}' mode.\n"
            "Set ANTHROPIC_API_KEY or OPENAI_API_KEY in your .env file to use live AI processing."
        )

    # Yield word by word with a small delay to simulate streaming
    words = text.split(" ")
    for i, word in enumerate(words):
        chunk = word if i == len(words) - 1 else word + " "
        yield chunk
        time.sleep(0.03)
