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
# CONFIGURAÇÃO DA PÁGINA (Deve ser a 1ª linha)
# ==========================================
st.set_page_config(
    page_title="Terminal Financeiro",
    layout="wide",
    initial_sidebar_state="collapsed",
    page_icon="💸"
)

# ==========================================
# CUSTOM CSS (Design System Minimalista)
# ==========================================
st.markdown("""
    <style>
    /* Ajustes refinados de UI */
    .stTabs [data-baseweb="tab-list"] { gap: 1rem; }
    .stTabs [data-baseweb="tab"] { font-weight: 600; font-size: 1.05rem; }
    div[data-testid="stMetricValue"] { font-size: 2rem !important; }
    </style>
""", unsafe_allow_html=True)

# ==========================================
# CAMADA DE BANCO DE DADOS (Preservada)
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
                "data": data_parcela, "valor": valor_parcela, "descricao": desc_parcela,
                "categoria": cat, "pago": pago if parcela_num == 1 else False,
                "quem_pagou": quem_pagou if parcela_num == 1 else None
            })
        conn.commit()

def acoes_db(id_reg, acao, quem_pagou=None):
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
                return False, "Você deve pagar primeiro as parcelas anteriores pendentes!"

            conn.execute(text("""
                UPDATE "Lançamentos" SET pago = TRUE, quem_pagou = :quem
                WHERE descricao LIKE '%' || :desc_base || '%' AND pago = FALSE
            """), {"quem": quem_pagou.strip() if quem_pagou else None, "desc_base": desc_base})
        
        elif acao == "excluir":
            conn.execute(text('DELETE FROM "Lançamentos" WHERE id = :id'), {"id": id_reg})
        conn.commit()
    return True, "Ação realizada com sucesso."

# ==========================================
# MODAIS NATIVOS (SOTA para ações em listas)
# ==========================================
@st.dialog("Confirmar Pagamento")
def modal_pagamento(lancamento_id, descricao):
    st.write(f"Você está pagando: **{descricao}**")
    st.info("Caso seja uma compra parcelada, isso quitará TODAS as parcelas restantes desta compra.")
    quem_pagou = st.text_input("Quem realizou o pagamento?")
    
    if st.button("Confirmar Pagamento", type="primary", use_container_width=True):
        sucesso, msg = acoes_db(lancamento_id, "pagar", quem_pagou)
        if sucesso:
            st.session_state['refresh'] = True
            st.rerun()
        else:
            st.error(msg)

@st.dialog("Excluir Lançamento")
def modal_exclusao(lancamento_id):
    st.warning("Tem certeza que deseja excluir este lançamento? Esta ação não pode ser desfeita.")
    if st.button("Sim, excluir", type="primary", use_container_width=True):
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
st.title("💸 Gestão Financeira Inteligente")
st.markdown("Bem-vindo ao seu terminal financeiro. Escaneie boletos ou insira dados manualmente.")

t_ocr, t_contas, t_cartao, t_dash = st.tabs(["📷 Scanner OCR", "🧾 Contas à Vista", "💳 Cartão (Parcelas)", "📊 Dashboard"])

# --- TAB 1: OCR ---
with t_ocr:
    st.markdown("#### Scanner Inteligente de Boletos")
    uploaded_file = st.file_uploader("Envie o boleto (PDF ou imagem)", type=["png", "jpg", "jpeg", "pdf"], label_visibility="collapsed")

    if uploaded_file:
        col_img, col_acao = st.columns([1, 1])
        try:
            with col_img:
                if uploaded_file.type == "application/pdf":
                    images = convert_from_bytes(uploaded_file.read(), first_page=1, last_page=1, dpi=200)
                    img = images[0]
                else:
                    img = Image.open(uploaded_file)
                st.image(img, use_column_width=True, caption="Documento Original")

            with col_acao:
                if st.button("🔍 Extrair Dados", type="primary", use_container_width=True):
                    with st.status("Analisando documento...", expanded=True) as status:
                        st.write("Executando OCR...")
                        txt = pytesseract.image_to_string(img, lang='por', config='--psm 6').lower()
                        
                        st.write("Classificando categoria...")
                        desc, cat = "Outros", "Outros"
                        if any(x in txt for x in ['condominio', 'condomínio']): desc, cat = "Condomínio", "Moradia"
                        elif any(x in txt for x in ['ceee', 'equatorial', 'energia', 'luz']): desc, cat = "Energia (CEEE)", "Moradia"

                        st.write("Extraindo valores e datas...")
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
                        status.update(label="Extração Concluída!", state="complete", expanded=False)
                    st.success("Dados preenchidos nas abas de formulário!")
        except Exception as e:
            st.error(f"Erro ao processar: {str(e)}")

