import streamlit as st
import pandas as pd
import os
import re
import numpy as np
import plotly.express as px
from PIL import Image
from datetime import datetime
from dateutil.relativedelta import relativedelta
from sqlalchemy import create_engine, text
import pytesseract
from pdf2image import convert_from_bytes

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
                pago BOOLEAN DEFAULT FALSE,
                quem_pagou TEXT
            )
        """))
        conn.commit()

def salvar_no_db(data_doc, valor, desc, cat, pago, quem_pagou="", parcelas=1):
    engine = get_engine()
    
    valor_total = 0.0
    try:
        valor_str = str(valor).strip()
        if valor_str:
            valor_total = float(valor_str.replace('.', '').replace(',', '.'))
    except (ValueError, AttributeError):
        st.warning(f"Valor inválido ou vazio: '{valor}'. Salvo como R$ 0,00.")
        valor_total = 0.0
    
    if parcelas < 1:
        parcelas = 1
    
    valor_parcela = round(valor_total / parcelas, 2)
    
    data_inicial = datetime.strptime(data_doc, "%d/%m/%Y")
    
    with engine.connect() as conn:
        for i in range(parcelas):
            parcela_num = i + 1
            desc_parcela = f"Parcela {parcela_num}/{parcelas} - {desc}" if parcelas > 1 else desc
            data_parcela = data_inicial + relativedelta(months=i)
            data_parcela_str = data_parcela.strftime("%d/%m/%Y")
            
            conn.execute(text("""
                INSERT INTO "Lançamentos" (data, valor, descricao, categoria, pago, quem_pagou)
                VALUES (:data, :valor, :descricao, :categoria, :pago, :quem_pagou)
            """), {
                "data": data_parcela_str,
                "valor": valor_parcela,
                "descricao": desc_parcela,
                "categoria": cat,
                "pago": pago if parcela_num == 1 else False,
                "quem_pagou": quem_pagou if parcela_num == 1 else None
            })
        conn.commit()

def acoes_db(id_reg, acao, quem_pagou=None):
    engine = get_engine()
    with engine.connect() as conn:
        if acao == "pagar":
            conn.execute(text('UPDATE "Lançamentos" SET pago = TRUE, quem_pagou = :quem WHERE id = :id'), {
                "quem": quem_pagou.strip() if quem_pagou else None,
                "id": id_reg
            })
        elif acao == "excluir":
            conn.execute(text('DELETE FROM "Lançamentos" WHERE id = :id'), {"id": id_reg})
        conn.commit()

# --- APP STREAMLIT ---
st.set_page_config(
    page_title="Terminal Financeiro Família",
    layout="wide",
    initial_sidebar_state="collapsed",
    page_icon="💰"
)

init_db()

st.markdown("""
    <style>
    .stButton > button {
        width: 100%;
        height: 3.2rem;
        font-size: 1.2rem;
        margin-top: 1rem;
    }
    .stExpander {
        font-size: 1.1rem;
        margin-bottom: 1rem;
    }
    .stTabs [data-baseweb="tab-list"] {
        gap: 0.8rem;
        flex-wrap: wrap;
    }
    .stForm > div {
        gap: 1.2rem !important;
    }
    label {
        font-size: 1.1rem !important;
        font-weight: 500;
    }
    </style>
