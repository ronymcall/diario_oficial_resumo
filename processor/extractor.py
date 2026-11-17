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
    detalhes: Optional[str] = None
    texto_original: Optional[str] = None


_MESES = (
    r"(?:janeiro|fevereiro|mar[çc]o|abril|maio|junho|"
    r"julho|agosto|setembro|outubro|novembro|dezembro)"
)

_PADROES_CABECALHO_PAGINA = [
    r"Documento\s+Assinado\s+Digitalmente\s+com\s+certificado\s+digital[\s\S]*?DO\s+MUNIC[ÍI]PIO\s+DE\s+S[ÃA]O\s+CRIST[ÓO]V[ÃA]O",
    r"Documento\s+Assinado\s+Digitalmente\s+com\s+certificado\s+digital[^\n]*(?:\n(?:Brasileira[^\n]*|Autoridade\s+Certificadora[^\n]*|(?:Segunda|Ter[çc]a|Quarta|Quinta|Sexta|S[áa]bado|Domingo)[^\n]*))*",
    r"Essa\s+edi[çc][ãa]o\s+encontra-se\s+no\s+site:[^\n]*",
    r"Edi[çc][ãa]o\s+de\s+[^\n]+\s*\n\s*Ano\s+[IVXLCDM]+\s*-\s*N[ºo°.]*\s*[\d.]+\s*(?:\n\s*\d+\s*)?(?:\n\s*DI[ÁA]RIO\s+OFICIAL)?(?:\n\s*DO\s+MUNIC[ÍI]PIO\s+DE\s+S[ÃA]O\s+CRIST[ÓO]V[ÃA]O)?",
    r"<#SEGRASE#[^>]*>",
]


def _limpar_ruido_pagina(texto: str) -> str:
    """Remove rodapés/cabeçalhos de quebra de página que interrompem frases."""
    limpo = texto
    for padrao in _PADROES_CABECALHO_PAGINA:
        limpo = re.sub(padrao, " ", limpo, flags=re.IGNORECASE)
    return limpo


def _normalizar_espacos(texto: Optional[str]) -> Optional[str]:
    if not texto:
        return None
    limpo = re.sub(r"\s+", " ", texto).strip(" ,.;:-\n\t")
    return limpo or None


def _limpar_orgao(orgao: Optional[str]) -> Optional[str]:
    if not orgao:
        return None
    s = re.sub(r"\s+", " ", orgao).strip()
    s = re.sub(r"^(?:na|no|nas|nos|da|do|das|dos|pela|pelo)\s+", "", s, flags=re.IGNORECASE)
    s = re.split(r",\s*com\s+lota[çc][ãa]o\b", s, flags=re.IGNORECASE)[0]
    s = re.split(
        r",\s*(?:com\s+efeito|referente|retroagindo|produzindo|deste\s+Munic[íi]pio|sob\s+condi[çc][ãa]o|conforme\b)",
        s,
        flags=re.IGNORECASE,
    )[0]
    s = re.sub(r",?\s*Estado\s+de\s+Sergipe.*$", "", s, flags=re.IGNORECASE)
    s = re.sub(
        r",?\s*(?:do|deste)\s+Munic[íi]pio(?:\s+de\s+S[ãa]o\s+Crist[óo]v[ãa]o)?.*$",
        "",
        s,
        flags=re.IGNORECASE,
    )
    s = re.sub(r"^Secret[áa]rio\s+Municipal\b", "Secretaria Municipal", s, flags=re.IGNORECASE)
    s = s.strip(" ,.;:-")
    if not s or re.fullmatch(
        r"(?:Munic[íi]pio(?:\s+de\s+S[ãa]o\s+Crist[óo]v[ãa]o)?|Prefeitura(?:\s+deste\s+Munic[íi]pio)?)",
        s,
        flags=re.IGNORECASE,
    ):
        return None
    return s


def _limpar_cargo(cargo: Optional[str]) -> Optional[str]:
    if not cargo:
        return None
    s = re.sub(r"\s+", " ", cargo).strip(" ,.;:-")
    s = re.sub(
        r"^(?:o\s+|a\s+)?(?:Cargo\s+em\s+Comiss[ãa]o\s+de|Cargo\s+efetivo\s+de|Cargo\s+de|ocupante\s+do\s+cargo(?:\s+efetivo)?\s+de|ocupante\s+de\s+cargo\s+efetivo\s*,?\s*|servidor(?:a)?\s+de\s+cargo\s+efetivo\s*,?\s*|cargo\s+efetivo\s+de|de\s+(?=Agente|Professor|Auxiliar|Secret[áa]ri|Executor|Trabalhador|Servente|Guarda))\s*",
        "",
        s,
        flags=re.IGNORECASE,
    )
    s = re.sub(r",\s*S[íi]mbolo.*$", "", s, flags=re.IGNORECASE)
    s = re.sub(
        r",?\s*(?:do|deste)\s+Munic[íi]pio(?:\s+de\s+S[ãa]o\s+Crist[óo]v[ãa]o)?.*$",
        "",
        s,
        flags=re.IGNORECASE,
    )
    s = re.sub(
        r",?\s*da\s+Prefeitura(?:\s+deste\s+Munic[íi]pio|\s+Municipal)?.*$",
        "",
        s,
        flags=re.IGNORECASE,
    )
    # Corrige erros comuns de digitação em diários (ex.: Escritporio -> Escritório)
    s = re.sub(r"\bEscritporio\b", "Escritório", s, flags=re.IGNORECASE)
    s = s.strip(" ,.;:-")
    if not s or s.lower() == "efetivo":
        return None
    return s


