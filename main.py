import importlib
import os
import re
import unicodedata
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

import utils
import utils.db as _db

if not hasattr(_db, "carregar_atos_edicao"):
    importlib.reload(_db)
    importlib.reload(utils)

from config import BASE_URL
from processor import extrair_atos, gerar_resumo
from processor.extractor import Ato
from scraper import baixar_edicao, extrair_texto_pdf, obter_edicao_do_dia
from utils.db import (
    carregar_atos,
    carregar_atos_edicao,
    listar_opcoes_historico,
    salvar_atos,
)
from utils.notifier import enviar_telegram

load_dotenv(Path(__file__).parent / ".env")

st.set_page_config(
    page_title="Diário Oficial — São Cristóvão/SE",
    page_icon=":material/newspaper:",
    layout="wide",
)

TIPOS = ["nomeação", "exoneração", "outro"]
CORES_TIPO = ["green", "red", "gray"]
ROTULOS_TIPO = {
    "nomeação": "Nomeação",
    "exoneração": "Exoneração",
    "outro": "Outro",
}
ROTULOS_COLUNAS = {
    "nome": "Nome",
    "tipo": "Tipo",
    "decreto": "Decreto",
    "cargo": "Cargo",
    "orgao": "Órgão",
    "data": "Data do ato",
    "edicao": "Edição",
}
COLUNAS_ATOS = ["nome", "tipo", "decreto", "cargo", "orgao", "data"]
COLUNAS_HISTORICO = [*COLUNAS_ATOS, "edicao"]


def _md(texto: str) -> str:
    return str(texto).replace("[", r"\[").replace("]", r"\]")


def _slug(texto: str) -> str:
    limpo = (
        unicodedata.normalize("NFKD", texto)
        .encode("ascii", "ignore")
        .decode("ascii")
    )
    return re.sub(r"[^a-zA-Z0-9]+", "-", limpo).strip("-").lower()


def _config_colunas(incluir_edicao: bool = False) -> dict:
    config = {
        "nome": st.column_config.TextColumn("Nome", width="large", pinned=True),
        "tipo": st.column_config.MultiselectColumn(
            "Tipo",
            options=TIPOS,
            color=CORES_TIPO,
            format_func=lambda t: ROTULOS_TIPO.get(t, str(t).capitalize()),
            width="small",
        ),
        "decreto": st.column_config.TextColumn("Decreto", width="small"),
        "cargo": st.column_config.TextColumn("Cargo", width="medium"),
        "orgao": st.column_config.TextColumn("Órgão", width="medium"),
        "data": st.column_config.TextColumn("Data do ato", width="small"),
    }
    if incluir_edicao:
        config["edicao"] = st.column_config.TextColumn("Edição", width="medium")
    return config


def _df_tabela(registros: list[dict], incluir_edicao: bool = False) -> pd.DataFrame:
    df = pd.DataFrame(registros)
    if df.empty:
        return df
    df["tipo"] = df["tipo"].apply(lambda t: [t] if t else [])
    colunas = COLUNAS_HISTORICO if incluir_edicao else COLUNAS_ATOS
    return df[[c for c in colunas if c in df.columns]]


def _mostrar_tabela(
    registros: list[dict],
    *,
    incluir_edicao: bool = False,
    altura: int = 460,
    key: str | None = None,
) -> None:
    st.dataframe(
        _df_tabela(registros, incluir_edicao),
        column_config=_config_colunas(incluir_edicao),
        hide_index=True,
        height=altura,
        placeholder="—",
        key=key,
        alt="Atos de pessoal publicados no Diário Oficial",
    )


def _csv(registros: list[dict], incluir_edicao: bool = False) -> bytes:
    if not registros:
        return b""
    df = pd.DataFrame(registros)
    colunas = COLUNAS_HISTORICO if incluir_edicao else COLUNAS_ATOS
    df = df[[c for c in colunas if c in df.columns]]
    df = df.rename(columns=ROTULOS_COLUNAS)
    return df.to_csv(index=False).encode("utf-8-sig")


def _badges_ato(ato: Ato) -> str:
    cor_decreto = {
        "nomeação": "green",
        "exoneração": "red",
        "outro": "gray",
    }.get(ato.tipo, "gray")
    cor_cargo = "orange" if ato.tipo == "exoneração" else "blue"

    badges = [f":{cor_decreto}-badge[Decreto {_md(ato.decreto)}]"]
    if ato.cargo:
        badges.append(f":{cor_cargo}-badge[{_md(ato.cargo)}]")
    return " ".join(badges)