""", unsafe_allow_html=True)

st.title("💰 Gestão Financeira Família")

tab_ocr, tab_contas, tab_cartao, tab_dashboard = st.tabs([
    "Scanner OCR",
    "Contas Fixas / Consumo",
    "Compras no Cartão (Parceladas)",
    "Dashboard & Gestão"
])

with tab_ocr:
    st.subheader("📷 Scanner de Boletos (Tesseract)")
    uploaded_file = st.file_uploader("Envie o boleto (PDF ou imagem)", type=["png", "jpg", "jpeg", "pdf"])

    if uploaded_file:
        try:
            if uploaded_file.type == "application/pdf":
                images = convert_from_bytes(uploaded_file.read(), first_page=1, last_page=1, dpi=200)
                img = images[0]
            else:
                img = Image.open(uploaded_file)
            st.image(img, use_column_width=True)

            if st.button("🔍 Escanear Boleto"):
                with st.spinner("Lendo boleto..."):
                    txt = pytesseract.image_to_string(img, lang='por', config='--psm 6')
                    txt = txt.lower()

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
                        'desc': desc, 'cat': cat,
                        'quem_pagou': "",
                        'parcelado': False,
                        'parcelas': 1
                    }
                    st.rerun()
        except Exception as e:
            st.error(f"Erro ao ler boleto: {str(e)}. Tente uma imagem clara ou PDF de 1 página.")

with tab_contas:
    st.subheader("Contas Fixas / Consumo")
    st.info("Luz, água, condomínio, mercado à vista... (sem parcelamento)")

    if st.button("Limpar formulário"):
        st.session_state['dados_temp'] = {'data': datetime.now().strftime("%d/%m/%Y"), 'valor': '0,00', 'desc': '', 'cat': 'Outros', 'quem_pagou': ''}
        st.rerun()

    with st.form("form_contas"):
        f_desc = st.text_input("Descrição (ex: Conta de Luz CEEE)", value=st.session_state.get('dados_temp', {}).get('desc', ''))
        lista_cats = ["Moradia", "Contas", "Transporte", "Educação", "Saúde", "Alimentação", "Outros"]
        f_cat = st.selectbox("Categoria", lista_cats, index=lista_cats.index(st.session_state.get('dados_temp', {}).get('cat', 'Outros')) if st.session_state.get('dados_temp', {}).get('cat') in lista_cats else 0)

        c_d, c_v = st.columns(2)
        f_data = c_d.text_input("Vencimento (dd/mm/aaaa)", value=st.session_state.get('dados_temp', {}).get('data', datetime.now().strftime("%d/%m/%Y")))
        f_valor = c_v.text_input("Valor R$", value=st.session_state.get('dados_temp', {}).get('valor', '0,00'))

        f_pago = st.checkbox("Já paguei")
        f_quem_pagou = st.text_input("Quem pagou? (nome)", value=st.session_state.get('dados_temp', {}).get('quem_pagou', ''))

        if st.form_submit_button("✅ Salvar Conta"):
            if not f_valor.strip():
                st.error("Preencha o valor!")
            else:
                salvar_no_db(f_data, f_valor, f_desc, f_cat, f_pago, f_quem_pagou, parcelas=1)  # Sempre 1 parcela
                st.success("Conta salva!")
                st.balloons()
                st.session_state['dados_temp'] = {'data': datetime.now().strftime("%d/%m/%Y"), 'valor': '0,00', 'desc': '', 'cat': 'Outros', 'quem_pagou': ''}

with tab_cartao:
    st.subheader("Compras Parceladas no Cartão")
    st.info("Celular, supermercado parcelado, etc. (registra todas as parcelas futuras)")

    with st.form("form_cartao"):
        f_desc = st.text_input("Descrição (ex: Celular 10x no cartão)", value=st.session_state.get('dados_temp', {}).get('desc', ''))
        lista_cats = ["Saúde", "Educação", "Moradia", "Alimentação", "Transporte", "Investimento", "Outros"]
        f_cat = st.selectbox("Categoria", lista_cats, index=lista_cats.index(st.session_state.get('dados_temp', {}).get('cat', 'Outros')) if st.session_state.get('dados_temp', {}).get('cat') in lista_cats else 0)

        c_d, c_v = st.columns(2)
        f_data = c_d.text_input("Data da primeira parcela (dd/mm/aaaa)", value=st.session_state.get('dados_temp', {}).get('data', datetime.now().strftime("%d/%m/%Y")))
        f_valor = c_v.text_input("Valor TOTAL da compra R$", value=st.session_state.get('dados_temp', {}).get('valor', '0,00'))

        # Checkbox retangular + condicional
        f_parcelado = st.checkbox("Parcelado?", value=True, help="Marque se a compra está em parcelas (padrão no cartão).")
        f_parcelas = 1
        if f_parcelado:
            f_parcelas = st.number_input("Quantas parcelas?", min_value=2, max_value=36, value=10, step=1, help="Valor total será dividido igualmente entre as parcelas.")

        f_pago = st.checkbox("Primeira parcela já veio na fatura e foi paga")
        f_quem_pagou = st.text_input("Quem pagou/pagará as parcelas? (nome)", value=st.session_state.get('dados_temp', {}).get('quem_pagou', ''))

        if st.form_submit_button("✅ Salvar Compra(s) no Cartão"):
            if not f_valor.strip():
                st.error("Preencha o valor total da compra!")
            else:
                salvar_no_db(f_data, f_valor, f_desc, f_cat, f_pago, f_quem_pagou, f_parcelas)
                st.success(f"{f_parcelas} parcela(s) registrada(s)!")
                st.balloons()
                st.session_state['dados_temp'] = {'data': datetime.now().strftime("%d/%m/%Y"), 'valor': '0,00', 'desc': '', 'cat': 'Outros', 'quem_pagou': '', 'parcelado': False, 'parcelas': 1}

with tab_dashboard:
    try:
        df = pd.read_sql('SELECT * FROM "Lançamentos" ORDER BY data_registro DESC', get_engine().connect())
    except Exception as e:
        st.error(f"Erro ao carregar dados: {str(e)}")
        df = pd.DataFrame()

    if not df.empty:
        df['dt'] = pd.to_datetime(df['data'], dayfirst=True, errors='coerce')

        pendente_total = df[df['pago'] == False]['valor'].sum()
        st.info(f"💰 Contas pendentes totais: **R$ {pendente_total:,.2f}**")

        pagos_por_pessoa = df[df['pago'] == True].groupby('quem_pagou')['valor'].sum().reset_index()
        if not pagos_por_pessoa.empty:
            st.subheader("Pagamentos por pessoa")
            st.dataframe(pagos_por_pessoa.style.format({"valor": "R$ {:,.2f}"}))
            st.info(f"Total pago até agora: **R$ {pagos_por_pessoa['valor'].sum():,.2f}**")

        g1, g2 = st.columns(2)
        with g1:
            st.subheader("Gastos Mensais")
            df['mes'] = df['dt'].dt.strftime('%m/%Y')
            evol = df.groupby('mes')['valor'].sum().reset_index()
            st.bar_chart(evol.set_index('mes'))

        with g2:
            st.subheader("Divisão por Categoria")
            setor = df.groupby('categoria')['valor'].sum().reset_index()
            fig = px.pie(setor, values='valor', names='categoria', hole=0.4, color_discrete_sequence=px.colors.qualitative.Safe)
            st.plotly_chart(fig, use_container_width=True)

        st.divider()
        st.subheader("Lista de Lançamentos")
        for i, r in df.sort_values('dt', ascending=False).iterrows():
            status = "✅ PAGO" if r['pago'] else "⏳ PENDENTE"
            quem = f" | Pago por: {r['quem_pagou']}" if r['pago'] and r['quem_pagou'] else ""
            with st.expander(f"{status}{quem} | {r['data']} | {r['descricao']} | R$ {r['valor']:.2f}"):
                c1, c2 = st.columns(2)
                if not r['pago'] and c1.button("Confirmar Pagamento", key=f"pay{r['id']}"):
                    quem_pagou = st.text_input("Quem pagou?", key=f"quem{r['id']}")
                    if st.button("Confirmar", key=f"conf{r['id']}"):
                        acoes_db(r['id'], "pagar", quem_pagou)
                        st.rerun()
                if c2.button("Excluir", key=f"del{r['id']}"):
                    acoes_db(r['id'], "excluir")
                    st.rerun()
    else:
        st.info("Nenhum lançamento ainda. Comece adicionando no scanner ou nas abas de contas/cartão.")