def _limpar_nome(nome: Optional[str]) -> Optional[str]:
    if not nome:
        return None
    s = re.sub(r"\s+", " ", nome).strip(" ,.;:-")
    s = re.sub(
        r"^(?:(?:DESIGNAR|LOTAR|REMOVER|REINTEGRAR|NOMEAR|EXONERAR)\s+)?(?:o\s+servidor(?:\s+efetivo)?|a\s+servidora(?:\s+efetiva)?|ao\s+servidor(?:\s+efetivo)?|à\s+servidora(?:\s+efetiva)?|servidor(?:a)?(?:\s+efetiv[oa])?|Sr\.?[ºªo°]*|Sra\.?[ªa°]*)\s+",
        "",
        s,
        flags=re.IGNORECASE,
    )
    s = re.sub(
        r"\s*,?\s*(?:servidor(?:a)?\s+(?:de\s+cargo\s+efetivo|efetiv[oa]|p[úu]blic[oa])|ocupante\s+d[eo]\s+cargo.*|inscrit[oa]\s+no\s+CPF.*)$",
        "",
        s,
        flags=re.IGNORECASE,
    )
    s = s.strip(" ,.;:-")
    # Nome válido deve ter ao menos duas palavras e letras maiúsculas
    if len(s.split()) < 2 or len(s) > 120:
        return None
    # Evita capturar iniciais de sindicância (ex: M.T.S.)
    if re.fullmatch(r"(?:[A-Z]\.?\s*){2,5}", s):
        return None
    return s


def _extrair_orgao_assinatura(bloco: str) -> Optional[str]:
    """Extrai o órgão da autoridade co-signatária ou do preâmbulo quando não explícito no Art. 1º."""
    m_pre = re.search(
        r"juntamente\s+com\s+[oa]\s+SECRET[ÁA]RI[OA]\s+MUNICIPAL\s+(?:DE|DA|DO)\s+([A-ZÀ-Ú\s]+?)(?:,|\s+no\s+uso)",
        bloco,
        re.IGNORECASE,
    )
    if m_pre:
        nome_sec = re.sub(r"\s+", " ", m_pre.group(1)).strip()
        return _limpar_orgao(f"Secretaria Municipal de {nome_sec.title()}")

    # Procura nas linhas finais a assinatura de Secretário(a) específico (exceto Governo e Gestão quando há outro)
    matches = re.findall(
        r"Secret[áa]ri[oa]\s+Municipal\s+(?:de|da|do)\s+([^\n]+)",
        bloco,
        re.IGNORECASE,
    )
    for m in reversed(matches):
        cand = _limpar_orgao(f"Secretaria Municipal de {m}")
        if cand and "governo" not in cand.lower():
            return cand
    return None


def _extrair_ementa_ou_art1(bloco: str, corpo: str) -> tuple[Optional[str], Optional[str]]:
    """Extrai o resumo/ementa do ato e o texto limpo dos artigos para consulta detalhada."""
    # Texto original a partir do cabeçalho sem ruído excessivo
    linhas = [re.sub(r"\s+", " ", ln).strip() for ln in bloco.strip().splitlines() if ln.strip()]
    texto_limpo = "\n".join(linhas[:25])

    # Ementa: geralmente fica entre a data do topo e "O PREFEITO / A SUPERINTENDENTE / A SECRETÁRIA"
    m_ementa = re.search(
        rf"^\s*(?:DECRETO|PORTARIA)[^\n]*\n\s*(?:DE\s+)?\d{{1,2}}\s*DE\s*{_MESES}\s*DE\s*\d{{4}}\s*\n(.+?)(?=\n\s*(?:O\s+PREFEITO|A\s+SUPERINTENDENTE|A\s+SECRET[ÁA]RIA|O\s+SECRET[ÁA]RIO|O\s+MUNIC[ÍI]PIO|A\s+MESA))",
        bloco,
        re.IGNORECASE | re.DOTALL,
    )
    ementa = None
    if m_ementa:
        cand = re.sub(r"\s+", " ", m_ementa.group(1)).strip(" .;-")
        cand = re.sub(r"^REPUBLICADO\s+POR\s+INCORRE[ÇC][ÃA]O\s*", "", cand, flags=re.IGNORECASE).strip()
        if 10 <= len(cand) <= 300:
            ementa = cand

    # Se não tiver ementa no topo (comum em algumas portarias), usa o Art. 1º resumido
    if not ementa:
        m_art1 = re.search(r"(Art\.?\s*1[ºo°]?\s*.+?)(?=\s*Art\.?\s*2|\s*São\s+Crist[óo]v[ãa]o|\s*Munic[íi]pio\s+de|$)", corpo, re.IGNORECASE | re.DOTALL)
        if m_art1:
            ementa = re.sub(r"\s+", " ", m_art1.group(1)).strip()

    return ementa, texto_limpo


