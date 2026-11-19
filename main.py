import importlib
import re
import unicodedata
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

import config
import processor
import processor.extractor as _extractor
import processor.summarizer as _summarizer
import utils
import utils.db as _db

if not hasattr(config, "get_config"):
    importlib.reload(config)
if not hasattr(_db, "resumo_edicoes_recentes"):
    importlib.reload(_db)
importlib.reload(_extractor)
importlib.reload(_summarizer)
importlib.reload(processor)
importlib.reload(utils)

from config import BASE_URL, get_config
from processor import extrair_atos, gerar_resumo
from processor.extractor import Ato
from scraper import baixar_edicao, extrair_texto_pdf, obter_edicao_do_dia
from utils.auth import (
    alterar_senha,
    autenticar_usuario,
    criar_sessao_persistente,
    criar_usuario,
    encerrar_sessao_persistente,
    garantir_admin_inicial,
    listar_usuarios,
    remover_usuario,
    validar_sessao_persistente,
)
from utils.db import (
    carregar_atos,
    carregar_atos_edicao,
    listar_opcoes_historico,
    resumo_edicoes_recentes,
    salvar_atos,
)
from utils.notifier import enviar_telegram

load_dotenv(Path(__file__).parent / ".env")

ASSETS_DIR = Path(__file__).parent / "assets"
ICON_PATH = ASSETS_DIR / "icone-prefeitura.png"
LOGO_BRANCO_PATH = ASSETS_DIR / "logo-prefeitura-branco.png"
LOGO_AZUL_PATH = ASSETS_DIR / "logo-prefeitura-azul.png"

st.set_page_config(
    page_title="Diário Oficial — São Cristóvão/SE",
    page_icon=str(ICON_PATH) if ICON_PATH.exists() else ":material/newspaper:",
    layout="wide",
)

# Paleta institucional Prefeitura de São Cristóvão (saocristovao.se.gov.br)
COR_AZUL_MARINHO = "#111C5A"
COR_AZUL_INSTITUCIONAL = "#1E3A8A"
COR_AZUL_REAL = "#2563EB"
COR_AZUL_CLARO = "#60A5FA"
COR_NOMEACAO = "#059669"
COR_EXONERACAO = "#DC2626"
COR_OUTRO = "#4F46E5"

TIPOS = ["nomeação", "exoneração", "outro"]
CORES_TIPO = ["green", "red", "blue"]
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
    "detalhes": "Descrição / Ementa",
    "data": "Data do ato",
    "edicao": "Edição",
}
COLUNAS_ATOS = ["nome", "tipo", "decreto", "cargo", "orgao", "detalhes", "data"]
COLUNAS_HISTORICO = [*COLUNAS_ATOS, "edicao"]


def _md(texto: str) -> str:
    return str(texto).replace("[", r"\[").replace("]", r"\]")


def _slug(texto: str) -> str:
    limpo = (
        unicodedata.normalize("NFKD", str(texto))
        .encode("ascii", "ignore")
        .decode("ascii")
    )
    return re.sub(r"[^a-zA-Z0-9]+", "-", limpo).strip("-").lower()


def _rotulo_curto_edicao(edicao: str) -> str:
    m_num = re.search(r"(\d{3,5})", str(edicao))
    m_data = re.search(r"(\d{2}/\d{2})", str(edicao))
    if m_num and m_data:
        return f"Ed. {m_num.group(1)} ({m_data.group(1)})"
    if m_num:
        return f"Ed. {m_num.group(1)}"
    return str(edicao)[:18]


@st.cache_data(ttl=60, show_spinner=False)
def _opcoes_historico_cached() -> dict[str, list[str]]:
    return listar_opcoes_historico()


@st.cache_data(ttl=60, show_spinner=False)
def _serie_edicoes_cached(limite: int = 12) -> list[dict]:
    return resumo_edicoes_recentes(limite=limite)


def _limpar_cache_banco() -> None:
    _opcoes_historico_cached.clear()
    _serie_edicoes_cached.clear()


def _config_colunas(incluir_edicao: bool = False) -> dict:
    colunas = {
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
        "detalhes": st.column_config.TextColumn("Descrição / Ementa", width="large"),
        "data": st.column_config.TextColumn("Data do ato", width="small"),
    }
    if incluir_edicao:
        colunas["edicao"] = st.column_config.TextColumn("Edição", width="medium")
    return colunas


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
        alt="Atos de pessoal publicados no Diário Oficial de São Cristóvão",
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
    cor_tipo = {
        "nomeação": "green",
        "exoneração": "red",
        "outro": "blue",
    }.get(ato.tipo, "gray")
    cor_cargo = "violet" if ato.tipo == "outro" else "blue"

    rotulo_doc = (
        _md(ato.decreto)
        if str(ato.decreto).lower().startswith("portaria")
        else f"Decreto {_md(ato.decreto)}"
    )
    badges = [f":{cor_tipo}-badge[{rotulo_doc}]"]
    if ato.cargo:
        badges.append(f":{cor_cargo}-badge[{_md(ato.cargo)}]")
    return " ".join(badges)


