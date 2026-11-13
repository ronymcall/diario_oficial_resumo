import streamlit as st
from datetime import date

from config import BASE_URL
from scraper import obter_edicao_do_dia, baixar_edicao, extrair_texto_pdf
from processor import extrair_atos, gerar_resumo
from utils import salvar_atos, carregar_atos
from utils.notifier import enviar_telegram

st.set_page_config(page_title="Resumo DO — São Cristóvão", page_icon="📰")
st.title("📰 Resumo do Diário Oficial — São Cristóvão/SE")

hoje = date.today()
chave_hoje = hoje.isoformat()


def processar_pdf(url: str, nome_arquivo: str, edicao: str) -> list:
    caminho = baixar_edicao(url, nome_arquivo=nome_arquivo)
    texto = extrair_texto_pdf(caminho)
    atos = extrair_atos(texto)
    salvar_atos(atos, edicao=edicao)
    st.session_state["atos_processados"] = atos
    return atos


def processar_diario(dia: date) -> None:
    with st.spinner(f"Buscando edição de {dia.strftime('%d/%m/%Y')}..."):
        try:
            edicao = obter_edicao_do_dia(dia)
        except Exception as e:
            st.error(f"Erro ao buscar edição: {e}")
            return

    if not edicao:
        st.session_state.pop("atos_processados", None)
        st.session_state.pop("edicao_atual", None)
        st.warning(f"Não há edição publicada em {dia.strftime('%d/%m/%Y')}.")
        return

    with st.spinner(f"Baixando e processando {edicao['titulo']}..."):
        try:
            atos = processar_pdf(edicao["url"], f"edicao-{edicao['id']}.pdf", edicao["titulo"])
        except Exception as e:
            st.error(f"Erro: {e}")
            return

    st.session_state["edicao_atual"] = edicao
    st.success(f"✅ {edicao['titulo']}: {len(atos)} atos extraídos.")


if st.session_state.get("tentativa_dia") != chave_hoje:
    st.session_state["tentativa_dia"] = chave_hoje
    processar_diario(hoje)

# --- Sidebar ---
with st.sidebar:
    st.header("⚙️ Diário Oficial")
    st.caption(f"Hoje: {hoje.strftime('%d/%m/%Y')}")

    if st.button("🔄 Atualizar diário de hoje"):
        processar_diario(hoje)

    st.divider()
    st.subheader("🔎 Buscar por data")
    dia_busca = st.date_input(
        "Escolha a data:",
        value=hoje,
        max_value=hoje,
        format="DD/MM/YYYY",
    )
    if st.button("Buscar edição da data"):
        processar_diario(dia_busca)

    edicao_atual = st.session_state.get("edicao_atual")
    if edicao_atual:
        st.info(edicao_atual["titulo"])

    with st.expander("📄 Usar PDF/ID manualmente"):
        entrada = st.text_input("ID da edição ou URL do PDF:", placeholder="8064")
        if st.button("Processar PDF informado"):
            valor = entrada.strip()
            if not valor:
                st.warning("Informe o ID ou a URL do PDF.")
            else:
                url = f"{BASE_URL}/portal/edicoes/download/{valor}" if valor.isdigit() else valor
                nome = f"edicao-{valor[:80]}"
                with st.spinner("Baixando e processando..."):
                    try:
                        atos = processar_pdf(url, f"{nome}.pdf", nome)
                    except Exception as e:
                        st.error(f"Erro: {e}")
                    else:
                        st.session_state.pop("edicao_atual", None)
                        st.success(f"✅ {len(atos)} atos extraídos.")

# --- Conteúdo principal ---
if edicao_atual:
    st.subheader(edicao_atual["titulo"])

tab_resumo, tab_tabela, tab_historico = st.tabs(["📋 Resumo", "📊 Tabela", "🕐 Histórico"])

with tab_resumo:
    if "atos_processados" in st.session_state:
        atos = st.session_state["atos_processados"]
        if not atos:
            st.warning("Nenhum ato de nomeação/exoneração encontrado nesta edição.")
        else:
            resumo = gerar_resumo(atos)
            st.markdown(resumo)
            if st.button("📤 Enviar por Telegram"):
                enviar_telegram(resumo)
                st.success("Resumo enviado (se as credenciais estiverem configuradas).")
    else:
        st.info("Nenhuma edição processada.")

with tab_tabela:
    if "atos_processados" in st.session_state:
        import pandas as pd
        df = pd.DataFrame([a.__dict__ for a in st.session_state["atos_processados"]])
        st.dataframe(df, use_container_width=True)
    else:
        st.info("Nenhum dado carregado.")

with tab_historico:
    filtro_tipo = st.selectbox("Tipo:", ["todos", "nomeação", "exoneração", "outro"])
    busca = st.text_input("Buscar por nome:")
    tipo = None if filtro_tipo == "todos" else filtro_tipo
    resultados = carregar_atos(tipo=tipo, busca=busca or None)
    if resultados:
        import pandas as pd
        st.dataframe(pd.DataFrame(resultados), use_container_width=True)
    else:
        st.info("Nenhum ato no histórico.")