def _extrair_cargo_e_orgao_comissionado(bloco: str) -> tuple[Optional[str], Optional[str]]:
    """Extrai cargo e órgão de estruturas com 'Cargo em Comissão de ..., Símbolo ..., da/do ...'."""
    cargo = None
    orgao = None

    m_cargo = re.search(
        r"Cargo\s+em\s+Comiss[ãa]o\s+de\s+(.+?)\s*,\s*S[íi]mbolo\s+[A-Z0-9-]+",
        bloco,
        re.IGNORECASE | re.DOTALL,
    )
    if m_cargo:
        cargo = _limpar_cargo(m_cargo.group(1))

    m_orgao = re.search(
        r"S[íi]mbolo\s+[^,\n]+,\s*(?:na\s+fun[çc][ãa]o\s+de\s+.+?\s+(?:da|do|das|dos)\s+|(?:da|do|das|dos)\s+)(.+?)(?:\.\s|\n\s*Art\.|$)",
        bloco,
        re.IGNORECASE | re.DOTALL,
    )
    if m_orgao:
        texto_orgao = m_orgao.group(1)
        orgao = _limpar_orgao(texto_orgao)

    return cargo, orgao


def _extrair_cargo_e_orgao_secretario(bloco: str) -> tuple[Optional[str], Optional[str]]:
    """Extrai cargo (e órgão inferido) quando o ato nomeia/exonera Secretário ou Chefe."""
    m = re.search(
        r"Cargo\s+de\s+((?:Secret[áa]ri[oa](?:\s+Municipal)?(?:\s+Adjunt[oa])?(?:\s+Chefe)?|Procurador(?:a)?\s+Geral|Controlador(?:a)?\s+Geral).+?)(?:,\s*Estado\s+de\s+Sergipe|\.\s|\n\s*Art\.|$)",
        bloco,
        re.IGNORECASE | re.DOTALL,
    )
    if not m:
        m = re.search(
            r"(?:Exonera|Nomeia)\s+((?:Secret[áa]ri[oa](?:\s+Municipal)?(?:\s+Adjunt[oa])?(?:\s+Chefe)?|Procurador(?:a)?\s+Geral|Controlador(?:a)?\s+Geral).+?)(?:,\s*Estado\s+de\s+Sergipe|\.\s|\n\s*O\s+PREFEITO|$)",
            bloco,
            re.IGNORECASE | re.DOTALL,
        )
    if not m:
        return None, None

    cargo = _limpar_cargo(m.group(1))
    orgao = None
    if cargo:
        if re.match(r"^Secret[áa]ri[oa]\s+Chefe\s+(?:da|do)\s+", cargo, flags=re.IGNORECASE):
            # Como o usuário apontou, em cargos como "Secretário Chefe da Assessoria de Relações Institucionais"
            # o decreto não traz um órgão separado (é o próprio cargo). Mantemos orgao = None.
            orgao = None
        elif re.match(r"^Secret[áa]ri[oa]\s+Municipal\b", cargo, flags=re.IGNORECASE):
            orgao = re.sub(r"^Secret[áa]ri[oa]\b", "Secretaria", cargo, flags=re.IGNORECASE)
            orgao = _limpar_orgao(orgao)
    return cargo, orgao


