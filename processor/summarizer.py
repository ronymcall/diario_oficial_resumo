from processor.extractor import Ato


def gerar_resumo(atos: list[Ato]) -> str:
    """Gera um resumo em texto legível dos atos."""
    if not atos:
        return "Nenhum ato encontrado."

    nomeacoes = [a for a in atos if a.tipo == "nomeação"]
    exoneracoes = [a for a in atos if a.tipo == "exoneração"]
    outros = [a for a in atos if a.tipo == "outro"]

    linhas = []

    if nomeacoes:
        linhas.append(f"\n## Nomeações ({len(nomeacoes)})")
        for a in nomeacoes:
            linha = f"- **{a.nome}** — Decreto {a.decreto}"
            if a.cargo:
                linha += f" — Cargo: {a.cargo}"
            if a.orgao:
                linha += f" — Órgão: {a.orgao}"
            linhas.append(linha)

    if exoneracoes:
        linhas.append(f"\n## Exonerações ({len(exoneracoes)})")
        for a in exoneracoes:
            linha = f"- **{a.nome}** — Decreto {a.decreto}"
            if a.cargo:
                linha += f" — Cargo: {a.cargo}"
            if a.orgao:
                linha += f" — Órgão: {a.orgao}"
            linhas.append(linha)

    if outros:
        linhas.append(f"\n## Outros atos ({len(outros)})")
        for a in outros:
            linha = f"- **{a.nome}** — {a.decreto}"
            if a.cargo:
                linha += f" — Cargo: {a.cargo}"
            if a.orgao:
                linha += f" — Órgão: {a.orgao}"
            if getattr(a, "detalhes", None):
                linha += f" ({a.detalhes})"
            linhas.append(linha)

    return "\n".join(linhas)   