# --- TAB 2: CONTAS À VISTA ---
with t_contas:
    st.markdown("#### Nova Conta Fixa / Consumo")
    with st.container(border=True):
        with st.form("form_contas", clear_on_submit=True):
            f_desc = st.text_input("Descrição", value=st.session_state['dados_temp'].get('desc', ''))
            lista_cats = ["Moradia", "Contas", "Transporte", "Educação", "Saúde", "Alimentação", "Outros"]
            
            # Tratamento de fallback seguro para o selectbox
            cat_atual = st.session_state['dados_temp'].get('cat', 'Outros')
            idx_cat = lista_cats.index(cat_atual) if cat_atual in lista_cats else lista_cats.index("Outros")
            f_cat = st.selectbox("Categoria", lista_cats, index=idx_cat)

            c1, c2 = st.columns(2)
            f_data = c1.text_input("Vencimento (dd/mm/aaaa)", value=st.session_state['dados_temp'].get('data'))
            f_valor = c2.text_input("Valor R$", value=st.session_state['dados_temp'].get('valor'))

            c3, c4 = st.columns(2)
            f_pago = c3.checkbox("Já paguei")
            f_quem_pagou = c4.text_input("Quem pagou?", value=st.session_state['dados_temp'].get('quem_pagou', ''))

            if st.form_submit_button("✅ Salvar Conta", type="primary", use_container_width=True):
                if not f_valor.strip():
                    st.error("Preencha o valor!")
                else:
                    salvar_no_db(f_data, f_valor, f_desc, f_cat, f_pago, f_quem_pagou)
                    st.toast("Conta salva com sucesso!", icon="🎉")

# --- TAB 3: CARTÃO / PARCELAS ---
with t_cartao:
    st.markdown("#### Nova Compra Parcelada")
    with st.container(border=True):
        with st.form("form_cartao", clear_on_submit=True):
            f_desc_c = st.text_input("Descrição", value=st.session_state['dados_temp'].get('desc', ''))
            lista_cats_c = ["Saúde", "Educação", "Moradia", "Alimentação", "Transporte", "Investimento", "Outros"]
            
            cat_atual_c = st.session_state['dados_temp'].get('cat', 'Outros')
            idx_cat_c = lista_cats_c.index(cat_atual_c) if cat_atual_c in lista_cats_c else lista_cats_c.index("Outros")
            f_cat_c = st.selectbox("Categoria", lista_cats_c, index=idx_cat_c)

            c1, c2, c3 = st.columns([2, 2, 1])
            f_data_c = c1.text_input("Data da 1ª Parcela", value=st.session_state['dados_temp'].get('data'))
            f_valor_c = c2.text_input("Valor TOTAL da Compra R$", value=st.session_state['dados_temp'].get('valor'))
            f_parcelas_c = c3.number_input("Qtd Parcelas", min_value=2, max_value=36, value=10, step=1)

            c4, c5 = st.columns(2)
            f_pago_c = c4.checkbox("1ª parcela já veio e foi paga")
            f_quem_pagou_c = c5.text_input("Quem pagou/pagará?", value=st.session_state['dados_temp'].get('quem_pagou', ''))

            if st.form_submit_button("✅ Salvar Compra Parcelada", type="primary", use_container_width=True):
                if not f_valor_c.strip():
                    st.error("Preencha o valor total!")
                else:
                    salvar_no_db(f_data_c, f_valor_c, f_desc_c, f_cat_c, f_pago_c, f_quem_pagou_c, f_parcelas_c)
                    st.toast(f"{f_parcelas_c} parcelas registradas!", icon="💳")