@st.dialog(
    "Detalhes do ato oficial",
    width="medium",
    position="right",
    icon=":material/gavel:",
)
def _drawer_detalhes_ato(ato: Ato) -> None:
    cor_tipo = {
        "nomeação": "green",
        "exoneração": "red",
        "outro": "blue",
    }.get(ato.tipo, "gray")
    rotulo_tipo = ROTULOS_TIPO.get(ato.tipo, str(ato.tipo).capitalize())

    st.markdown(f"### {_md(ato.nome)}")
    selos = [f":{cor_tipo}-badge[{rotulo_tipo}]", _badges_ato(ato)]
    st.markdown(" ".join(selos))

    with st.container(border=True, gap="xsmall"):
        col_a, col_b = st.columns(2, gap="small")
        col_a.caption("Órgão / Secretaria")
        col_a.markdown(f"**{_md(ato.orgao or 'Não especificado')}**")
        col_b.caption("Data do ato")
        col_b.markdown(f"**{_md(ato.data or 'Não informada')}**")

    if getattr(ato, "detalhes", None):
        with st.container(border=True, gap="xsmall"):
            st.caption("Resumo / Ementa")
            st.markdown(_md(ato.detalhes))

    if getattr(ato, "texto_original", None):
        st.caption("Trecho extraído do Diário Oficial")
        st.code(ato.texto_original, language="text")


def _card_ato(
    ato: Ato,
    *,
    key_prefix: str,
    idx: int,
    mostrar_detalhes: bool = False,
) -> None:
    tem_drawer = bool(
        getattr(ato, "texto_original", None)
        or getattr(ato, "detalhes", None)
    )
    with st.container(border=True, gap="xxsmall"):
        col_titulo, col_btn = st.columns([4.2, 1.3], vertical_alignment="top")
        with col_titulo:
            st.markdown(f"**{_md(ato.nome)}**")
        with col_btn:
            if tem_drawer:
                btn_key = (
                    f"det_{key_prefix}_{idx}_"
                    f"{_slug(ato.decreto)[:12]}_{_slug(ato.nome)[:14]}"
                )
                if st.button(
                    "Detalhes",
                    icon=":material/open_in_new:",
                    type="tertiary",
                    key=btn_key,
                    width="stretch",
                ):
                    _drawer_detalhes_ato(ato)

        st.markdown(_badges_ato(ato))

        if mostrar_detalhes and getattr(ato, "detalhes", None):
            st.caption(_md(ato.detalhes))

        rodape = []
        if ato.orgao:
            rodape.append(f":material/account_balance: {_md(ato.orgao)}")
        if ato.data:
            rodape.append(f":material/event: {_md(ato.data)}")
        if rodape:
            st.caption(" · ".join(rodape))


def _lista_resumo(atos: list[Ato], vazio: str, *, key_prefix: str) -> None:
    with st.container(height=470, border=True, gap="xsmall"):
        if not atos:
            st.caption(vazio)
            return
        for idx, ato in enumerate(atos):
            _card_ato(ato, key_prefix=key_prefix, idx=idx)


def _render_cabecalho_acoes(edicao: dict, atos: list[Ato]) -> None:
    col_titulo, col_acoes = st.columns([2.2, 1.5], vertical_alignment="bottom")
    with col_titulo:
        st.title("Resumo do Diário Oficial", icon=":material/newspaper:")
        st.caption(
            "Prefeitura Municipal de São Cristóvão/SE · "
            "Monitoramento de nomeações, exonerações e atos de pessoal"
        )

    with col_acoes:
        if not edicao and not atos:
            return
        with st.container(
            horizontal=True,
            horizontal_alignment="right",
            vertical_alignment="center",
        ):
            url = edicao.get("url") if edicao else None
            if url:
                st.link_button(
                    "PDF original",
                    url,
                    icon=":material/open_in_new:",
                    type="secondary",
                )
            if atos:
                resumo = gerar_resumo(atos)
                base = (
                    _slug(edicao.get("titulo", "diario-oficial"))
                    if edicao
                    else "diario-oficial"
                ) or "diario-oficial"
                st.download_button(
                    "Exportar .md",
                    data=resumo,
                    file_name=f"resumo-{base}.md",
                    mime="text/markdown",
                    icon=":material/download:",
                    type="primary",
                    key="btn_topo_baixar_md",
                )
                with st.popover("Compartilhar", icon=":material/send:"):
                    telegram_configurado = bool(
                        get_config("TELEGRAM_BOT_TOKEN")
                        and get_config("TELEGRAM_CHAT_ID")
                    )
                    if st.button(
                        "Enviar resumo por Telegram",
                        icon=":material/send:",
                        type="primary",
                        disabled=not telegram_configurado,
                        width="stretch",
                        key="btn_enviar_telegram_topo",
                    ):
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
                            "Defina `TELEGRAM_BOT_TOKEN` e `TELEGRAM_CHAT_ID` no `.env`."
                        )
                    st.caption("Pré-visualização do resumo em Markdown")
                    st.code(resumo, language="markdown")


def _render_edicao(edicao: dict, atos: list[Ato]) -> None:
    nomeacoes = sum(1 for a in atos if a.tipo == "nomeação")
    exoneracoes = sum(1 for a in atos if a.tipo == "exoneração")
    outros = sum(1 for a in atos if a.tipo == "outro")
    orgaos = {a.orgao for a in atos if a.orgao}

    with st.container(border=True, gap="xsmall"):
        col_info, col_meta = st.columns([3.4, 1.4], vertical_alignment="center")
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
                f":blue-badge[:material/gavel: {len(atos)} ato(s)]"
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
            if outros:
                selos.append(
                    f":violet-badge[:material/assignment: {outros} outro(s)]"
                )
            if orgaos:
                selos.append(
                    f":gray-badge[:material/account_balance: {len(orgaos)} órgão(s)]"
                )
            st.markdown(" ".join(selos))

        with col_meta:
            saldo = nomeacoes - exoneracoes
            sinal = "+" if saldo > 0 else ""
            cor_saldo = "green" if saldo > 0 else ("red" if saldo < 0 else "gray")
            with st.container(horizontal_alignment="right"):
                st.caption("Balanço de movimentação")
                st.badge(
                    f"Saldo líquido: {sinal}{saldo}",
                    icon=":material/trending_up:"
                    if saldo >= 0
                    else ":material/trending_down:",
                    color=cor_saldo,
                )