def _extrair_atos_conselho(bloco: str, doc_id: str, data: Optional[str]) -> list[Ato]:
    """Extrai exonerações e nomeações de membros de conselhos (ex.: Decreto 659/2026 e 689/2026)."""
    atos = []
    detalhes_ato, texto_orig = _extrair_ementa_ou_art1(bloco, bloco)
    artigos = re.split(r"(?=\bArt\.?\s*\d+[ºo°]?)", bloco)
    for art in artigos:
        if re.search(r"\bexonerad[oa]\b", art, re.IGNORECASE):
            tipo = "exoneração"
        elif re.search(r"\bnomead[oa]\b", art, re.IGNORECASE):
            tipo = "nomeação"
        else:
            continue

        m_nome = re.search(
            r"(?:Titular|Suplente|Membro|Conselheir[oa])\s*:\s*([A-ZÀ-Úa-zà-ú][^\n,]+?)(?:\s*,?\s*CPF|\n|$)",
            art,
            re.IGNORECASE,
        )
        if not m_nome:
            continue
        nome = _limpar_nome(m_nome.group(1))
        if not nome:
            continue

        m_cargo = re.search(
            r"(Conselheir[oa]\s+[^\n.,:]+?)(?=\s*,\s*representante|\.|Secretaria|Funda[çc][ãa]o|:|$)",
            art,
            re.IGNORECASE | re.DOTALL,
        )
        cargo = _limpar_cargo(m_cargo.group(1)) if m_cargo else "Conselheiro(a)"

        m_orgao = re.search(
            r"(?:representantes?\s+(?:da|do)\s+)?((?:Secretaria|Funda[çc][ãa]o|Procuradoria|Gabinete)\s+[^\n:]+?)(?:\s*-\s*[A-Z]+\s*)?(?::|\n)\s*(?:Titular|Suplente|Membro)",
            art,
            re.IGNORECASE | re.DOTALL,
        )
        orgao = _limpar_orgao(m_orgao.group(1)) if m_orgao else _extrair_orgao_assinatura(bloco)

        atos.append(
            Ato(
                decreto=doc_id,
                tipo=tipo,
                nome=nome,
                cargo=cargo,
                orgao=orgao,
                data=data,
                detalhes=detalhes_ato,
                texto_original=texto_orig,
            )
        )
    return atos