def _card_ato(ato: Ato) -> None:
    with st.container(border=True, gap="xxsmall"):
        st.markdown(f"**{_md(ato.nome)}**\n\n{_badges_ato(ato)}")
        rodape = []
        if ato.orgao:
            rodape.append(f":material/account_balance: {_md(ato.orgao)}")
        if ato.data:
            rodape.append(f":material/event: {_md(ato.data)}")
        if rodape:
            st.caption(" · ".join(rodape))


def _lista_resumo(atos: list[Ato], vazio: str) -> None:
    with st.container(height=460, border=True, gap="xsmall"):
        if not atos:
            st.caption(vazio)
            return
        for ato in atos:
            _card_ato(ato)


def _render_edicao(edicao: dict, atos: list[Ato]) -> None:
    nomeacoes = sum(1 for a in atos if a.tipo == "nomeação")
    exoneracoes = sum(1 for a in atos if a.tipo == "exoneração")
    orgaos = {a.orgao for a in atos if a.orgao}

    with st.container(border=True):
        col_info, col_acao = st.columns([4, 1.2], vertical_alignment="center")
        with col_info:
            st.subheader(
                edicao.get("titulo", "Edição carregada"),
                icon=":material/description:",
            )
            selos = []
            if edicao.get("data"):
                selos.append(
                    f":blue-badge[:material/calendar_today: Publicada em {_md(edicao['data'])}]"
                )
            selos.append(
                f":gray-badge[:material/gavel: {len(atos)} ato(s)]"
                if atos
                else ":gray-badge[Nenhum ato identificado]"
            )
            if nomeacoes:
                selos.append(
                    f":green-badge[:material/person_add: {nomeacoes} nomeação(ões)]"
                )
            if exoneracoes:
                selos.append(
                    f":red-badge[:material/person_remove: {exoneracoes} exoneração(ões)]"
                )
            if orgaos:
                selos.append(
                    f":violet-badge[:material/account_balance: {len(orgaos)} órgão(s)]"
                )
            st.markdown(" ".join(selos))
        with col_acao:
            url = edicao.get("url")
            if url:
                st.link_button(
                    "Abrir PDF original",
                    url,
                    icon=":material/open_in_new:",
                    width="stretch",
                )


def _render_metricas(atos: list[Ato]) -> None:
    total = len(atos)
    nomeacoes = sum(1 for a in atos if a.tipo == "nomeação")
    exoneracoes = sum(1 for a in atos if a.tipo == "exoneração")
    outros = sum(1 for a in atos if a.tipo == "outro")
    orgaos = {a.orgao for a in atos if a.orgao}
    saldo = nomeacoes - exoneracoes

    col_total, col_nomeacoes, col_exoneracoes, col_outros = st.columns(
        4, gap="small"
    )
    col_total.metric(
        "Total de atos",
        total,
        delta=f"{len(orgaos)} órgão(s) com atos" if orgaos else "Sem órgão especificado",
        delta_color="off",
        delta_arrow="off",
        icon=":material/gavel:",
        border=True,
        height="stretch",
    )
    col_nomeacoes.metric(
        "Nomeações",
        nomeacoes,
        delta=f"{nomeacoes / total:.0%} da edição" if total else "0%",
        delta_color="green" if nomeacoes else "off",
        delta_arrow="up" if nomeacoes else "off",
        icon=":material/person_add:",
        border=True,
        height="stretch",
    )
    col_exoneracoes.metric(
        "Exonerações",
        exoneracoes,
        delta=f"{exoneracoes / total:.0%} da edição" if total else "0%",
        delta_color="red" if exoneracoes else "off",
        delta_arrow="down" if exoneracoes else "off",
        icon=":material/person_remove:",
        border=True,
        height="stretch",
    )
    col_outros.metric(
        "Outros atos",
        outros,
        delta=f"Saldo líquido: {saldo:+d}",
        delta_color="off",
        delta_arrow="off",
        icon=":material/description:",
        border=True,
        height="stretch",
    )


def _filtrar_atos_edicao(
    atos: list[Ato], termo: str, orgao_selecionado: str | None
) -> list[Ato]:
    filtrados = atos
    if orgao_selecionado and orgao_selecionado != "Todos os órgãos":
        filtrados = [a for a in filtrados if a.orgao == orgao_selecionado]
    if termo:
        t = termo.lower()
        filtrados = [
            a
            for a in filtrados
            if t in (a.nome or "").lower()
            or t in (a.cargo or "").lower()
            or t in (a.orgao or "").lower()
            or t in (a.decreto or "").lower()
        ]
    return filtrados


