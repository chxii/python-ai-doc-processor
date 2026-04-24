"""
app.py — Gradio UI for batch document processing with LLM APIs.

Supports PDF, DOCX, and TXT files. Modes: Summary, Extract, Q&A.
Runs in mock mode (no API key required) for demo purposes.
"""

import os
import pathlib
import sys
import tempfile

import gradio as gr
from dotenv import load_dotenv

load_dotenv()

# Allow running as `python src/app.py` from the project root
_SRC_DIR = pathlib.Path(__file__).parent
_PROJECT_ROOT = _SRC_DIR.parent
sys.path.insert(0, str(_SRC_DIR))

from parsers import parse_file
from processor import build_prompt, call_llm, is_mock_mode, mock_response
from exporter import to_json, to_excel

# ── State shared across a session ────────────────────────────────────────────
_last_results: list[dict] = []


def _get_provider() -> str:
    """Pick the first available LLM provider based on env keys."""
    if os.getenv("ANTHROPIC_API_KEY"):
        return "anthropic"
    if os.getenv("OPENAI_API_KEY"):
        return "openai"
    return "anthropic"  # won't be reached in mock mode


def process_documents(files, mode: str, template: str, question: str):
    """Main processing generator — yields streaming text to the output box.

    Iterates over uploaded files, parses each one, builds a prompt, and
    streams the LLM (or mock) response into the Gradio textbox.
    """
    global _last_results
    _last_results = []

    if not files:
        yield "Please upload at least one document to process."
        return

    mode_key = mode.lower()  # "summary" | "extract" | "q&a"
    if mode_key == "q&a":
        mode_key = "qa"

    template_key = template.lower()  # "contract" | "report" | "general"

    accumulated = ""

    for file_obj in files:
        file_path = file_obj.name if hasattr(file_obj, "name") else str(file_obj)
        filename = pathlib.Path(file_path).name

        accumulated += f"── {filename} ──\n"
        yield accumulated

        # Parse document text
        try:
            text = parse_file(file_path)
        except Exception as e:
            error_msg = f"[Error reading file: {e}]\n\n"
            accumulated += error_msg
            yield accumulated
            continue

        if not text.strip():
            accumulated += "[File appears to be empty or unreadable]\n\n"
            yield accumulated
            continue

        result_chunks = []

        if is_mock_mode():
            # Stream mock response word by word
            for chunk in mock_response(filename, mode_key):
                result_chunks.append(chunk)
                accumulated += chunk
                yield accumulated
        else:
            # Build prompt and call live LLM
            try:
                tpl = template_key if template_key != "general" else "contract"
                prompt = build_prompt(
                    text=text,
                    mode=mode_key,
                    template_name=tpl,
                    custom_question=question,
                )
            except Exception as e:
                accumulated += f"[Prompt error: {e}]\n\n"
                yield accumulated
                continue

            def _on_chunk(chunk: str):
                nonlocal accumulated
                result_chunks.append(chunk)
                accumulated += chunk

            try:
                call_llm(prompt, provider=_get_provider(), stream_callback=_on_chunk)
                yield accumulated
            except Exception as e:
                accumulated += f"[LLM error: {e}]\n\n"
                yield accumulated
                continue

        result_text = "".join(result_chunks)
        _last_results.append({
            "filename": filename,
            "mode": mode_key,
            "result": result_text,
        })

        accumulated += "\n\n"
        yield accumulated

    if not _last_results:
        return

    accumulated += "─" * 40 + "\nProcessing complete.\n"
    yield accumulated


def export_json_handler():
    """Write results to a temp JSON file and return it for download."""
    if not _last_results:
        return None
    combined = {
        item["filename"]: {
            "mode": item["mode"],
            "result_raw": item["result"],
            "result_parsed": _try_parse_json(item["result"]),
        }
        for item in _last_results
    }
    import json
    tmp = tempfile.NamedTemporaryFile(
        delete=False, suffix=".json", mode="w", encoding="utf-8"
    )
    json.dump(combined, tmp, indent=2, ensure_ascii=False)
    tmp.close()
    return tmp.name