def _render_metricas(atos: list[Ato], historico_edicoes: list[dict]) -> None:
    total = len(atos)
    nomeacoes = sum(1 for a in atos if a.tipo == "nomeação")
    exoneracoes = sum(1 for a in atos if a.tipo == "exoneração")
    outros = sum(1 for a in atos if a.tipo == "outro")
    orgaos = {a.orgao for a in atos if a.orgao}
    saldo = nomeacoes - exoneracoes

    spark_total = [e["total"] for e in historico_edicoes] or None
    spark_nom = [e["nomeacoes"] for e in historico_edicoes] or None
    spark_exo = [e["exoneracoes"] for e in historico_edicoes] or None
    spark_saldo = (
        [e["nomeacoes"] - e["exoneracoes"] for e in historico_edicoes]
        or None
    )

    media_hist = (
        sum(e["total"] for e in historico_edicoes) / len(historico_edicoes)
        if historico_edicoes
        else 0.0
    )
    diff_media = total - round(media_hist) if historico_edicoes else 0

    with st.grid(4, gap="small"):
        st.metric(
            "Total de atos",
            total,
            delta=f"{diff_media:+d} vs. média"
            if historico_edicoes
            else f"{len(orgaos)} órgão(s)",
            delta_color="primary",
            delta_arrow="off",
            delta_description=f"{len(orgaos)} órgão(s)" if orgaos else None,
            icon=":material/gavel:",
            chart_data=spark_total,
            chart_type="area",
            border=True,
            height="stretch",
        )
        st.metric(
            "Nomeações",
            nomeacoes,
            delta=f"{nomeacoes / total:.0%} da edição" if total else 0,
            delta_color="green" if nomeacoes else "off",
            delta_arrow="up" if nomeacoes else "off",
            icon=":material/person_add:",
            chart_data=spark_nom,
            chart_type="bar",
            border=True,
            height="stretch",
        )
        st.metric(
            "Exonerações",
            exoneracoes,
            delta=f"{exoneracoes / total:.0%} da edição" if total else 0,
            delta_color="red" if exoneracoes else "off",
            delta_arrow="down" if exoneracoes else "off",
            icon=":material/person_remove:",
            chart_data=spark_exo,
            chart_type="bar",
            border=True,
            height="stretch",
        )
        st.metric(
            "Saldo líquido",
            f"{saldo:+d}",
            delta=f"{outros} outro(s) ato(s)",
            delta_color="blue",
            delta_arrow="off",
            icon=":material/balance:",
            chart_data=spark_saldo,
            chart_type="line",
            border=True,
            height="stretch",
        )


def _agrupar_por_orgao(atos: list[Ato]) -> pd.DataFrame:
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
    return pd.DataFrame(linhas).sort_values(
        by=["Total", "Nomeações"], ascending=[False, False]
    )


