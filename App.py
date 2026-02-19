import streamlit as st
import pandas as pd
import easyocr
import os
import re
import numpy as np
import plotly.express as px
from PIL import Image
from datetime import datetime
from pdf2image import convert_from_bytes
from sqlalchemy import create_engine, text

# --- CONFIGURAÇÃO DB SUPABASE ---
@st.cache_resource
def get_engine():
    return create_engine(st.secrets["connections"]["financeiro"]["url"])

def init_db():
    engine = get_engine()
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS "Lançamentos" (
                id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                data TEXT,
                valor NUMERIC(12,2),
                descricao TEXT,
                categoria TEXT,
                data_registro TIMESTAMPTZ DEFAULT NOW(),
                pago BOOLEAN DEFAULT FALSE
            )
        """))
        conn.commit()

def salvar_no_db(data_doc, valor, desc, cat, pago):
    engine = get_engine()
    
    # Valor sempre definido, com fallback
    valor_limpo = 0.0
    try:
        valor_str = str(valor).strip()  # Converte para string e remove espaços
        if valor_str:  # Evita erro em vazio
            valor_limpo = float(valor_str.replace('.', '').replace(',', '.'))
    except (ValueError, AttributeError):
        st.warning(f"Valor inválido ou vazio: '{valor}'. Salvo como R$ 0,00.")
    
    with engine.connect() as conn:
        conn.execute(text("""
            INSERT INTO "Lançamentos" (data, valor, descricao, categoria, pago)
            VALUES (:data, :valor, :descricao, :categoria, :pago)
        """), {
            "data": data_doc,
            "valor": valor_limpo,
            "descricao": desc,
            "categoria": cat,
            "pago": pago
        })
        conn.commit()

def acoes_db(id_reg, acao):
    engine = get_engine()
    with engine.connect() as conn:
        if acao == "pagar":
            conn.execute(text('UPDATE "Lançamentos" SET pago = TRUE WHERE id = :id'), {"id": id_reg})
        elif acao == "excluir":
            conn.execute(text('DELETE FROM "Lançamentos" WHERE id = :id'), {"id": id_reg})
        conn.commit()

# --- APP STREAMLIT ---
st.set_page_config(page_title="Terminal Financeiro v3.6 - Supabase", layout="wide")
init_db()

@st.cache_resource
def load_model():
    return easyocr.Reader(['pt'], gpu=os.path.exists('/opt/bin/nvidia-smi'))

reader = load_model()

st.title("💰 Gestão Financeira Absoluta")

tab1, tab2 = st.tabs(["🚀 Lançamentos", "📊 Dashboard & Gestão"])

with tab1:
    if 'dados_temp' not in st.session_state:
        st.session_state['dados_temp'] = {'data': datetime.now().strftime("%d/%m/%Y"), 'valor': '0,00', 'desc': '', 'cat': 'Outros'}

    col_scan, col_manual = st.columns([1, 1])

    with col_scan:
        st.subheader("📷 Scanner de Boletos")
        uploaded_file = st.file_uploader("Upload PDF/Imagem", type=["png", "jpg", "jpeg", "pdf"])

        if uploaded_file:
            try:
                if uploaded_file.type == "application/pdf":
                    # Correção principal: força o caminho do Poppler instalado pelo packages.txt
                    img = convert_from_bytes(uploaded_file.read(), dpi=250, poppler_path="/usr/bin")[0]
                else:
                    img = Image.open(uploaded_file)
                st.image(img, width=250)
            except Exception as e:
                st.error(f"Erro ao processar o arquivo: {str(e)}. Tente com uma imagem PNG/JPG ou verifique se o PDF é válido.")
                st.stop()

            if st.button("🔍 Escanear Agora"):
                try:
                    res = reader.readtext(np.array(img), detail=0)
                    txt = " ".join(res).lower()

                    desc, cat = "Outros", "Outros"
                    if any(x in txt for x in ['condominio', 'condomínio']): desc, cat = "Condomínio", "Moradia"
                    elif any(x in txt for x in ['ceee', 'equatorial', 'energia', 'luz']): desc, cat = "Energia (CEEE)", "Moradia"

                    vals = re.findall(r'(\d{1,3}(?:\.\d{3})*,\d{2})', txt)
                    nums = sorted(list(set([float(v.replace('.', '').replace(',', '.')) for v in vals if float(v.replace('.', '').replace(',', '.')) > 5.0])), reverse=True)

                    v_calc = nums[0] if nums else 0.0

                    datas = re.findall(r'(\d{2}/\d{2}/\d{4})', txt)
                    hoje = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
                    dts = [datetime.strptime(d, "%d/%m/%Y") for d in datas if datetime.strptime(d, "%d/%m/%Y") >= hoje]
                    venc = max(dts) if dts else hoje

                    st.session_state['dados_temp'] = {
                        'data': venc.strftime("%d/%m/%Y"),
                        'valor': f"{v_calc:,.2f}".replace('.', 'X').replace(',', '.').replace('X', ','),
                        'desc': desc, 'cat': cat
                    }
                    st.rerun()
                except Exception as e:
                    st.error(f"Erro no OCR: {str(e)}. Tente uma imagem mais clara ou PDF simples.")

    with col_manual:
        st.subheader("⌨️ Entrada de Dados")
        if st.button("➕ Novo Lançamento Manual"):
            st.session_state['dados_temp'] = {'data': datetime.now().strftime("%d/%m/%Y"), 'valor': '0,00', 'desc': '', 'cat': 'Outros'}
            st.rerun()

        with st.form("form_financeiro"):
            f_desc = st.text_input("O que é? (Ex: Plano de Saúde)", value=st.session_state['dados_temp']['desc'])
            lista_cats = ["Moradia", "Saúde", "Alimentação", "Contas", "Transporte", "Educação", "Investimento", "Outros"]
            f_cat = st.selectbox("Categoria", lista_cats, index=lista_cats.index(st.session_state['dados_temp']['cat']) if st.session_state['dados_temp']['cat'] in lista_cats else 0)

            c_d, c_v = st.columns(2)
            f_data = c_d.text_input("Vencimento", value=st.session_state['dados_temp']['data'])
            f_valor = c_v.text_input("Valor R$", value=st.session_state['dados_temp']['valor'])
            f_pago = st.checkbox("Já paguei este valor")

            if st.form_submit_button("✅ SALVAR NO SISTEMA"):
                if not f_valor.strip():
                    st.error("Preencha o valor antes de salvar!")
                else:
                    salvar_no_db(f_data, f_valor, f_desc, f_cat, f_pago)
                    st.success("Registrado!")
                    st.balloons()

with tab2:
    try:
        df = pd.read_sql('SELECT * FROM "Lançamentos" ORDER BY data_registro DESC', get_engine().connect())
    except Exception as e:
        st.error(f"Erro ao carregar dados: {str(e)}")
        df = pd.DataFrame()  # Evita crash total

    if not df.empty:
        df['dt'] = pd.to_datetime(df['data'], dayfirst=True, errors='coerce')

        pendente = df[df['pago'] == False]['valor'].sum()
        st.info(f"💰 Você ainda tem **R$ {pendente:,.2f}** em contas pendentes.")

        g1, g2 = st.columns(2)
        with g1:
            st.write("📊 Gastos Mensais")
            df['mes'] = df['dt'].dt.strftime('%m/%Y')
            evol = df.groupby('mes')['valor'].sum().reset_index()
            st.bar_chart(evol.set_index('mes'))

        with g2:
            st.write("🍕 Divisão por Setor")
            setor = df.groupby('categoria')['valor'].sum().reset_index()
            fig = px.pie(setor, values='valor', names='categoria', hole=0.4, color_discrete_sequence=px.colors.qualitative.Safe)
            st.plotly_chart(fig, use_container_width=True)

        st.divider()
        for i, r in df.sort_values('dt', ascending=False).iterrows():
            status = "✅ PAGO" if r['pago'] else "⏳ PENDENTE"
            with st.expander(f"{status} | {r['data']} | {r['descricao']} | R$ {r['valor']:.2f}"):
                c1, c2 = st.columns(2)
                if not r['pago'] and c1.button("Confirmar Pagamento", key=f"pay{r['id']}"):
                    acoes_db(r['id'], "pagar")
                    st.rerun()
                if c2.button("Excluir Registro", key=f"del{r['id']}"):
                    acoes_db(r['id'], "excluir")
                    st.rerun()
    else:
        st.info("Nenhum dado encontrado.")