def _extrair_ato_bloco(doc_tipo: str, doc_num: str, bloco_bruto: str) -> list[Ato]:
    bloco = _limpar_ruido_pagina(bloco_bruto)
    doc_id = f"{doc_num}" if doc_tipo.upper() == "DECRETO" else f"Portaria {doc_num}"

    # Ignora portarias de fiscal/gestor de contrato ou ata e instauração/prorrogação de sindicância
    if re.search(
        r"exercerem\s+as\s+fun[çc][õo]es\s+de\s+Gestor\s+e\s+Fiscal|"
        r"Instaurar\s+(?:Processo\s+de\s+)?Sindic[âa]ncia|"
        r"prazo\s+para\s+conclus[ãa]o\s+(?:dos\s+trabalhos\s+)?da\s+Sindic[âa]ncia|"
        r"declara(?:da)?\s+de\s+utilidade\s+p[úu]blica|"
        r"Comiss[ãa]o\s+Eleitoral|"
        r"Comiss[ãa]o\s+T[ée]cnica\s+Multidisciplinar|"
        r"Comiss[ãa]o\s+Especial\s+de\s+Acompanhamento|"
        r"renova[çc][ãa]o\s+da\s+comiss[ãa]o\s+respons[áa]vel|"
        r"Delega\s+compet[êe]ncias\s+do\s+Secret[áa]rio",
        bloco,
        re.IGNORECASE,
    ):
        return []

    # Data do ato (prioriza a data do cabeçalho logo no início do bloco)
    data = None
    m_data_topo = re.search(
        rf"^\s*(?:DECRETO|PORTARIA)[^\n]*\n\s*(?:DE\s+)?(\d{{1,2}}\s*DE\s*{_MESES}\s*DE\s*\d{{4}})",
        bloco,
        re.IGNORECASE,
    )
    if m_data_topo:
        data = re.sub(r"\s+", " ", m_data_topo.group(1)).strip().lower()
        data = re.sub(r"(\d+)\s*de\s*", r"\1 de ", data)
        data = re.sub(r"\s*de\s*(\d{4})", r" de \1", data)
        data = re.sub(r"\s+", " ", data).strip()
    else:
        m_data = re.search(rf"(\d{{1,2}}\s+de\s+{_MESES}\s+de\s+\d{{4}})", bloco, re.IGNORECASE)
        if m_data:
            data = re.sub(r"\s+", " ", m_data.group(1)).strip().lower()

    # Caso especial: Decreto de conselho com múltiplos artigos (exoneração + nomeação)
    if re.search(r"Conselho\s+Municipal", bloco, re.IGNORECASE) and re.search(
        r"Fica\s+(?:exonerad|nomead)", bloco, re.IGNORECASE
    ):
        atos_conselho = _extrair_atos_conselho(bloco, doc_id, data)
        if atos_conselho:
            return atos_conselho

    # Isola a seção a partir de RESOLVE / DECRETA / verbo de ação para não capturar preâmbulo
    pos_acao = re.search(
        r"(?:resolve\s*[:,]?|DECRETA\s*[:,]?|\n\s*(?:NOMEAR|EXONERAR|LOTAR|DESIGNAR|REMOVER|REINTEGRAR|TORNAR\s+SEM\s+EFEITO|CONCEDER|DEFERIR|DISPENSAR|SUSPENDER)\b)",
        bloco,
        re.IGNORECASE,
    )
    corpo = bloco[pos_acao.start() :] if pos_acao else bloco

    # Determina o tipo do ato
    tipo = "outro"
    subtipo_rotulo = None

    if re.search(r"\bTORNAR\s+SEM\s+EFEITO\b", corpo, re.IGNORECASE):
        tipo = "outro"
        subtipo_rotulo = "Tornar sem efeito"
    elif re.search(r"\bEXONERAR\b|\bExonera\b", bloco, re.IGNORECASE):
        tipo = "exoneração"
    elif re.search(r"\bNOMEAR\b|\bNomeia\b|\bFica\s+nomead[oa]\b", bloco, re.IGNORECASE):
        tipo = "nomeação"
    elif re.search(r"\bLOTAR\b", corpo, re.IGNORECASE):
        tipo = "outro"
        subtipo_rotulo = "Lotação"
    elif re.search(r"\bDESIGNAR\b", corpo, re.IGNORECASE):
        tipo = "outro"
        subtipo_rotulo = "Designação"
    elif re.search(r"\bREMOVER\b", corpo, re.IGNORECASE):
        tipo = "outro"
        subtipo_rotulo = "Remoção"
    elif re.search(r"\bREINTEGRAR\b", corpo, re.IGNORECASE):
        tipo = "outro"
        subtipo_rotulo = "Reintegração"
    elif re.search(r"\bcess[ãa]o\s+de\b", corpo, re.IGNORECASE):
        tipo = "outro"
        subtipo_rotulo = "Cessão"
    elif re.search(r"\bLICEN[ÇC]A\s+PR[ÊE]MIO\b", corpo, re.IGNORECASE):
        tipo = "outro"
        subtipo_rotulo = "Licença Prêmio"
    elif re.search(r"\bMudan[çc]a\s+de\s+N[íi]vel\b", corpo, re.IGNORECASE):
        tipo = "outro"
        subtipo_rotulo = "Mudança de Nível"
    elif re.search(r"\bGratifica[çc][ãa]o\s+por\s+Tempo\s+Integral\b", corpo, re.IGNORECASE):
        if re.search(r"\bDISPENSAR\b", corpo, re.IGNORECASE):
            subtipo_rotulo = "Dispensa de Gratificação"
        else:
            subtipo_rotulo = "Gratificação Tempo Integral"
        tipo = "outro"
    elif re.search(r"\bredu[çc][ãa]o\s+d[ae]\s+carga\s+hor[áa]ria\b|\bhor[áa]rio\s+especial\b", corpo, re.IGNORECASE):
        if re.search(r"\bSUSPENDER\b|\bSuspende\b", corpo, re.IGNORECASE):
            subtipo_rotulo = "Suspensão de Redução de Carga Horária"
        else:
            subtipo_rotulo = "Redução de Carga Horária"
        tipo = "outro"
    elif re.search(r"\bVAC[ÂA]NCIA\b", corpo, re.IGNORECASE):
        tipo = "outro"
        subtipo_rotulo = "Vacância"

    multiplos = _extrair_multiplos_art1(corpo, doc_id, tipo, subtipo_rotulo, data, bloco)
    if multiplos:
        return multiplos

    return _extrair_dados_servidor(corpo, doc_id, tipo, subtipo_rotulo, data, bloco)


def _extrair_multiplos_art1(
    corpo: str, doc_id: str, tipo: str, subtipo_rotulo: Optional[str], data: Optional[str], bloco_completo: str
) -> list[Ato]:
    """Subdivide um ato caso haja múltiplos 'Art. 1º' no mesmo bloco (ex.: duas portarias seguidas)."""
    partes = re.split(r"(?=\bArt\.?\s*1[ºo°]?\b)", corpo)
    artigos = [p for p in partes if re.match(r"^\s*Art\.?\s*1[ºo°]?\b", p)]
    if len(artigos) <= 1:
        return []
    atos = []
    for art in artigos:
        atos.extend(_extrair_dados_servidor(art, doc_id, tipo, subtipo_rotulo, data, bloco_completo))
    return atos