def export_excel_handler():
    """Write results to a temp Excel file and return it for download."""
    if not _last_results:
        return None
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx")
    tmp.close()
    to_excel(_last_results, tmp.name)
    return tmp.name


def _try_parse_json(text: str):
    import json
    try:
        return json.loads(text)
    except Exception:
        return None


def _update_visibility(mode: str):
    """Show/hide template dropdown and question box based on selected mode."""
    show_template = mode == "Extract"
    show_question = mode == "Q&A"
    return (
        gr.update(visible=show_template),
        gr.update(visible=show_question),
    )


# ── Build Gradio UI ───────────────────────────────────────────────────────────

MOCK_BANNER = (
    "⚠ Running in demo mode — using pre-written responses. "
    "Set ANTHROPIC_API_KEY or OPENAI_API_KEY in your .env file to use live AI."
)

_CSS = """
    .mock-banner {
        background: #fff8c5;
        border: 1px solid #e6c84a;
        border-radius: 6px;
        padding: 10px 16px;
        color: #7a5c00;
        font-size: 0.92em;
    }
    .export-row { margin-top: 8px; }
"""

with gr.Blocks(title="AI Document Processor") as demo:

    gr.Markdown("# AI Document Processor")
    gr.Markdown(
        "Batch-process PDF, DOCX, and TXT documents — extract structured data, "
        "generate summaries, or answer questions. Results export to JSON or Excel."
    )

    # Mock mode banner (only shown when no API key is set)
    if is_mock_mode():
        gr.HTML(f'<div class="mock-banner">{MOCK_BANNER}</div>')

    with gr.Row():
        file_upload = gr.File(
            label="Upload Documents",
            file_count="multiple",
            file_types=[".pdf", ".docx", ".txt"],
            scale=3,
        )
        mode_radio = gr.Radio(
            choices=["Summary", "Extract", "Q&A"],
            value="Summary",
            label="Processing Mode",
            scale=1,
        )

    template_dropdown = gr.Dropdown(
        choices=["Contract", "Report", "General"],
        value="Contract",
        label="Extraction Template",
        visible=False,
        interactive=True,
    )

    question_box = gr.Textbox(
        label="Your Question",
        placeholder="e.g. What are the payment terms?",
        visible=False,
        lines=2,
    )

    process_btn = gr.Button("Process Documents", variant="primary")

    output_box = gr.Textbox(
        label="Result",
        lines=20,
        max_lines=40,
        interactive=False,
    )

    with gr.Row(elem_classes="export-row"):
        export_json_btn = gr.Button("Export JSON", variant="secondary")
        export_excel_btn = gr.Button("Export Excel", variant="secondary")

    json_download = gr.File(label="Download JSON", visible=False)
    excel_download = gr.File(label="Download Excel", visible=False)

    # ── Event wiring ─────────────────────────────────────────────────────────

    mode_radio.change(
        fn=_update_visibility,
        inputs=[mode_radio],
        outputs=[template_dropdown, question_box],
    )

    process_btn.click(
        fn=process_documents,
        inputs=[file_upload, mode_radio, template_dropdown, question_box],
        outputs=[output_box],
    )

    export_json_btn.click(
        fn=export_json_handler,
        inputs=[],
        outputs=[json_download],
    ).then(
        fn=lambda path: gr.update(visible=path is not None, value=path),
        inputs=[json_download],
        outputs=[json_download],
    )

    export_excel_btn.click(
        fn=export_excel_handler,
        inputs=[],
        outputs=[excel_download],
    ).then(
        fn=lambda path: gr.update(visible=path is not None, value=path),
        inputs=[excel_download],
        outputs=[excel_download],
    )


if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=7860, share=False,
                theme=gr.themes.Soft(), css=_CSS)
