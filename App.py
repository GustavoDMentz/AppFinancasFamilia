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

# ==========================================
# CONFIGURAÇÃO DA PÁGINA (Otimizado Mobile)
# ==========================================
st.set_page_config(
    page_title="Terminal Financeiro",
    layout="centered", # Centered funciona melhor no mobile nativo do Streamlit
    initial_sidebar_state="collapsed",
    page_icon="💸"
)

# ==========================================
# CUSTOM CSS (Mobile First)
# ==========================================
st.markdown("""
    <style>
    /* Abas maiores e mais fáceis para tocar */
    .stTabs [data-baseweb="tab-list"] { gap: 0.5rem; justify-content: space-between; }
    .stTabs [data-baseweb="tab"] { font-weight: 600; font-size: 1rem; padding-left: 0.5rem; padding-right: 0.5rem; }
    
    /* Métricas responsivas e texto de valor estilo App Banco */
    div[data-testid="stMetricValue"] { font-size: 1.8rem !important; }
    .valor-card { font-size: 1.6rem; font-weight: 700; margin: 0; padding-top: 0.2rem; padding-bottom: 0.5rem; }
    .valor-pendente { color: #FF7F0E; }
    .valor-pago { color: #2CA02C; }
    
    /* Ajuste para evitar o notch/home indicator no iOS */
    .block-container { padding-bottom: 5rem; padding-top: 2rem; }
    </style>
""", unsafe_allow_html=True)

# ==========================================
# CAMADA DE BANCO DE DADOS
# ==========================================
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
        st.toast(f"Valor inválido: '{valor}'. Salvo como R$ 0,00.", icon="⚠️")
        valor_total = 0.0
    
    parcelas = max(1, parcelas)
    valor_parcela = round(valor_total / parcelas, 2)
    data_inicial = datetime.strptime(data_doc, "%d/%m/%Y")
    
    with engine.connect() as conn:
        for i in range(parcelas):
            parcela_num = i + 1
            desc_parcela = f"Parcela {parcela_num}/{parcelas} - {desc}" if parcelas > 1 else desc
            data_parcela = (data_inicial + relativedelta(months=i)).strftime("%d/%m/%Y")
            
            conn.execute(text("""
                INSERT INTO "Lançamentos" (data, valor, descricao, categoria, pago, quem_pagou)
                VALUES (:data, :valor, :descricao, :categoria, :pago, :quem_pagou)
            """), {
                "data": data_parcela, 
                "valor": valor_parcela, 
                "descricao": desc_parcela,
                "categoria": cat, 
                "pago": pago if parcela_num == 1 else False,
                "quem_pagou": quem_pagou.strip() if quem_pagou else None
            })
        conn.commit()

def acoes_db(id_reg, acao):
    engine = get_engine()
    with engine.connect() as conn:
        if acao == "pagar":
            parcela_atual = conn.execute(text('SELECT descricao, data FROM "Lançamentos" WHERE id = :id'), {"id": id_reg}).fetchone()
            if not parcela_atual: return False, "Lançamento não encontrado."

            desc_completa, data_atual = parcela_atual
            desc_base = desc_completa.split(" - ", 1)[1] if " - " in desc_completa else desc_completa

            anteriores_pendentes = conn.execute(text("""
                SELECT COUNT(*) FROM "Lançamentos"
                WHERE descricao LIKE '%' || :desc_base || '%' AND pago = FALSE AND data < :data_atual
            """), {"desc_base": desc_base, "data_atual": data_atual}).fetchone()[0]

            if anteriores_pendentes > 0:
                return False, "Você deve pagar primeiro a(s) parcela(s) anterior(es) desta compra!"

            conn.execute(text('UPDATE "Lançamentos" SET pago = TRUE WHERE id = :id'), {"id": id_reg})
        
        elif acao == "excluir":
            conn.execute(text('DELETE FROM "Lançamentos" WHERE id = :id'), {"id": id_reg})
        conn.commit()
    return True, "Ação realizada com sucesso."

# ==========================================
# MODAIS NATIVOS
# ==========================================
@st.dialog("Confirmar Pagamento")
def modal_pagamento(lancamento_id, descricao):
    st.write(f"**{descricao}**")
    st.info("Apenas esta parcela será marcada como paga.")
    
    if st.button("✅ Confirmar Pagamento", type="primary", use_container_width=True):
        sucesso, msg = acoes_db(lancamento_id, "pagar")
        if sucesso:
            st.session_state['refresh'] = True
            st.rerun()
        else:
            st.error(msg)

@st.dialog("Excluir Lançamento")
def modal_exclusao(lancamento_id):
    st.warning("Excluir este lançamento permanentemente?")
    if st.button("🗑️ Sim, excluir", type="primary", use_container_width=True):
        acoes_db(lancamento_id, "excluir")
        st.session_state['refresh'] = True
        st.rerun()