@st.fragment
def _render_resumo(atos: list[Ato], edicao: dict) -> None:
    if not atos:
        st.info(
            "Nenhum ato de nomeação ou exoneração foi encontrado nesta edição.",
            icon=":material/search_off:",
            title="Nenhum ato encontrado",
        )
        return

    orgaos_edicao = sorted({a.orgao for a in atos if a.orgao})

    col_busca, col_orgao = st.columns([2.2, 1.3], vertical_alignment="center")
    with col_busca:
        busca_resumo = st.text_input(
            "Filtrar atos no resumo",
            type="search",
            live=True,
            placeholder="Filtrar por nome, cargo, órgão ou decreto…",
            label_visibility="collapsed",
            key="resumo_busca",
        )
    with col_orgao:
        orgao_filtro = st.selectbox(
            "Filtrar por órgão",
            ["Todos os órgãos", *orgaos_edicao],
            label_visibility="collapsed",
            key="resumo_orgao",
            disabled=not orgaos_edicao,
        )

    atos_filtrados = _filtrar_atos_edicao(
        atos, (busca_resumo or "").strip(), orgao_filtro
    )

    nomeacoes = [a for a in atos_filtrados if a.tipo == "nomeação"]
    exoneracoes = [a for a in atos_filtrados if a.tipo == "exoneração"]
    outros = [a for a in atos_filtrados if a.tipo == "outro"]

    if len(atos_filtrados) != len(atos):
        st.caption(
            f"Exibindo {len(atos_filtrados)} de {len(atos)} atos desta edição."
        )
    else:
        st.caption(
            "Consulte as nomeações e exonerações separadas por categoria abaixo."
        )

    col_nomeacoes, col_exoneracoes = st.columns(2, gap="medium")
    with col_nomeacoes:
        st.subheader(
            f"Nomeações · {len(nomeacoes)}",
            icon=":material/person_add:",
        )
        _lista_resumo(nomeacoes, "Nenhuma nomeação para os filtros aplicados.")
    with col_exoneracoes:
        st.subheader(
            f"Exonerações · {len(exoneracoes)}",
            icon=":material/person_remove:",
        )
        _lista_resumo(exoneracoes, "Nenhuma exoneração para os filtros aplicados.")

    if outros:
        st.space("small")
        with st.expander(
            f"Outros atos · {len(outros)}",
            icon=":material/description:",
        ):
            for ato in outros:
                _card_ato(ato)

    st.space("small")
    resumo = gerar_resumo(atos)
    base = _slug(edicao.get("titulo", "diario-oficial")) or "diario-oficial"
    telegram_configurado = bool(
        os.getenv("TELEGRAM_BOT_TOKEN") and os.getenv("TELEGRAM_CHAT_ID")
    )

    with st.container(horizontal=True, vertical_alignment="center"):
        st.download_button(
            "Baixar resumo (.md)",
            data=resumo,
            file_name=f"resumo-{base}.md",
            mime="text/markdown",
            icon=":material/download:",
        )
        with st.popover("Visualizar Markdown", icon=":material/visibility:"):
            st.caption("Pré-visualização do texto gerado para exportação e Telegram")
            st.code(resumo, language="markdown")
        enviar = st.button(
            "Enviar por Telegram",
            icon=":material/send:",
            disabled=not telegram_configurado,
            key="btn_enviar_telegram",
        )

    if enviar:
        with st.spinner("Enviando resumo para o Telegram..."):
            enviado = enviar_telegram(resumo)
        if enviado:
            st.toast(
                "Resumo enviado para o Telegram.",
                icon=":material/check_circle:",
            )
        else:
            st.error(
                "Não foi possível enviar o resumo. Confira as credenciais do Telegram.",
                icon=":material/error:",
                title="Falha no envio",
            )

    if not telegram_configurado:
        st.caption(
            "Telegram não configurado. Defina `TELEGRAM_BOT_TOKEN` e "
            "`TELEGRAM_CHAT_ID` no arquivo `.env`."
        )


