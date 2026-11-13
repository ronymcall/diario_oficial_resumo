import re
from datetime import date
from pathlib import Path

from curl_cffi import requests as cffi_requests

from config import BASE_URL, EDICOES_DIR

SUBTEMA = BASE_URL.rstrip("/").split("/")[-1]
API_EDICOES = f"{BASE_URL}/apifront/portal/edicoes"


def obter_edicao_do_dia(dia: date | None = None) -> dict | None:
    """Retorna a edição publicada na data informada (padrão: hoje)."""
    dia = dia or date.today()
    resp = cffi_requests.get(
        f"{API_EDICOES}/edicoes_from_data/{dia.isoformat()}.json",
        params={"subtheme": SUBTEMA},
        impersonate="chrome131",
        timeout=30,
    )
    resp.raise_for_status()
    dados = resp.json()

    itens = dados.get("itens") or []
    if not itens:
        return None

    item = next((i for i in itens if not i.get("suplemento")), itens[0])
    return {
        "id": item["id"],
        "numero": item.get("numero", ""),
        "data": item.get("data", dia.strftime("%d/%m/%Y")),
        "titulo": f"Edição {item.get('numero', '')} — {item.get('data', '')}",
        "url": f"{BASE_URL}/portal/edicoes/download/{item['id']}",
    }


def listar_edicoes() -> list[dict]:
    """Lista as edições disponíveis via API do portal."""
    resp = cffi_requests.get(
        f"{API_EDICOES}/ultimas_edicoes.json",
        params={"subtheme": SUBTEMA},
        impersonate="chrome131",
        timeout=30,
    )
    resp.raise_for_status()
    dados = resp.json()

    if dados.get("erro"):
        raise RuntimeError(dados.get("msg") or "Erro ao listar edições")

    edicoes = []
    for item in dados.get("itens", []):
        data = item.get("data", "").replace("/", "-")
        numero = item.get("numero", "")
        suplemento = " (Suplemento)" if item.get("suplemento") else ""
        edicoes.append({
            "titulo": f"Edição {numero} — {data}{suplemento}",
            "url": f"{BASE_URL}/portal/edicoes/download/{item['id']}",
        })
    return edicoes


def baixar_edicao(url: str, nome_arquivo: str = None) -> Path:
    """Baixa o PDF e salva em output/edicoes/."""
    if not nome_arquivo:
        nome_arquivo = url.rstrip("/").split("/")[-1] + ".pdf"
    nome_arquivo = re.sub(r'[\\/:*?"<>|]', "-", nome_arquivo)
    caminho = EDICOES_DIR / nome_arquivo

    if caminho.exists():
        return caminho

    visualizador = re.search(r"/portal/visualizacoes/(?:pdf|html|jornal)/(\d+)", url)
    if visualizador:
        url = f"{BASE_URL}/portal/edicoes/download/{visualizador.group(1)}"

    resp = cffi_requests.get(url, impersonate="chrome131", timeout=60)
    resp.raise_for_status()
    if not resp.content.startswith(b"%PDF"):
        raise RuntimeError("A URL informada não retornou um arquivo PDF.")
    caminho.write_bytes(resp.content)
    return caminho   
