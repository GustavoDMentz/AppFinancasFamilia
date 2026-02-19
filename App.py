%%writefile app.py
import streamlit as st
import pandas as pd
import sqlite3
import easyocr
import os
import re
import numpy as np
import plotly.express as px
from PIL import Image
from datetime import datetime
from pdf2image import convert_from_bytes

# --- CONFIGURAÇÃO DB ---
DB_NAME = "financeiro.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS lancamentos
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  data TEXT, valor REAL, descricao TEXT, categoria TEXT,
                  data_registro TEXT, pago INTEGER DEFAULT 0)''')
    conn.commit()
    conn.close()

def salvar_no_db(data_doc, valor, desc, cat, pago):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    try:
        valor_limpo = float(valor.replace('.', '').replace(',', '.'))
    except:
        valor_limpo = 0.0
    data_reg = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute("INSERT INTO lancamentos (data, valor, descricao, categoria, data_registro, pago) VALUES (?, ?, ?, ?, ?, ?)",
              (data_doc, valor_limpo, desc, cat, data_reg, 1 if pago else 0))
    conn.commit()
    conn.close()

def acoes_db(id_reg, acao):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    if acao == "pagar":
        c.execute("UPDATE lancamentos SET pago = 1 WHERE id = ?", (id_reg,))
    elif acao == "excluir":
        c.execute("DELETE FROM lancamentos WHERE id = ?", (id_reg,))
    conn.commit()
    conn.close()

# --- APP STREAMLIT ---
st.set_page_config(page_title="Terminal Financeiro v3.6", layout="wide")
init_db()

@st.cache_resource
def load_model():
    return easyocr.Reader(['pt'], gpu=os.path.exists('/opt/bin/nvidia-smi'))

reader = load_model()

st.title("💰 Gestão Financeira Absoluta")

tab1, tab2 = st.tabs(["🚀 Lançamentos", "📊 Dashboard & Gestão"])

with tab1:
    # Estado inicial para manual ou scanner
    if 'dados_temp' not in st.session_state:
        st.session_state['dados_temp'] = {'data': datetime.now().strftime("%d/%m/%Y"), 'valor': '0,00', 'desc': '', 'cat': 'Outros'}

    col_scan, col_manual = st.columns([1, 1])

    with col_scan:
        st.subheader("📷 Scanner de Boletos")
        uploaded_file = st.file_uploader("Upload PDF/Imagem", type=["png", "jpg", "jpeg", "pdf"])

        if uploaded_file:
            if uploaded_file.type == "application/pdf":
                img = convert_from_bytes(uploaded_file.read(), dpi=250)[0]
            else:
                img = Image.open(uploaded_file)
            st.image(img, width=250)

            if st.button("🔍 Escanear Agora"):
                res = reader.readtext(np.array(img), detail=0)
                txt = " ".join(res).lower()

                # --- REGRAS SEPARADAS ---
                desc, cat, tipo = "Outros", "Outros", "outro"
                if any(x in txt for x in ['condominio', 'condomínio']): desc, cat, tipo = "Condomínio", "Moradia", "condo"
                elif any(x in txt for x in ['ceee', 'equatorial', 'energia', 'luz']): desc, cat, tipo = "Energia (CEEE)", "Moradia", "luz"

                # Valores
                vals = re.findall(r'(\d{1,3}(?:\.\d{3})*,\d{2})', txt)
                nums = sorted(list(set([float(v.replace('.', '').replace(',', '.')) for v in vals if float(v.replace('.', '').replace(',', '.')) > 5.0])), reverse=True)

                v_calc = 0.0
                if nums:
                    if tipo == "luz": v_calc = nums[0] # REGRA LUZ: MAIOR
                    elif tipo == "condo": v_calc = nums[1] if len(nums) > 1 else nums[0] # REGRA CONDO: PRINCIPAL
                    else: v_calc = nums[0]

                # Datas (Futuro ou Hoje)
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
                salvar_no_db(f_data, f_valor, f_desc, f_cat, f_pago)
                st.success("Registrado!")
                st.balloons()

with tab2:
    conn = sqlite3.connect(DB_NAME)
    df = pd.read_sql_query("SELECT * FROM lancamentos", conn)
    conn.close()

    if not df.empty:
        df['dt'] = pd.to_datetime(df['data'], dayfirst=True)

        # Métrica de Resumo
        pendente = df[df['pago'] == 0]['valor'].sum()
        st.info(f"💰 Você ainda tem **R$ {pendente:,.2f}** em contas pendentes.")

        # --- DASHBOARD ---
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
        # --- LISTA DE GESTÃO ---
        for i, r in df.sort_values('dt', ascending=False).iterrows():
            status = "✅ PAGO" if r['pago'] else "⏳ PENDENTE"
            with st.expander(f"{status} | {r['data']} | {r['descricao']} | R$ {r['valor']:.2f}"):
                c1, c2 = st.columns(2)
                if not r['pago'] and c1.button("Confirmar Pagamento", key=f"pay{r['id']}"):
                    acoes_db(r['id'], "pagar"); st.rerun()
                if c2.button("Excluir Registro", key=f"del{r['id']}"):
                    acoes_db(r['id'], "excluir"); st.rerun()
    else:
        st.info("Nenhum dado encontrado.")
