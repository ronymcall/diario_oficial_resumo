import os
from pathlib import Path

BASE_URL = "https://iose.se.gov.br/prefeitura-sao-cristovao"
IBGE_CODE = "2805703"

OUT_DIR = Path(__file__).parent / "output"
EDICOES_DIR = OUT_DIR / "edicoes"
ATOS_DIR = OUT_DIR / "atos"
RESUMOS_DIR = OUT_DIR / "resumos"

DB_PATH = OUT_DIR / "atos.db"


def get_config(chave: str, padrao: str = "") -> str:
    """Busca configuração nas variáveis de ambiente ou no st.secrets (Streamlit Cloud)."""
    valor = os.getenv(chave)
    if valor:
        return valor
    try:
        import streamlit as st

        if chave in st.secrets:
            return str(st.secrets[chave])
    except Exception:
        pass
    return padrao


for d in (EDICOES_DIR, ATOS_DIR, RESUMOS_DIR):
    d.mkdir(parents=True, exist_ok=True)