def _extrair_dados_servidor(
    corpo: str,
    doc_id: str,
    tipo: str,
    subtipo_rotulo: Optional[str],
    data: Optional[str],
    bloco: str,
) -> list[Ato]:
    nome = None
    cargo = None
    orgao = None

    # 1. Padrão LOTAR: "Art. 1º LOTAR o servidor NOME, CPF ..., CARGO, na SECRETARIA..."
    if subtipo_rotulo == "Lotação":
        m = re.search(
            r"LOTAR\s+(?:o\s+servidor|a\s+servidora)\s+([A-ZÀ-Ú][^,\n]+?)\s*,\s*CPF[^,]+,\s*([^,]+?)\s*,\s*(?:na|no)\s+([^.]+)",
            corpo,
            re.IGNORECASE | re.DOTALL,
        )
        if m:
            nome = _limpar_nome(m.group(1))
            cargo = _limpar_cargo(m.group(2))
            orgao = _limpar_orgao(m.group(3))

    # 2. Padrão DESIGNAR: "Art. 1º DESIGNAR a servidora NOME, CPF ..., para exercer função de CARGO, símbolo ..., atribuições de ..., da SECRETARIA..."
    elif subtipo_rotulo == "Designação":
        m = re.search(
            r"DESIGNAR\s+(?:o\s+servidor|a\s+servidora)\s+([A-ZÀ-Ú][^,\n]+?)\s*,\s*CPF[^,]+,\s*para\s+exercer\s+(?:a\s+)?fun[çc][ãa]o\s+de\s+([^,]+?)(?:\s*,\s*s[íi]mbolo[^,]+)?(?:\s*,\s*atribui[çc][õo]es\s+de\s+([^,]+?))?\s*,\s*(?:da|do|na|no)\s+([^.]+)",
            corpo,
            re.IGNORECASE | re.DOTALL,
        )
        if m:
            nome = _limpar_nome(m.group(1))
            c_base = _limpar_cargo(m.group(2))
            c_atrib = _limpar_cargo(m.group(3)) if m.group(3) else None
            cargo = f"{c_base} ({c_atrib})" if c_base and c_atrib else (c_base or c_atrib)
            orgao = _limpar_orgao(m.group(4))

    # 3. Padrão REMOVER: "Art. 1º NOME, CPF: ..., CARGO, lotado na ORIGEM, para desenvolver suas atividades laborais na DESTINO"
    elif subtipo_rotulo == "Remoção":
        m = re.search(
            r"Art\.?\s*1[ºo°]?\s+([A-ZÀ-Ú][^,\n]+?)\s*,\s*CPF[^,]+,\s*([^,]+?)\s*,\s*lotad[oa]\s+(?:na|no)\s+[^,]+,\s*para\s+desenvolver\s+suas\s+atividades\s+laborais\s+(?:na|no)\s+([^.]+)",
            corpo,
            re.IGNORECASE | re.DOTALL,
        )
        if m:
            nome = _limpar_nome(m.group(1))
            cargo = _limpar_cargo(m.group(2))
            orgao = _limpar_orgao(m.group(3))

    # 4. Padrão REINTEGRAR: "Art. 1º REINTEGRAR o servidor NOME, CPF ..., CARGO, em decorrência de decisão judicial, na SECRETARIA..."
    elif subtipo_rotulo == "Reintegração":
        m = re.search(
            r"REINTEGRAR\s+(?:o\s+servidor|a\s+servidora)\s+([A-ZÀ-Ú][^,\n]+?)\s*,\s*CPF[^,]+,\s*([^,]+?)\s*,\s*(?:em\s+decorr[êe]ncia\s+de\s+decis[ãa]o\s+judicial\s*,\s*)?(?:na|no)\s+([^.]+)",
            corpo,
            re.IGNORECASE | re.DOTALL,
        )
        if m:
            nome = _limpar_nome(m.group(1))
            cargo = _limpar_cargo(m.group(2))
            orgao = _limpar_orgao(m.group(3))

    # 5. Padrão CESSÃO: "Art. 1º A cessão de NOME, servidora de cargo efetivo, CARGO, inscrita no CPF ... para a ORGÃO"
    elif subtipo_rotulo == "Cessão":
        m = re.search(
            r"cess[ãa]o\s+de\s+([A-ZÀ-Ú][^,\n]+?)\s*,\s*servidor(?:a)?\s+de\s+cargo\s+efetivo\s*,\s*([^,]+?)\s*,\s*inscrit[oa]\s+no\s+CPF.+?para\s+(?:a|o)\s+([^,.]+)",
            corpo,
            re.IGNORECASE | re.DOTALL,
        )
        if m:
            nome = _limpar_nome(m.group(1))
            cargo = _limpar_cargo(m.group(2))
            orgao = _limpar_orgao(m.group(3))

    # 6. Padrão TORNAR SEM EFEITO
    elif subtipo_rotulo == "Tornar sem efeito":
        m = re.search(
            r"que\s+(?:exonerou|nomeou)\s+([A-ZÀ-Ú][^,]+?)\s*,\s*CPF",
            corpo,
            re.IGNORECASE | re.DOTALL,
        )
        if m:
            nome = _limpar_nome(m.group(1))
            cargo, orgao = _extrair_cargo_e_orgao_comissionado(corpo)

    # 6b. Padrão VACÂNCIA: "Art. 1º Declarar VACÂNCIA do cargo de CARGO, ocupado pela servidora NOME, inscrita no CPF..."
    elif subtipo_rotulo == "Vacância":
        m = re.search(
            r"VAC[ÂA]NCIA\s+do\s+cargo(?:\s+efetivo)?\s+de\s+([^,]+?)\s*,\s*ocupad[oa]\s+pel[oa]\s+servidor(?:a)?\s+([A-ZÀ-Ú][^,]+?)\s*,\s*(?:inscrit|CPF)",
            corpo,
            re.IGNORECASE | re.DOTALL,
        )
        if m:
            cargo = _limpar_cargo(m.group(1))
            nome = _limpar_nome(m.group(2))
            orgao = _extrair_orgao_assinatura(bloco)

    # 7. Padrão LICENÇA PRÊMIO / MUDANÇA DE NÍVEL / GRATIFICAÇÃO / REDUÇÃO DE CARGA HORÁRIA
    elif subtipo_rotulo in (
        "Licença Prêmio",
        "Mudança de Nível",
        "Gratificação Tempo Integral",
        "Dispensa de Gratificação",
        "Redução de Carga Horária",
        "Suspensão de Redução de Carga Horária",
    ):
        m_nome = re.search(
            r"(?:LICEN[ÇC]A\s+PR[ÊE]MIO\s+a|Gratifica[çc][ãa]o\s+por\s+Tempo\s+Integral\s+a|carga\s+hor[áa]ria\s+de|(?:ao|a|à)\s+servidor(?:a)?(?:\s+efetiv[oa])?)\s+([A-ZÀ-Ú][A-ZÀ-Ú\s]+?)(?=\s*,\s*(?:servidor|ocupante|cargo|Professor|inscrit|CPF)|\s+servidor(?:a)?\s+(?:de\s+cargo\s+)?efetiv[oa])",
            corpo,
            re.DOTALL,
        )
        if m_nome:
            nome = _limpar_nome(m_nome.group(1))

        # Tenta extrair cargo efetivo nas várias ordens possíveis
        for padrao_cargo in (
            r"matr[íi]cula\s+n[ºo°.]*\s*\d+\s*,?\s*([A-ZÀ-Úa-zà-ú][^,]+?)(?=\s*,?\s*do\s+Munic[íi]pio|\s*,\s*lotad|\s*,\s*a\s+pedido)",
            r"ocupante\s+d[eo]\s+cargo\s*(?:efetivo)?(?:\s+de)?\s*,?\s*([A-ZÀ-Úa-zà-ú][^,]+?)(?=\s*,\s*(?:inscrit|CPF|lotad))",
            r"cargo\s+(?!efetivo\b)([A-ZÀ-Úa-zà-ú][^,]+?)(?=\s*,\s*CPF)",
            r",\s*(Professor(?:\(a\))?\s+[^,]+?)(?=\s*,\s*CPF)",
        ):
            m_cargo = re.search(padrao_cargo, corpo, re.IGNORECASE | re.DOTALL)
            if m_cargo:
                cargo = _limpar_cargo(m_cargo.group(1))
                if cargo:
                    break

        # Órgão / Lotação (aceita quebras de linha no meio do nome da Secretaria/Escola)
        m_orgao = re.search(
            r"(?:lotad[oa](?:\([oa]\)[oa]?)?|matriculad[oa]|\d+\s*,\s*na)\s+(?:em\s+[^,]+\s+na\s+|na\s+|no\s+)((?:Secretaria|Escola|EMEF|Funda[çc][ãa]o)[^,.]+)",
            corpo,
            re.IGNORECASE | re.DOTALL,
        )
        if m_orgao:
            orgao = _limpar_orgao(m_orgao.group(1))
        else:
            orgao = _extrair_orgao_assinatura(bloco)

    # 8. Padrão geral de NOMEAÇÃO / EXONERAÇÃO (Comissionados, Secretários e Efetivos)
    if not nome:
        # Caso 8a: Nomeação de cargo efetivo ("Art. 1º Fica nomeado para exercer as funções do cargo efetivo de CARGO ..., Sr.º NOME, CPF...")
        m_efetivo = re.search(
            r"cargo\s+efetivo\s+de\s+([^,]+?)\s*,\s*(?:Sr\.?[ºªo°]*|Sra\.?[ªa°]*)\s*([A-ZÀ-Ú][^,]+?)\s*,\s*CPF",
            corpo,
            re.IGNORECASE | re.DOTALL,
        )
        if m_efetivo:
            cargo = _limpar_cargo(m_efetivo.group(1))
            nome = _limpar_nome(m_efetivo.group(2))
        else:
            # Caso 8b: Padrão "Art. 1º NOME, CPF..." ou "Art. 1º NOME servidora de cargo efetivo, inscrita no CPF..."
            m_padrao = re.search(
                r"Art\.?\s*1[ºo°]?\s+([A-ZÀ-Ú][^,]+?)\s*(?:,\s*)?(?:servidor(?:a)?\s+de\s+cargo\s+efetivo|CPF|portador|inscrit|do\s+Cargo|das\s+fun[çc][õo]es|para\s+exercer)",
                corpo,
                re.DOTALL,
            )
            if m_padrao:
                nome = _limpar_nome(m_padrao.group(1))

        if not cargo:
            cargo, orgao = _extrair_cargo_e_orgao_comissionado(bloco)
        if not cargo:
            cargo, orgao_sec = _extrair_cargo_e_orgao_secretario(bloco)
            if not orgao:
                orgao = orgao_sec
        if not cargo:
            # Exoneração de servidor efetivo em Portaria ("matrícula nº 0003985, Auxiliar de Saúde Bucal do Município...")
            m_cargo_ef = re.search(
                r"matr[íi]cula\s+n[ºo°.]*\s*\d+\s*,?\s*([A-ZÀ-Úa-zà-ú][^,]+?)(?=\s*,?\s*do\s+Munic[íi]pio|\s*,\s*lotad|\s*,\s*a\s+pedido)",
                corpo,
                re.IGNORECASE | re.DOTALL,
            )
            if m_cargo_ef:
                cargo = _limpar_cargo(m_cargo_ef.group(1))

    if not orgao and doc_tipo_eh_portaria(doc_id):
        orgao = _extrair_orgao_assinatura(bloco)

    # Em atos do tipo "outro", não poluímos o cargo com o nome do ato se houver subtipo:
    # deixamos o cargo limpo (ou subtipo quando não há cargo específico) e colocamos o subtipo/ementa nos detalhes!
    detalhes_ato, texto_orig = _extrair_ementa_ou_art1(bloco, corpo)
    if subtipo_rotulo:
        if detalles := detalhes_ato:
            if not detalles.lower().startswith(subtipo_rotulo.lower()):
                detalhes_ato = f"{subtipo_rotulo}: {detalles}"
        else:
            detalhes_ato = subtipo_rotulo
        if not cargo:
            cargo = subtipo_rotulo

    if not nome:
        return []

    return [
        Ato(
            decreto=doc_id,
            tipo=tipo,
            nome=nome,
            cargo=cargo,
            orgao=orgao,
            data=data,
            detalhes=detalhes_ato,
            texto_original=texto_orig,
        )
    ]


