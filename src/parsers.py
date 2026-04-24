"""
parsers.py — Extract plain text from PDF, DOCX, and TXT files.
"""

import pathlib


def parse_txt(path: str) -> str:
    """Read a plain text file and return its contents."""
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def parse_pdf(path: str) -> str:
    """Extract text from all pages of a PDF using pdfplumber."""
    import pdfplumber

    pages = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                pages.append(text)
    return "\n".join(pages)


def parse_docx(path: str) -> str:
    """Extract paragraph text from a DOCX file using python-docx."""
    from docx import Document

    doc = Document(path)
    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
    return "\n".join(paragraphs)


def parse_file(path: str) -> str:
    """Dispatch to the correct parser based on file extension.

    Raises ValueError for unsupported file types.
    """
    ext = pathlib.Path(path).suffix.lower()
    if ext == ".txt":
        return parse_txt(path)
    elif ext == ".pdf":
        return parse_pdf(path)
    elif ext == ".docx":
        return parse_docx(path)
    else:
        raise ValueError(f"Unsupported file type: '{ext}'. Supported: .txt, .pdf, .docx")