def _render_orgaos(atos: list[Ato]) -> None:
    if not atos:
        st.info(
            "Carregue uma edição com atos para visualizar a distribuição por órgão.",
            icon=":material/analytics:",
            title="Sem dados para análise",
        )
        return

    agrupado: dict[str, dict[str, int]] = {}
    for ato in atos:
        nome_orgao = ato.orgao or "Órgão não especificado"
        item = agrupado.setdefault(
            nome_orgao,
            {"Nomeações": 0, "Exonerações": 0, "Outros": 0, "Total": 0},
        )
        if ato.tipo == "nomeação":
            item["Nomeações"] += 1
        elif ato.tipo == "exoneração":
            item["Exonerações"] += 1
        else:
            item["Outros"] += 1
        item["Total"] += 1

    linhas = [
        {
            "Órgão": orgao,
            "Nomeações": cont["Nomeações"],
            "Exonerações": cont["Exonerações"],
            "Outros": cont["Outros"],
            "Saldo": cont["Nomeações"] - cont["Exonerações"],
            "Total": cont["Total"],
        }
        for orgao, cont in agrupado.items()
    ]
    df_orgaos = pd.DataFrame(linhas).sort_values(
        by=["Total", "Nomeações"], ascending=[False, False]
    )

    with st.container(border=True):
        st.subheader(
            "Movimentações por secretaria ou órgão",
            icon=":material/bar_chart:",
        )
        st.caption(
            "Comparativo entre nomeações e exonerações identificadas nesta edição."
        )
        st.bar_chart(
            df_orgaos,
            x="Órgão",
            y=["Nomeações", "Exonerações", "Outros"],
            horizontal=True,
            color=["#1A7F37", "#B42318", "#5B6B73"],
            height=max(260, min(520, len(df_orgaos) * 44 + 80)),
            alt="Gráfico de barras horizontais com o total de nomeações e exonerações por órgão",
        )

    max_total = int(df_orgaos["Total"].max()) if not df_orgaos.empty else 1
    st.dataframe(
        df_orgaos,
        column_config={
            "Órgão": st.column_config.TextColumn("Órgão", width="large", pinned=True),
            "Nomeações": st.column_config.NumberColumn("Nomeações", width="small"),
            "Exonerações": st.column_config.NumberColumn("Exonerações", width="small"),
            "Outros": st.column_config.NumberColumn("Outros", width="small"),
            "Saldo": st.column_config.NumberColumn(
                "Saldo",
                format="%+d",
                width="small",
                help="Diferença entre nomeações e exonerações no órgão",
            ),
            "Total": st.column_config.ProgressColumn(
                "Total de atos",
                min_value=0,
                max_value=max(1, max_total),
                format="%d",
                width="medium",
            ),
        },
        hide_index=True,
        key="df_orgaos_edicao",
        alt="Resumo quantitativo de atos agrupados por órgão",
    )


def _render_tabela(atos: list[Ato], edicao: dict) -> None:
    if not atos:
        st.info(
            "Nenhum ato para exibir nesta edição.",
            icon=":material/table_chart:",
            title="Tabela vazia",
        )
        return

    registros = [a.__dict__ for a in atos]
    base = _slug(edicao.get("titulo", "diario-oficial")) or "diario-oficial"

    col_info, col_acao = st.columns([3, 1], vertical_alignment="center")
    col_info.caption(
        f"{len(atos)} atos nesta edição. "
        "Ordene pelas colunas ou use a busca da tabela."
    )
    with col_acao:
        st.download_button(
            "Baixar CSV",
            data=_csv(registros),
            file_name=f"atos-{base}.csv",
            mime="text/csv",
            icon=":material/download:",
            width="stretch",
        )

    _mostrar_tabela(registros, altura=480, key="df_tabela_edicao")


