import re
from dataclasses import dataclass, asdict
from typing import Optional


@dataclass
class Ato:
    decreto: str
    tipo: str  # "nomeação" | "exoneração" | "outro"
    nome: str
    cargo: Optional[str] = None
    orgao: Optional[str] = None
    data: Optional[str] = None


def extrair_atos(texto: str) -> list[Ato]:
    """Extrai atos de nomeação/exoneração do texto do diário oficial."""
    atos = []

    # Separa por decretos
    decreto_pattern = r"DECRETO\s+N[ºo°.]*\s*(\d+)\s*/\s*(\d{4})"
    matches = list(re.finditer(decreto_pattern, texto, re.IGNORECASE))

    for i, m in enumerate(matches):
        inicio = m.start()
        fim = matches[i + 1].start() if i + 1 < len(matches) else min(inicio + 4000, len(texto))
        bloco = texto[inicio:fim]
        decreto = f"{m.group(1)}/{m.group(2)}"

        # Tipo
        if re.search(r"\bEXONERAR\b|\bEXONERA\b", bloco, re.IGNORECASE):
            tipo = "exoneração"
        elif re.search(r"\bNOMEAR\b|\bNOMEIA\b", bloco, re.IGNORECASE):
            tipo = "nomeação"
        else:
            tipo = "outro"

        # Nome (após "Art. 1º", antes do CPF/cargo)
        nome = None
        nome_pattern = r"Art\.?\s*1[ºo°]?\s+([A-ZÀ-Ú][^,\n]+?)\s*,\s*(?:CPF|do\s+Cargo|para\s+o\s+Cargo)"
        nome_match = re.search(nome_pattern, bloco)
        if nome_match:
            nome = re.sub(r"\s+", " ", nome_match.group(1)).strip()

        # Cargo
        cargo = None
        cargo_pattern = r"Cargo\s+em\s+Comiss[ãa]o\s+de\s+(.+?)\s*,\s*S[íi]mbolo"
        cargo_match = re.search(cargo_pattern, bloco, re.IGNORECASE | re.DOTALL)
        if cargo_match:
            cargo = re.sub(r"\s+", " ", cargo_match.group(1)).strip()

        # Órgão (após "Símbolo XX,")
        orgao = None
        orgao_pattern = r"S[íi]mbolo\s+[^,\n]+,\s*((?:da|do|das|dos)\s+.+?)(?:\.|$)"
        orgao_match = re.search(orgao_pattern, bloco, re.IGNORECASE | re.DOTALL)
        if orgao_match:
            orgao = re.sub(r"\s+", " ", orgao_match.group(1)).strip()
            orgao = re.sub(r"^(?:da|do|das|dos)\s+", "", orgao, flags=re.IGNORECASE)
            orgao = re.split(r",\s*com\s+lota[çc][ãa]o\b", orgao, flags=re.IGNORECASE)[0].strip()
            orgao = re.sub(r",\s*Estado\s+de\s+Sergipe\s*$", "", orgao, flags=re.IGNORECASE)
            orgao = re.sub(r"\s+do\s+Munic[íi]pio\s+de\s+S[ãa]o\s+Crist[óo]v[ãa]o\s*$", "", orgao, flags=re.IGNORECASE).strip(" ,.;")
            orgao = orgao or None

        # Data
        data = None
        data_pattern = r"(\d{1,2}\s+de\s+\w+\s+de\s+\d{4})"
        data_match = re.search(data_pattern, bloco)
        if data_match:
            data = data_match.group(1)

        if nome:
            atos.append(Ato(
                decreto=decreto,
                tipo=tipo,
                nome=nome,
                cargo=cargo,
                orgao=orgao,
                data=data,
            ))

    return atos   