def _render_bento_visao_geral(atos: list[Ato], historico_edicoes: list[dict]) -> None:
    col_evolucao, col_composicao = st.columns([1.65, 1], gap="medium")

    with col_evolucao:
        with st.container(border=True, height="stretch"):
            col_h, col_seg = st.columns([1.6, 1.3], vertical_alignment="center")
            with col_h:
                st.subheader(
                    "Atividade das edições",
                    icon=":material/monitoring:",
                )
            with col_seg:
                modo_grafico = st.segmented_control(
                    "Visualização do gráfico principal",
                    ["Evolução histórica", "Top órgãos"],
                    default="Evolução histórica" if len(historico_edicoes) >= 2 else "Top órgãos",
                    label_visibility="collapsed",
                    key="bento_modo_grafico",
                )

            if modo_grafico == "Evolução histórica" and historico_edicoes:
                df_hist = pd.DataFrame(
                    [
                        {
                            "Edição": _rotulo_curto_edicao(e["edicao"]),
                            "Total": e["total"],
                            "Nomeações": e["nomeacoes"],
                            "Exonerações": e["exoneracoes"],
                        }
                        for e in historico_edicoes
                    ]
                )
                st.caption(
                    f"Ritmo de publicações nas últimas {len(df_hist)} edições registradas."
                )
                st.echarts_chart(
                    {
                        "tooltip": {"trigger": "axis"},
                        "legend": {"bottom": 0, "icon": "circle"},
                        "grid": {
                            "left": 12,
                            "right": 16,
                            "top": 18,
                            "bottom": 36,
                            "containLabel": True,
                        },
                        "dataset": {"source": df_hist},
                        "xAxis": {
                            "type": "category",
                            "axisLine": {"show": False},
                            "axisTick": {"show": False},
                        },
                        "yAxis": {
                            "type": "value",
                            "minInterval": 1,
                            "splitLine": {"lineStyle": {"type": "dashed", "opacity": 0.35}},
                        },
                        "series": [
                            {
                                "name": "Total de atos",
                                "type": "line",
                                "smooth": True,
                                "symbolSize": 7,
                                "encode": {"x": "Edição", "y": "Total"},
                                "lineStyle": {"width": 3, "color": COR_AZUL_REAL},
                                "itemStyle": {"color": COR_AZUL_REAL},
                                "areaStyle": {
                                    "color": {
                                        "type": "linear",
                                        "x": 0,
                                        "y": 0,
                                        "x2": 0,
                                        "y2": 1,
                                        "colorStops": [
                                            {"offset": 0, "color": "rgba(37, 99, 235, 0.28)"},
                                            {"offset": 1, "color": "rgba(37, 99, 235, 0.02)"},
                                        ],
                                    }
                                },
                            },
                            {
                                "name": "Nomeações",
                                "type": "bar",
                                "barMaxWidth": 18,
                                "encode": {"x": "Edição", "y": "Nomeações"},
                                "itemStyle": {
                                    "color": COR_NOMEACAO,
                                    "borderRadius": [6, 6, 0, 0],
                                },
                            },
                            {
                                "name": "Exonerações",
                                "type": "bar",
                                "barMaxWidth": 18,
                                "encode": {"x": "Edição", "y": "Exonerações"},
                                "itemStyle": {
                                    "color": COR_EXONERACAO,
                                    "borderRadius": [6, 6, 0, 0],
                                },
                            },
                        ],
                    },
                    height=265,
                    key="echarts_evolucao_edicoes",
                    alt="Gráfico de evolução de atos, nomeações e exonerações nas últimas edições",
                )
            else:
                df_top = _agrupar_por_orgao(atos).head(6).iloc[::-1]
                st.caption("Órgãos com maior volume de movimentações nesta edição.")
                st.echarts_chart(
                    {
                        "tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"}},
                        "legend": {"bottom": 0, "icon": "circle"},
                        "grid": {
                            "left": 8,
                            "right": 18,
                            "top": 12,
                            "bottom": 36,
                            "containLabel": True,
                        },
                        "dataset": {"source": df_top},
                        "xAxis": {
                            "type": "value",
                            "minInterval": 1,
                            "splitLine": {"lineStyle": {"type": "dashed", "opacity": 0.35}},
                        },
                        "yAxis": {
                            "type": "category",
                            "axisLine": {"show": False},
                            "axisTick": {"show": False},
                        },
                        "series": [
                            {
                                "name": "Nomeações",
                                "type": "bar",
                                "stack": "total",
                                "barMaxWidth": 20,
                                "encode": {"x": "Nomeações", "y": "Órgão"},
                                "itemStyle": {
                                    "color": COR_NOMEACAO,
                                    "borderRadius": [0, 4, 4, 0],
                                },
                            },
                            {
                                "name": "Exonerações",
                                "type": "bar",
                                "stack": "total",
                                "barMaxWidth": 20,
                                "encode": {"x": "Exonerações", "y": "Órgão"},
                                "itemStyle": {
                                    "color": COR_EXONERACAO,
                                    "borderRadius": [0, 4, 4, 0],
                                },
                            },
                            {
                                "name": "Outros",
                                "type": "bar",
                                "stack": "total",
                                "barMaxWidth": 20,
                                "encode": {"x": "Outros", "y": "Órgão"},
                                "itemStyle": {
                                    "color": COR_AZUL_REAL,
                                    "borderRadius": [0, 6, 6, 0],
                                },
                            },
                        ],
                    },
                    height=265,
                    key="echarts_top_orgaos_bento",
                    alt="Gráfico de barras horizontais dos principais órgãos na edição atual",
                )

    with col_composicao:
        with st.container(border=True, height="stretch"):
            st.subheader("Composição da edição", icon=":material/donut_large:")
            nomeacoes = sum(1 for a in atos if a.tipo == "nomeação")
            exoneracoes = sum(1 for a in atos if a.tipo == "exoneração")
            outros = sum(1 for a in atos if a.tipo == "outro")

            st.caption(
                f"{len(atos)} ato(s) distribuído(s) por natureza administrativa."
            )
            dados_donut = [
                {"name": "Nomeações", "value": nomeacoes, "itemStyle": {"color": COR_NOMEACAO}},
                {"name": "Exonerações", "value": exoneracoes, "itemStyle": {"color": COR_EXONERACAO}},
                {"name": "Outros atos", "value": outros, "itemStyle": {"color": COR_AZUL_REAL}},
            ]
            dados_donut = [d for d in dados_donut if d["value"] > 0]

            st.echarts_chart(
                {
                    "tooltip": {"trigger": "item", "formatter": "{b}: {c} ({d}%)"},
                    "legend": {"bottom": 0, "icon": "circle"},
                    "series": [
                        {
                            "name": "Composição",
                            "type": "pie",
                            "radius": ["54%", "78%"],
                            "center": ["50%", "44%"],
                            "avoidLabelOverlap": True,
                            "padAngle": 3,
                            "itemStyle": {"borderRadius": 8},
                            "label": {
                                "show": True,
                                "position": "center",
                                "formatter": f"{len(atos)}\natos",
                                "fontSize": 22,
                                "fontWeight": "bold",
                            },
                            "emphasis": {
                                "scale": True,
                                "scaleSize": 6,
                            },
                            "labelLine": {"show": False},
                            "data": dados_donut,
                        }
                    ],
                },
                height=265,
                key="echarts_composicao_donut",
                alt="Gráfico de rosca com a proporção entre nomeações, exonerações e outros atos",
            )


def _filtrar_atos_edicao(
    atos: list[Ato],
    termo: str,
    orgao_selecionado: str | None,
    tipo_selecionado: str | None = None,
) -> list[Ato]:
    filtrados = atos
    if tipo_selecionado and tipo_selecionado != "Todos":
        mapa = {
            "Nomeações": "nomeação",
            "Exonerações": "exoneração",
            "Outros": "outro",
        }
        tipo_alvo = mapa.get(tipo_selecionado)
        if tipo_alvo:
            filtrados = [a for a in filtrados if a.tipo == tipo_alvo]
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
            or t in (getattr(a, "detalhes", None) or "").lower()
            or t in (a.decreto or "").lower()
        ]
    return filtrados


