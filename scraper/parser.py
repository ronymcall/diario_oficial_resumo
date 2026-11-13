import pymupdf
from pathlib import Path


def extrair_texto_pdf(caminho: Path) -> str:
    """Extrai todo o texto de um arquivo PDF."""
    doc = pymupdf.open(str(caminho))
    texto = "\n".join(page.get_text() for page in doc)
    doc.close()
    return texto   