@st.fragment
def _render_historico() -> None:
    opcoes = listar_opcoes_historico()

    with st.container(horizontal=True, vertical_alignment="center"):
        filtro = st.segmented_control(
            "Tipo do ato",
            ["Todos", "Nomeações", "Exonerações", "Outros"],
            default="Todos",
            key="historico_tipo",
            label_visibility="collapsed",
        )
        busca = st.text_input(
            "Buscar no histórico",
            type="search",
            live="300ms",
            placeholder="Buscar por nome, cargo, órgão ou decreto…",
            label_visibility="collapsed",
            key="historico_busca",
            persist_state="session",
        )

    col_orgao, col_edicao = st.columns(2, gap="small")
    with col_orgao:
        orgao_sel = st.selectbox(
            "Filtrar por órgão no histórico",
            ["Todos os órgãos", *opcoes["orgaos"]],
            label_visibility="collapsed",
            key="historico_orgao",
        )
    with col_edicao:
        edicao_sel = st.selectbox(
            "Filtrar por edição no histórico",
            ["Todas as edições", *opcoes["edicoes"]],
            label_visibility="collapsed",
            key="historico_edicao",
        )

    mapa_tipos = {
        "Nomeações": "nomeação",
        "Exonerações": "exoneração",
        "Outros": "outro",
    }
    tipo = mapa_tipos.get(filtro or "Todos")
    termo = (busca or "").strip()
    orgao_param = (
        None if not orgao_sel or orgao_sel == "Todos os órgãos" else orgao_sel
    )
    edicao_param = (
        None if not edicao_sel or edicao_sel == "Todas as edições" else edicao_sel
    )
    resultados = carregar_atos(
        tipo=tipo,
        busca=termo or None,
        orgao=orgao_param,
        edicao=edicao_param,
    )

    if not resultados:
        st.info(
            "Nenhum ato encontrado no histórico com esses filtros.",
            icon=":material/search_off:",
            title="Sem resultados",
        )
        return

    nom_hist = sum(1 for r in resultados if r.get("tipo") == "nomeação")
    exo_hist = sum(1 for r in resultados if r.get("tipo") == "exoneração")

    col_info, col_acao = st.columns([3, 1], vertical_alignment="center")
    col_info.caption(
        f"{len(resultados)} ato(s) encontrado(s) no histórico · "
        f"{nom_hist} nomeação(ões) · {exo_hist} exoneração(ões)."
    )
    with col_acao:
        st.download_button(
            "Baixar CSV",
            data=_csv(resultados, incluir_edicao=True),
            file_name="historico-atos.csv",
            mime="text/csv",
            icon=":material/download:",
            width="stretch",
        )

    _mostrar_tabela(
        resultados,
        incluir_edicao=True,
        altura=480,
        key="df_tabela_historico",
    )


def processar_pdf(url: str, nome_arquivo: str, edicao: str) -> list[Ato]:
    caminho = baixar_edicao(url, nome_arquivo=nome_arquivo)
    texto = extrair_texto_pdf(caminho)
    atos = extrair_atos(texto)
    salvar_atos(atos, edicao=edicao)
    st.session_state["atos_processados"] = atos
    return atos


def processar_diario(dia: date) -> None:
    with st.spinner(f"Buscando edição de {dia:%d/%m/%Y}..."):
        try:
            edicao = obter_edicao_do_dia(dia)
        except Exception as e:
            st.error(
                f"Não foi possível buscar a edição: {e}",
                icon=":material/cloud_off:",
                title="Erro de conexão",
            )
            return

    if not edicao:
        st.session_state.pop("atos_processados", None)
        st.session_state.pop("edicao_atual", None)
        st.info(
            f"Não há edição publicada em {dia:%d/%m/%Y}. "
            "Você pode consultar outra data ou selecionar uma edição salva na barra lateral.",
            icon=":material/event_busy:",
            title="Sem publicação nesta data",
        )
        return

    with st.spinner(f"Baixando e processando a edição {edicao['numero']}..."):
        try:
            atos = processar_pdf(
                edicao["url"],
                f"edicao-{edicao['id']}.pdf",
                edicao["titulo"],
            )
        except Exception as e:
            st.error(
                f"Não foi possível processar a edição: {e}",
                icon=":material/error:",
                title="Erro ao processar PDF",
            )
            return

    st.session_state["edicao_atual"] = edicao
    st.toast(
        f"{len(atos)} atos extraídos de {edicao['titulo']}.",
        icon=":material/check_circle:",
    )


hoje = date.today()
chave_hoje = hoje.isoformat()

st.title("Resumo do Diário Oficial", icon=":material/newspaper:")
st.caption(
    "São Cristóvão/SE · Monitoramento de nomeações, exonerações e atos de pessoal "
    "publicados no diário oficial do município"
)

if st.session_state.get("tentativa_dia") != chave_hoje:
    st.session_state["tentativa_dia"] = chave_hoje
    processar_diario(hoje)

opcoes_hist = listar_opcoes_historico()
edicoes_salvas = opcoes_hist["edicoes"]