@st.fragment
def _render_resumo(
    atos: list[Ato],
    edicao: dict,
    historico_edicoes: list[dict],
) -> None:
    if not atos:
        st.info(
            "Nenhum ato de nomeação ou exoneração foi encontrado nesta edição.",
            icon=":material/search_off:",
            title="Nenhum ato encontrado",
        )
        return

    _render_bento_visao_geral(atos, historico_edicoes)
    st.space("small")

    orgaos_edicao = sorted({a.orgao for a in atos if a.orgao})

    with st.container(border=True, gap="xsmall"):
        col_busca, col_orgao, col_tipo = st.columns(
            [2.0, 1.3, 1.5], vertical_alignment="center"
        )
        with col_busca:
            busca_resumo = st.text_input(
                "Filtrar atos no resumo",
                type="search",
                live=True,
                placeholder="Buscar servidor, cargo, órgão ou decreto…",
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
        with col_tipo:
            tipo_filtro = st.segmented_control(
                "Categoria do ato",
                ["Todos", "Nomeações", "Exonerações", "Outros"],
                default="Todos",
                label_visibility="collapsed",
                key="resumo_tipo_seg",
            )

    atos_filtrados = _filtrar_atos_edicao(
        atos,
        (busca_resumo or "").strip(),
        orgao_filtro,
        tipo_filtro,
    )

    nomeacoes = [a for a in atos_filtrados if a.tipo == "nomeação"]
    exoneracoes = [a for a in atos_filtrados if a.tipo == "exoneração"]
    outros = [a for a in atos_filtrados if a.tipo == "outro"]

    if len(atos_filtrados) != len(atos):
        st.caption(
            f"Exibindo {len(atos_filtrados)} de {len(atos)} atos desta edição. "
            "Clique em **Detalhes** em qualquer cartão para abrir o painel lateral do ato."
        )
    else:
        st.caption(
            "Clique em **Detalhes** em qualquer cartão para inspecionar a ementa e o trecho original do Diário Oficial."
        )

    if tipo_filtro in (None, "Todos"):
        col_nomeacoes, col_exoneracoes = st.columns(2, gap="medium")
        with col_nomeacoes:
            st.subheader(
                f"Nomeações · {len(nomeacoes)}",
                icon=":material/person_add:",
            )
            _lista_resumo(
                nomeacoes,
                "Nenhuma nomeação para os filtros aplicados.",
                key_prefix="nom",
            )
        with col_exoneracoes:
            st.subheader(
                f"Exonerações · {len(exoneracoes)}",
                icon=":material/person_remove:",
            )
            _lista_resumo(
                exoneracoes,
                "Nenhuma exoneração para os filtros aplicados.",
                key_prefix="exo",
            )

        if outros:
            st.caption(
                f":material/info: Há também **{len(outros)} outro(s) ato(s)** de pessoal nesta edição "
                "(licenças, lotações, gratificações, vacâncias). Filtre por **Outros** acima ou acesse a aba **Outros atos**."
            )
    else:
        if not atos_filtrados:
            st.info(
                "Nenhum ato corresponde aos filtros selecionados.",
                icon=":material/search_off:",
                title="Sem resultados",
            )
        else:
            with st.grid(2, gap="small"):
                for idx, ato in enumerate(atos_filtrados):
                    _card_ato(
                        ato,
                        key_prefix=f"flt_{_slug(tipo_filtro)}",
                        idx=idx,
                        mostrar_detalhes=(tipo_filtro == "Outros"),
                    )


@st.fragment
def _render_outros_e_detalhes(atos: list[Ato]) -> None:
    if not atos:
        st.info(
            "Carregue uma edição para consultar outros atos de pessoal e as descrições completas.",
            icon=":material/assignment:",
            title="Nenhum ato carregado",
        )
        return

    outros = [a for a in atos if a.tipo == "outro"]
    with st.container(border=True, gap="xsmall"):
        col_seg, col_busca = st.columns([1.4, 2.0], vertical_alignment="center")
        with col_seg:
            sub_visao = st.segmented_control(
                "Filtro de visualização",
                options=[
                    f"Outros atos ({len(outros)})",
                    f"Todos os atos ({len(atos)})",
                ],
                default=(
                    f"Outros atos ({len(outros)})"
                    if outros
                    else f"Todos os atos ({len(atos)})"
                ),
                label_visibility="collapsed",
                key="seg_outros_detalhes",
            )
        with col_busca:
            busca_det = st.text_input(
                "Filtrar atos nos detalhes",
                type="search",
                live=True,
                placeholder="Buscar servidor, cargo, órgão, portaria/decreto ou ementa…",
                label_visibility="collapsed",
                key="busca_aba_detalhes",
            )

    lista_base = (
        outros if sub_visao and sub_visao.startswith("Outros atos") else atos
    )
    lista_filtrada = _filtrar_atos_edicao(
        lista_base, (busca_det or "").strip(), None
    )

    if not lista_filtrada:
        st.info(
            "Nenhum ato encontrado para o filtro selecionado.",
            icon=":material/search_off:",
            title="Sem resultados",
        )
        return

    st.caption(
        f"Exibindo {len(lista_filtrada)} ato(s). Clique em **Detalhes** para abrir o texto oficial no painel lateral."
    )
    with st.grid(2, gap="small"):
        for idx, ato in enumerate(lista_filtrada):
            _card_ato(
                ato,
                key_prefix="aba_det",
                idx=idx,
                mostrar_detalhes=True,
            )


def _render_orgaos(atos: list[Ato]) -> None:
    if not atos:
        st.info(
            "Carregue uma edição com atos para visualizar a distribuição por órgão.",
            icon=":material/analytics:",
            title="Sem dados para análise",
        )
        return

    df_orgaos = _agrupar_por_orgao(atos)
    df_chart = df_orgaos.iloc[::-1]

    with st.container(border=True):
        st.subheader(
            "Movimentações por secretaria ou órgão",
            icon=":material/bar_chart:",
        )
        st.caption(
            "Comparativo entre nomeações, exonerações e outros atos identificados nesta edição."
        )
        altura_chart = max(260, min(520, len(df_orgaos) * 44 + 80))
        st.echarts_chart(
            {
                "tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"}},
                "legend": {"bottom": 0, "icon": "circle"},
                "grid": {
                    "left": 12,
                    "right": 20,
                    "top": 12,
                    "bottom": 38,
                    "containLabel": True,
                },
                "dataset": {"source": df_chart},
                "xAxis": {
                    "type": "value",
                    "minInterval": 1,
                    "splitLine": {"lineStyle": {"type": "dashed", "opacity": 0.35}},
                },
                "yAxis": {
                    "type": "category",
                    "axisLine": {"show": False},
                    "axisTick": {"show": False},
                },
                "series": [
                    {
                        "name": "Nomeações",
                        "type": "bar",
                        "stack": "total",
                        "barMaxWidth": 22,
                        "encode": {"x": "Nomeações", "y": "Órgão"},
                        "itemStyle": {
                            "color": COR_NOMEACAO,
                            "borderRadius": [0, 4, 4, 0],
                        },
                    },
                    {
                        "name": "Exonerações",
                        "type": "bar",
                        "stack": "total",
                        "barMaxWidth": 22,
                        "encode": {"x": "Exonerações", "y": "Órgão"},
                        "itemStyle": {
                            "color": COR_EXONERACAO,
                            "borderRadius": [0, 4, 4, 0],
                        },
                    },
                    {
                        "name": "Outros",
                        "type": "bar",
                        "stack": "total",
                        "barMaxWidth": 22,
                        "encode": {"x": "Outros", "y": "Órgão"},
                        "itemStyle": {
                            "color": COR_AZUL_REAL,
                            "borderRadius": [0, 6, 6, 0],
                        },
                    },
                ],
            },
            height=altura_chart,
            key="echarts_orgaos_edicao",
            alt="Gráfico de barras horizontais empilhadas com nomeações, exonerações e outros atos por órgão",
        )

    max_total = int(df_orgaos["Total"].max()) if not df_orgaos.empty else 1
    with st.container(border=True):
        st.subheader("Quadro quantitativo por órgão", icon=":material/table_rows:")
        st.dataframe(
            df_orgaos,
            column_config={
                "Órgão": st.column_config.TextColumn(
                    "Órgão", width="large", pinned=True
                ),
                "Nomeações": st.column_config.NumberColumn(
                    "Nomeações", width="small"
                ),
                "Exonerações": st.column_config.NumberColumn(
                    "Exonerações", width="small"
                ),
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

    with st.container(border=True):
        col_info, col_acao = st.columns([3, 1], vertical_alignment="center")
        with col_info:
            st.subheader("Tabela completa da edição", icon=":material/table_chart:")
            st.caption(
                f"{len(atos)} atos nesta edição. Ordene pelas colunas ou utilize a busca integrada."
            )
        with col_acao:
            st.download_button(
                "Baixar CSV",
                data=_csv(registros),
                file_name=f"atos-{base}.csv",
                mime="text/csv",
                icon=":material/download:",
                type="primary",
                width="stretch",
            )

        _mostrar_tabela(registros, altura=490, key="df_tabela_edicao")


@st.fragment
def _render_historico() -> None:
    opcoes = _opcoes_historico_cached()

    with st.container(border=True, gap="xsmall"):
        col_seg, col_busca = st.columns([1.4, 2.0], vertical_alignment="center")
        with col_seg:
            filtro = st.segmented_control(
                "Tipo do ato",
                ["Todos", "Nomeações", "Exonerações", "Outros"],
                default="Todos",
                key="historico_tipo",
                label_visibility="collapsed",
            )
        with col_busca:
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
    out_hist = sum(1 for r in resultados if r.get("tipo") == "outro")

    with st.container(border=True):
        col_info, col_acao = st.columns([3.2, 1], vertical_alignment="center")
        with col_info:
            st.markdown(
                f":blue-badge[:material/history: {len(resultados)} ato(s)] "
                f":green-badge[:material/person_add: {nom_hist} nomeação(ões)] "
                f":red-badge[:material/person_remove: {exo_hist} exoneração(ões)] "
                f":violet-badge[:material/assignment: {out_hist} outro(s)]"
            )
        with col_acao:
            st.download_button(
                "Baixar CSV",
                data=_csv(resultados, incluir_edicao=True),
                file_name="historico-atos.csv",
                mime="text/csv",
                icon=":material/download:",
                type="primary",
                width="stretch",
            )

        _mostrar_tabela(
            resultados,
            incluir_edicao=True,
            altura=490,
            key="df_tabela_historico",
        )


def processar_pdf(url: str, nome_arquivo: str, edicao: str) -> list[Ato]:
    caminho = baixar_edicao(url, nome_arquivo=nome_arquivo)
    texto = extrair_texto_pdf(caminho)
    atos = extrair_atos(texto)
    salvar_atos(atos, edicao=edicao)
    _limpar_cache_banco()
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
            "Você pode consultar outra data ou carregar uma edição salva.",
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


def _render_login() -> None:
    garantir_admin_inicial()
    st.space("medium")
    _, col_centro, _ = st.columns([1.15, 1.7, 1.15])
    with col_centro:
        with st.container(border=True, gap="small"):
            logo_login = (
                LOGO_BRANCO_PATH
                if st.context.theme.type == "dark"
                else LOGO_AZUL_PATH
            )
            if logo_login.exists():
                with st.container(horizontal_alignment="center"):
                    st.image(
                        str(logo_login),
                        width=210,
                        alt="Brasão e marca oficial da Prefeitura Municipal de São Cristóvão",
                    )

            st.subheader(
                "Painel do Diário Oficial",
                icon=":material/newspaper:",
                text_alignment="center",
            )
            st.caption(
                "Prefeitura Municipal de São Cristóvão/SE · "
                "Acesso ao monitoramento de atos administrativos",
                text_alignment="center",
            )
            with st.form("form_login", border=False):
                username = st.text_input(
                    "Usuário",
                    placeholder="Ex.: admin",
                    icon=":material/person:",
                )
                senha = st.text_input(
                    "Senha",
                    type="password",
                    placeholder="Digite sua senha",
                    icon=":material/lock:",
                )
                manter_conectado = st.checkbox(
                    "Manter conectado neste dispositivo (30 dias)",
                    value=True,
                )
                entrar = st.form_submit_button(
                    "Entrar no painel",
                    type="primary",
                    icon=":material/login:",
                    width="stretch",
                )
            if entrar:
                usuario = autenticar_usuario(username, senha)
                if usuario:
                    st.session_state["usuario_logado"] = usuario
                    if manter_conectado:
                        token = criar_sessao_persistente(usuario["id"])
                        st.session_state["token_sessao"] = token
                        st.query_params["sessao"] = token
                    st.rerun()
                else:
                    st.error(
                        "Usuário ou senha inválidos.",
                        icon=":material/error:",
                    )


@st.fragment
def _render_usuarios(usuario_atual: dict) -> None:
    col_lista, col_acoes = st.columns([1.6, 1.1], gap="medium")

    with col_lista:
        with st.container(border=True):
            st.subheader(
                "Usuários cadastrados",
                icon=":material/group:",
            )
            st.caption(
                "Contas com permissão de acesso ao sistema de monitoramento."
            )
            usuarios = listar_usuarios()
            df_usr = pd.DataFrame(usuarios)
            if not df_usr.empty:
                df_usr["papel"] = df_usr["papel"].map(
                    {"admin": "Administrador", "usuario": "Usuário"}
                )
                st.dataframe(
                    df_usr[["nome", "username", "papel", "criado_em"]],
                    column_config={
                        "nome": st.column_config.TextColumn("Nome", width="medium"),
                        "username": st.column_config.TextColumn(
                            "Usuário", width="small"
                        ),
                        "papel": st.column_config.TextColumn(
                            "Perfil", width="small"
                        ),
                        "criado_em": st.column_config.TextColumn(
                            "Criado em", width="small"
                        ),
                    },
                    hide_index=True,
                    width="stretch",
                    alt="Tabela de usuários cadastrados no painel",
                )

            outros_usuarios = [
                u["username"]
                for u in usuarios
                if u["username"] != usuario_atual["username"]
            ]
            if outros_usuarios:
                with st.expander(
                    "Remover ou redefinir senha de usuário",
                    icon=":material/manage_accounts:",
                ):
                    alvo = st.selectbox(
                        "Selecione o usuário",
                        outros_usuarios,
                        key="adm_alvo_user",
                    )
                    nova_senha_adm = st.text_input(
                        "Nova senha (para redefinir)",
                        type="password",
                        placeholder="Mínimo de 6 caracteres",
                        key="adm_nova_senha",
                    )
                    col_reset, col_del = st.columns(2, gap="small")
                    if col_reset.button(
                        "Redefinir senha",
                        icon=":material/key:",
                        width="stretch",
                        key="btn_adm_reset",
                    ):
                        ok, msg = alterar_senha(alvo, nova_senha_adm)
                        if ok:
                            st.success(msg, icon=":material/check_circle:")
                        else:
                            st.error(msg, icon=":material/error:")
                    if col_del.button(
                        "Excluir usuário",
                        icon=":material/delete:",
                        type="secondary",
                        width="stretch",
                        key="btn_adm_del",
                    ):
                        ok, msg = remover_usuario(alvo, usuario_atual["username"])
                        if ok:
                            st.toast(msg, icon=":material/check_circle:")
                            st.rerun()
                        else:
                            st.error(msg, icon=":material/error:")

    with col_acoes:
        with st.container(border=True):
            st.subheader(
                "Novo usuário",
                icon=":material/person_add:",
            )
            st.caption("Cadastre um novo membro da equipe.")
            with st.form("form_criar_usuario", border=False, clear_on_submit=True):
                novo_nome = st.text_input(
                    "Nome completo", placeholder="Ex.: Maria Santos"
                )
                novo_user = st.text_input(
                    "Nome de usuário (login)", placeholder="Ex.: maria.santos"
                )
                nova_senha = st.text_input(
                    "Senha inicial",
                    type="password",
                    placeholder="Mínimo de 6 caracteres",
                )
                novo_papel = st.selectbox(
                    "Perfil de acesso",
                    options=["usuario", "admin"],
                    format_func=lambda p: (
                        "Administrador (gerencia usuários)"
                        if p == "admin"
                        else "Usuário padrão (consulta e exporta)"
                    ),
                )
                cadastrar = st.form_submit_button(
                    "Criar usuário",
                    type="primary",
                    icon=":material/person_add:",
                    width="stretch",
                )
            if cadastrar:
                ok, msg = criar_usuario(
                    novo_user, novo_nome, nova_senha, novo_papel
                )
                if ok:
                    st.toast(msg, icon=":material/check_circle:")
                    st.rerun()
                else:
                    st.error(msg, icon=":material/error:")


# --- Fluxo principal de autenticação ---
usuario_logado = st.session_state.get("usuario_logado")
if not usuario_logado:
    token_url = st.query_params.get("sessao")
    if token_url:
        usuario_recuperado = validar_sessao_persistente(token_url)
        if usuario_recuperado:
            usuario_logado = usuario_recuperado
            st.session_state["usuario_logado"] = usuario_recuperado
            st.session_state["token_sessao"] = token_url
        else:
            st.query_params.pop("sessao", None)

if not usuario_logado:
    _render_login()
    st.stop()

hoje = date.today()
chave_hoje = hoje.isoformat()

if st.session_state.get("tentativa_dia") != chave_hoje:
    st.session_state["tentativa_dia"] = chave_hoje
    processar_diario(hoje)

opcoes_hist = _opcoes_historico_cached()
edicoes_salvas = opcoes_hist["edicoes"]
historico_edicoes = _serie_edicoes_cached(limite=12)

# --- Barra lateral institucional (Azul Marinho São Cristóvão) ---
with st.sidebar:
    if LOGO_BRANCO_PATH.exists():
        st.image(
            str(LOGO_BRANCO_PATH),
            width=205,
            alt="Prefeitura Municipal de São Cristóvão — Cidade Mãe de Sergipe",
        )
    st.caption("Monitoramento do Diário Oficial")

    with st.container(border=True, gap="xsmall"):
        st.markdown(
            f":material/account_circle: **{_md(usuario_logado['nome'])}**  \n"
            f"`@{_md(usuario_logado['username'])}` · "
            f"{'Admin' if usuario_logado.get('papel') == 'admin' else 'Usuário'}"
        )
        col_pwd, col_out = st.columns(2, gap="xsmall")
        with col_pwd:
            with st.popover(
                "Senha", icon=":material/lock_reset:", width="stretch"
            ):
                with st.form(
                    "form_minha_senha", border=False, clear_on_submit=True
                ):
                    senha_atual_in = st.text_input(
                        "Senha atual", type="password"
                    )
                    senha_nova_in = st.text_input("Nova senha", type="password")
                    salvar_senha = st.form_submit_button(
                        "Atualizar",
                        type="primary",
                        width="stretch",
                    )
                if salvar_senha:
                    ok, msg = alterar_senha(
                        usuario_logado["username"],
                        senha_nova_in,
                        senha_atual=senha_atual_in,
                    )
                    if ok:
                        st.success(msg, icon=":material/check_circle:")
                    else:
                        st.error(msg, icon=":material/error:")
        with col_out:
            if st.button(
                "Sair",
                icon=":material/logout:",
                width="stretch",
                key="btn_logout",
            ):
                token_atual = st.session_state.pop(
                    "token_sessao", None
                ) or st.query_params.get("sessao")
                encerrar_sessao_persistente(token_atual)
                st.query_params.pop("sessao", None)
                st.session_state.pop("usuario_logado", None)
                st.rerun()

    st.subheader("Consultar edição", icon=":material/search:")
    st.caption(f"Referência: {hoje:%d/%m/%Y}")

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
        with st.expander("Edições salvas", icon=":material/inventory_2:"):
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

    with st.expander("Importar PDF / ID", icon=":material/link:"):
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
                        atos_manual = processar_pdf(url, f"{nome}.pdf", nome)
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
                            f"{len(atos_manual)} atos extraídos.",
                            icon=":material/check_circle:",
                        )

    edicao_sidebar = st.session_state.get("edicao_atual")
    with st.container(border=True, gap="xxsmall"):
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

    st.caption("Fonte: Portal Oficial · saocristovao.se.gov.br")

# --- Área principal do Dashboard ---
edicao_atual = st.session_state.get("edicao_atual")
atos = st.session_state.get("atos_processados", [])

_render_cabecalho_acoes(edicao_atual or {}, atos)

if edicao_atual:
    _render_edicao(edicao_atual, atos)
else:
    with st.container(border=True):
        col_msg, col_quick = st.columns([3, 1.3], vertical_alignment="center")
        with col_msg:
            st.markdown(
                ":material/event_note: **Nenhuma edição carregada no momento.**  \n"
                "Consulte outra data na barra lateral ou carregue a última edição registrada no banco."
            )
        with col_quick:
            if edicoes_salvas:
                ultima = edicoes_salvas[0]
                if st.button(
                    "Abrir última edição",
                    icon=":material/history:",
                    type="primary",
                    width="stretch",
                    key="btn_abrir_ultima_salva",
                ):
                    atos_ult = carregar_atos_edicao(ultima)
                    st.session_state["atos_processados"] = atos_ult
                    st.session_state["edicao_atual"] = {"titulo": ultima}
                    st.rerun()

if atos:
    st.space("small")
    _render_metricas(atos, historico_edicoes)

st.space("small")
abas_titulos = [
    ":material/dashboard: Resumo",
    f":material/assignment: Outros atos ({sum(1 for a in atos if a.tipo == 'outro')})",
    ":material/analytics: Por órgão",
    ":material/table_chart: Tabela",
    ":material/history: Histórico",
]
if usuario_logado.get("papel") == "admin":
    abas_titulos.append(":material/manage_accounts: Usuários")

abas = st.tabs(abas_titulos, on_change="rerun", key="aba_principal")

with abas[0]:
    if abas[0].open:
        _render_resumo(atos, edicao_atual or {}, historico_edicoes)

with abas[1]:
    if abas[1].open:
        _render_outros_e_detalhes(atos)

with abas[2]:
    if abas[2].open:
        _render_orgaos(atos)

with abas[3]:
    if abas[3].open:
        _render_tabela(atos, edicao_atual or {})

with abas[4]:
    if abas[4].open:
        _render_historico()

if usuario_logado.get("papel") == "admin" and len(abas) > 5:
    with abas[5]:
        if abas[5].open:
            _render_usuarios(usuario_logado)