# ==========================================
# INICIALIZAÇÃO DE ESTADO
# ==========================================
init_db()
if 'dados_temp' not in st.session_state:
    st.session_state['dados_temp'] = {'data': datetime.now().strftime("%d/%m/%Y"), 'valor': '0,00', 'desc': '', 'cat': 'Outros', 'quem_pagou': '', 'parcelado': False, 'parcelas': 1}

# ==========================================
# UI PRINCIPAL
# ==========================================
st.markdown("### 💸 Gestão Família")

t_dash, t_contas, t_cartao, t_ocr = st.tabs(["📊 Painel", "🧾 Fixo", "💳 Cartão", "📷 Scan"])

# --- TAB 1: DASHBOARD (Principal no Mobile) ---
with t_dash:
    df = pd.read_sql('SELECT * FROM "Lançamentos" ORDER BY data_registro DESC', get_engine().connect())

    if not df.empty:
        df['dt'] = pd.to_datetime(df['data'], dayfirst=True, errors='coerce')
        
        total_pendente = df[df['pago'] == False]['valor'].sum()
        total_pago = df[df['pago'] == True]['valor'].sum()
        
        m1, m2 = st.columns(2)
        m1.metric("Pendente", f"R$ {total_pendente:,.2f}")
        m2.metric("Pago", f"R$ {total_pago:,.2f}")

        st.divider()

        # SOTA Mobile: Gráficos em Sub-abas para evitar rolagem longa
        tab_g1, tab_g2, tab_g3 = st.tabs(["👤 Divisão", "📈 Mensal", "🍕 Categoria"])
        
        with tab_g1:
            df['quem_pagou'] = df['quem_pagou'].fillna("").astype(str).str.strip()
            df_pessoas = df[(df['pago'] == True) & (df['quem_pagou'] != "")]
            if not df_pessoas.empty:
                soma_pessoas = df_pessoas.groupby('quem_pagou')['valor'].sum().reset_index().sort_values('valor', ascending=True)
                fig_pessoas = px.bar(soma_pessoas, x='valor', y='quem_pagou', text='valor', color='quem_pagou', color_discrete_sequence=px.colors.qualitative.Set2, orientation='h')
                fig_pessoas.update_traces(texttemplate='R$ %{text:,.2f}', textposition='inside')
                fig_pessoas.update_layout(plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)", margin=dict(l=0, r=0, t=20, b=0), xaxis_title="", yaxis_title="", showlegend=False, xaxis=dict(showticklabels=False))
                st.plotly_chart(fig_pessoas, use_container_width=True)
            else:
                st.info("Nenhum pagamento registrado.")

        with tab_g2:
            df['mes'] = df['dt'].dt.strftime('%m/%Y')
            evol = df.groupby('mes')['valor'].sum().reset_index()
            fig_bar = px.bar(evol, x='mes', y='valor', text_auto='.2s', color_discrete_sequence=['#4F8BF9'])
            fig_bar.update_layout(plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)", margin=dict(l=0, r=0, t=20, b=0), xaxis_title="", yaxis_title="")
            st.plotly_chart(fig_bar, use_container_width=True)

        with tab_g3:
            setor = df.groupby('categoria')['valor'].sum().reset_index()
            fig_pie = px.pie(setor, values='valor', names='categoria', hole=0.5, color_discrete_sequence=px.colors.qualitative.Pastel)
            fig_pie.update_layout(plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)", margin=dict(l=0, r=0, t=20, b=0), showlegend=False)
            fig_pie.update_traces(textposition='inside', textinfo='percent+label')
            st.plotly_chart(fig_pie, use_container_width=True)

        st.divider()
        
        # Filtros e Lista
        f_col1, f_col2, f_col3 = st.columns(3)
        filtro_status = st.radio("Filtro:", ["Pendentes", "Pagos", "Todos"], horizontal=True, label_visibility="collapsed")
        
        df_view = df.sort_values('dt', ascending=True)
        if filtro_status == "Pendentes": df_view = df_view[df_view['pago'] == False]
        elif filtro_status == "Pagos": df_view = df_view[df_view['pago'] == True]

        for _, row in df_view.iterrows():
            with st.container(border=True):
                # SOTA Mobile: Card Vertical Redesenhado
                status_icon = "✅" if row['pago'] else "⏳"
                tag_responsavel = f"| 👤 {row['quem_pagou']}" if row['quem_pagou'] != "" else ""
                classe_cor = "valor-pago" if row['pago'] else "valor-pendente"
                
                # Cabeçalho do Card
                st.caption(f"{status_icon} {row['data']} | 🏷️ {row['categoria']} {tag_responsavel}")
                st.markdown(f"**{row['descricao']}**")
                
                # Valor Destaque
                st.markdown(f"<p class='valor-card {classe_cor}'>R$ {row['valor']:,.2f}</p>", unsafe_allow_html=True)
                
                # Ações na Base
                if not row['pago']:
                    btn_c1, btn_c2 = st.columns(2)
                    with btn_c1:
                        if st.button("✅ Pagar", key=f"pay_{row['id']}", use_container_width=True):
                            modal_pagamento(row['id'], row['descricao'])
                    with btn_c2:
                        if st.button("🗑️ Excluir", key=f"del_{row['id']}", use_container_width=True):
                            modal_exclusao(row['id'])
                else:
                    if st.button("🗑️ Excluir", key=f"del_{row['id']}", use_container_width=True):
                        modal_exclusao(row['id'])
    else:
        st.info("Nenhum lançamento no banco. Use as abas ao lado para adicionar.", icon="ℹ️")