# --- TAB 4: DASHBOARD ---
with t_dash:
    df = pd.read_sql('SELECT * FROM "Lançamentos" ORDER BY data_registro DESC', get_engine().connect())

    if not df.empty:
        df['dt'] = pd.to_datetime(df['data'], dayfirst=True, errors='coerce')
        
        # SOTA: Métricas superiores
        m1, m2, m3 = st.columns(3)
        total_pendente = df[df['pago'] == False]['valor'].sum()
        total_pago = df[df['pago'] == True]['valor'].sum()
        qtd_pendentes = len(df[df['pago'] == False])
        
        m1.metric("Total Pendente", f"R$ {total_pendente:,.2f}")
        m2.metric("Total Pago", f"R$ {total_pago:,.2f}")
        m3.metric("Contas a Pagar", f"{qtd_pendentes} itens")

        st.divider()

        # SOTA: Gráficos Plotly Clean
        c1, c2 = st.columns([3, 2])
        with c1:
            st.markdown("##### 📈 Gastos por Mês")
            df['mes'] = df['dt'].dt.strftime('%m/%Y')
            evol = df.groupby('mes')['valor'].sum().reset_index()
            fig_bar = px.bar(evol, x='mes', y='valor', text_auto='.2s', color_discrete_sequence=['#4F8BF9'])
            fig_bar.update_layout(plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)", margin=dict(l=0, r=0, t=0, b=0), xaxis_title="", yaxis_title="")
            st.plotly_chart(fig_bar, use_container_width=True)

        with c2:
            st.markdown("##### 🍕 Divisão por Categoria")
            setor = df.groupby('categoria')['valor'].sum().reset_index()
            fig_pie = px.pie(setor, values='valor', names='categoria', hole=0.5, color_discrete_sequence=px.colors.qualitative.Pastel)
            fig_pie.update_layout(plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)", margin=dict(l=0, r=0, t=0, b=0))
            st.plotly_chart(fig_pie, use_container_width=True)

        st.divider()
        st.markdown("### 📋 Gestão de Lançamentos")
        
        # Filtros SOTA
        f_col1, f_col2 = st.columns([1, 4])
        filtro_status = f_col1.radio("Filtrar por:", ["Pendentes", "Pagos", "Todos"], horizontal=True, label_visibility="collapsed")
        
        df_view = df.sort_values('dt', ascending=True)
        if filtro_status == "Pendentes": df_view = df_view[df_view['pago'] == False]
        elif filtro_status == "Pagos": df_view = df_view[df_view['pago'] == True]

        # Renderização da lista usando st.container para UI limpa
        for _, row in df_view.iterrows():
            with st.container(border=True):
                col_info, col_valor, col_acoes = st.columns([5, 2, 2])
                
                status_icon = "✅" if row['pago'] else "⏳"
                status_color = "green" if row['pago'] else "orange"
                
                with col_info:
                    st.markdown(f"**{row['descricao']}**")
                    st.caption(f"{status_icon} :{status_color}[{row['data']}] | 🏷️ {row['categoria']} " + (f"| 👤 {row['quem_pagou']}" if row['pago'] else ""))
                
                with col_valor:
                    st.markdown(f"<h4 style='margin:0; padding-top:0.5rem;'>R$ {row['valor']:,.2f}</h4>", unsafe_allow_html=True)
                
                with col_acoes:
                    # Uso das Dialogs para evitar o bug de nested buttons
                    if not row['pago']:
                        if st.button("Pagar", key=f"pay_{row['id']}", use_container_width=True):
                            modal_pagamento(row['id'], row['descricao'])
                    if st.button("Excluir", key=f"del_{row['id']}", use_container_width=True):
                        modal_exclusao(row['id'])

    else:
        st.info("Nenhum lançamento no banco de dados. Cadastre sua primeira conta nas abas acima!", icon="ℹ️")
