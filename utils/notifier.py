import requests
from dotenv import load_dotenv

from config import get_config

load_dotenv()


def _dividir_mensagem(texto: str, limite: int = 4000) -> list[str]:
    """Divide o texto em partes que caibam no limite do Telegram."""
    partes = []
    restante = texto
    while restante:
        corte = restante.rfind("\n", 0, limite)
        if corte <= 0:
            corte = min(limite, len(restante))
        partes.append(restante[:corte])
        restante = restante[corte:].lstrip("\n")
    return partes


def enviar_telegram(mensagem: str) -> bool:
    """Envia mensagem via Telegram Bot. Retorna True se o envio funcionou."""
    token = get_config("TELEGRAM_BOT_TOKEN")
    chat_id = get_config("TELEGRAM_CHAT_ID")
    if not token or not chat_id or not mensagem.strip():
        return False

    try:
        for parte in _dividir_mensagem(mensagem):
            resposta = requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": parte},
                timeout=10,
            )
            resposta.raise_for_status()
    except requests.RequestException:
        return False
    return True