# --- TAB 2: CONTAS À VISTA ---
with t_contas:
    with st.container(border=True):
        with st.form("form_contas", clear_on_submit=True):
            f_desc = st.text_input("Descrição", value=st.session_state['dados_temp'].get('desc', ''))
            
            c1, c2 = st.columns(2)
            lista_cats = ["Moradia", "Contas", "Transporte", "Educação", "Saúde", "Alimentação", "Outros"]
            cat_atual = st.session_state['dados_temp'].get('cat', 'Outros')
            f_cat = c1.selectbox("Categoria", lista_cats, index=lista_cats.index(cat_atual) if cat_atual in lista_cats else 6)
            f_data = c2.text_input("Vencimento", value=st.session_state['dados_temp'].get('data'))
            
            c3, c4 = st.columns(2)
            f_valor = c3.text_input("Valor R$", value=st.session_state['dados_temp'].get('valor'))
            f_quem_pagou = c4.text_input("Responsável?", value=st.session_state['dados_temp'].get('quem_pagou', ''))
            
            f_pago = st.checkbox("Já paguei")

            if st.form_submit_button("✅ Salvar Conta", type="primary", use_container_width=True):
                if not f_valor.strip(): st.error("Preencha o valor!")
                else:
                    salvar_no_db(f_data, f_valor, f_desc, f_cat, f_pago, f_quem_pagou)
                    st.toast("Conta salva!", icon="🎉")

# --- TAB 3: CARTÃO / PARCELAS ---
with t_cartao:
    with st.container(border=True):
        with st.form("form_cartao", clear_on_submit=True):
            f_desc_c = st.text_input("Descrição da Compra", value=st.session_state['dados_temp'].get('desc', ''))
            
            c1, c2 = st.columns(2)
            f_data_c = c1.text_input("Data 1ª Parcela", value=st.session_state['dados_temp'].get('data'))
            f_valor_c = c2.text_input("Valor TOTAL R$", value=st.session_state['dados_temp'].get('valor'))
            
            c3, c4 = st.columns(2)
            f_parcelas_c = c3.number_input("Parcelas", min_value=2, max_value=36, value=10, step=1)
            lista_cats_c = ["Saúde", "Educação", "Moradia", "Alimentação", "Transporte", "Investimento", "Outros"]
            f_cat_c = c4.selectbox("Categoria ", lista_cats_c, index=6)

            f_quem_pagou_c = st.text_input("Responsável pela compra?", value=st.session_state['dados_temp'].get('quem_pagou', ''))
            f_pago_c = st.checkbox("1ª parcela já paga")

            if st.form_submit_button("✅ Salvar Compra", type="primary", use_container_width=True):
                if not f_valor_c.strip(): st.error("Preencha o valor total!")
                else:
                    salvar_no_db(f_data_c, f_valor_c, f_desc_c, f_cat_c, f_pago_c, f_quem_pagou_c, f_parcelas_c)
                    st.toast("Compra parcelada salva!", icon="💳")

# --- TAB 4: OCR ---
with t_ocr:
    st.info("No celular, você pode tirar uma foto do boleto na hora.")
    uploaded_file = st.file_uploader("Câmera / Galeria", type=["png", "jpg", "jpeg", "pdf"], label_visibility="collapsed")

    if uploaded_file:
        if st.button("🔍 Extrair Dados", type="primary", use_container_width=True):
            with st.status("Lendo documento...", expanded=True) as status:
                try:
                    if uploaded_file.type == "application/pdf":
                        images = convert_from_bytes(uploaded_file.read(), first_page=1, last_page=1, dpi=200)
                        img = images[0]
                    else:
                        img = Image.open(uploaded_file)
                    
                    txt = pytesseract.image_to_string(img, lang='por', config='--psm 6').lower()
                    
                    desc, cat = "Outros", "Outros"
                    if any(x in txt for x in ['condominio', 'condomínio']): desc, cat = "Condomínio", "Moradia"
                    elif any(x in txt for x in ['ceee', 'equatorial', 'energia', 'luz']): desc, cat = "Energia", "Moradia"

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
                        'desc': desc, 'cat': cat, 'quem_pagou': "", 'parcelado': False, 'parcelas': 1
                    }
                    status.update(label="Extraído! Vá em Fixo/Cartão.", state="complete", expanded=False)
                except Exception as e:
                    st.error(f"Erro: {str(e)}")