def doc_tipo_eh_portaria(doc_id: str) -> bool:
    return str(doc_id).lower().startswith("portaria")


def extrair_atos(texto: str) -> list[Ato]:
    """Extrai atos de nomeação, exoneração e movimentação de pessoal do diário oficial."""
    atos: list[Ato] = []

    # Identifica apenas títulos reais de DECRETO ou PORTARIA no início de linha
    # (evita cortar blocos quando outro Decreto/Portaria é citado no meio de um parágrafo)
    cabecalho_pattern = re.compile(
        r"(?:^|\n)\s*(DECRETO|PORTARIA)\s+N[ºo°.]*\s*(\d+(?:\s*/\s*(?:\d{4}|[A-Z]+))?)\s*(?=\n|$)",
        re.IGNORECASE,
    )
    matches = list(cabecalho_pattern.finditer(texto))

    for i, m in enumerate(matches):
        doc_tipo = m.group(1).upper()
        doc_num = re.sub(r"\s+", "", m.group(2))
        # Se for uma Portaria sem ano no número (ex: "Portaria Nº 355"), tenta recuperar o ano da linha seguinte
        inicio = m.start()
        fim = matches[i + 1].start() if i + 1 < len(matches) else min(inicio + 4000, len(texto))
        bloco = texto[inicio:fim]

        if "/" not in doc_num:
            m_ano = re.search(rf"^\s*(?:DECRETO|PORTARIA)[^\n]*\n\s*(?:DE\s+)?\d{{1,2}}\s*DE\s*{_MESES}\s*DE\s*(\d{{4}})", bloco, re.IGNORECASE)
            if m_ano:
                doc_num = f"{doc_num}/{m_ano.group(1)}"

        atos.extend(_extrair_ato_bloco(doc_tipo, doc_num, bloco))

    return atos