with st.sidebar:
    st.header("Consultar edição", icon=":material/search:")
    st.caption(f"Data de referência: {hoje:%d/%m/%Y}")

    if st.button(
        "Atualizar diário de hoje",
        icon=":material/refresh:",
        type="primary",
        width="stretch",
        key="btn_atualizar",
    ):
        processar_diario(hoje)

    with st.form("form_busca_data"):
        dia_busca = st.date_input(
            "Buscar por data",
            value=hoje,
            max_value=hoje,
            format="DD/MM/YYYY",
        )
        buscar = st.form_submit_button(
            "Buscar edição",
            icon=":material/search:",
            width="stretch",
        )
    if buscar:
        processar_diario(dia_busca)

    if edicoes_salvas:
        with st.expander("Edições salvas no banco", icon=":material/inventory_2:"):
            with st.form("form_edicao_salva", border=False):
                edicao_escolhida = st.selectbox(
                    "Selecione uma edição processada",
                    edicoes_salvas,
                    key="sidebar_edicao_salva",
                )
                carregar_salva = st.form_submit_button(
                    "Carregar edição",
                    icon=":material/folder_open:",
                    width="stretch",
                )
            if carregar_salva and edicao_escolhida:
                atos_salvos = carregar_atos_edicao(edicao_escolhida)
                st.session_state["atos_processados"] = atos_salvos
                st.session_state["edicao_atual"] = {
                    "titulo": edicao_escolhida,
                }
                st.toast(
                    f"{len(atos_salvos)} atos carregados de {edicao_escolhida}.",
                    icon=":material/check_circle:",
                )

    with st.expander("Usar PDF/ID manualmente", icon=":material/link:"):
        with st.form("form_pdf_manual", border=False):
            entrada = st.text_input(
                "ID da edição ou URL do PDF",
                placeholder="Ex.: 8064",
            )
            processar = st.form_submit_button(
                "Processar PDF",
                icon=":material/download:",
                width="stretch",
            )

        if processar:
            valor = entrada.strip()
            if not valor:
                st.warning(
                    "Informe o ID ou a URL do PDF.",
                    icon=":material/warning:",
                    title="Campo obrigatório",
                )
            else:
                url = (
                    f"{BASE_URL}/portal/edicoes/download/{valor}"
                    if valor.isdigit()
                    else valor
                )
                nome = f"edicao-{valor[:80]}"
                with st.spinner("Baixando e processando..."):
                    try:
                        atos = processar_pdf(url, f"{nome}.pdf", nome)
                    except Exception as e:
                        st.error(
                            f"Não foi possível processar o PDF: {e}",
                            icon=":material/error:",
                            title="Falha ao processar PDF",
                        )
                    else:
                        st.session_state["edicao_atual"] = {
                            "titulo": (
                                f"Edição {valor}"
                                if valor.isdigit()
                                else "PDF informado manualmente"
                            ),
                            "url": url,
                        }
                        st.toast(
                            f"{len(atos)} atos extraídos.",
                            icon=":material/check_circle:",
                        )

    st.space("small")
    edicao_sidebar = st.session_state.get("edicao_atual")
    with st.container(border=True):
        st.caption("Edição em exibição")
        if edicao_sidebar:
            st.markdown(
                f"**{_md(edicao_sidebar.get('titulo', 'Edição carregada'))}**"
            )
            atos_sidebar = st.session_state.get("atos_processados", [])
            st.badge(
                f"{len(atos_sidebar)} atos identificados"
                if atos_sidebar
                else "Nenhum ato identificado",
                icon=":material/gavel:" if atos_sidebar else ":material/info:",
                color="green" if atos_sidebar else "gray",
            )
        else:
            st.caption("Nenhuma edição carregada.")

    st.caption("Fonte: Portal Oficial de São Cristóvão/SE.")

edicao_atual = st.session_state.get("edicao_atual")
atos = st.session_state.get("atos_processados", [])

if edicao_atual:
    _render_edicao(edicao_atual, atos)
else:
    st.info(
        "Use a barra lateral para atualizar o diário de hoje, "
        "buscar uma data, carregar uma edição salva ou informar um PDF.",
        icon=":material/event_note:",
        title="Nenhuma edição carregada",
    )

if atos:
    st.space("small")
    _render_metricas(atos)

st.space("small")
tab_resumo, tab_orgaos, tab_tabela, tab_historico = st.tabs(
    [
        ":material/article: Resumo",
        ":material/analytics: Por órgão",
        ":material/table_chart: Tabela",
        ":material/history: Histórico",
    ]
)

with tab_resumo:
    _render_resumo(atos, edicao_atual or {})

with tab_orgaos:
    _render_orgaos(atos)

with tab_tabela:
    _render_tabela(atos, edicao_atual or {})

with tab_historico:
    _render_historico()
