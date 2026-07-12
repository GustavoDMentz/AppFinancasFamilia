<div align="center">

# 💸 Terminal Financeiro Familiar

### Controle de gastos compartilhado com OCR e análise mensal

[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![Streamlit](https://img.shields.io/badge/Streamlit-App-FF4B4B?style=flat-square&logo=streamlit&logoColor=white)](https://streamlit.io)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-SQL-4169E1?style=flat-square&logo=postgresql&logoColor=white)](https://postgresql.org)
[![Plotly](https://img.shields.io/badge/Plotly-Gráficos-3F4F75?style=flat-square&logo=plotly&logoColor=white)](https://plotly.com)
[![Status](https://img.shields.io/badge/Status-Protótipo-orange?style=flat-square)]()

</div>

> Protótipo de app financeiro para **uso em família ou compartilhado**, construído com Streamlit e Python. Registra lançamentos manualmente ou via **OCR de comprovantes** (imagem/PDF), armazena em **PostgreSQL**, e exibe dashboards mensais com divisão de gastos por pessoa, evolução temporal e distribuição por categoria.

> [!NOTE]
> **Contexto:** Este projeto foi o protótipo inicial que originou o [Planejaí](https://github.com/GustavoDMentz/Planejai-atualizado). As stacks são intencionalmente diferentes — aqui o foco é **backend real com SQL e OCR**; no Planejaí o foco é **PWA mobile com voz e IA**.

---

## ✨ Funcionalidades

### 📄 Lançamento Manual com Parcelamento
- Formulário completo: data, valor, descrição, categoria, status (pago/pendente) e responsável
- **Parcelamento automático**: divida qualquer lançamento em N parcelas mensais — cada parcela é inserida como registro separado com data calculada automaticamente

### 🔍 OCR de Comprovantes (Tesseract + pdf2image)
- Faça upload de uma **imagem** (JPG/PNG) ou **PDF** de comprovante
- O Tesseract extrai o texto automaticamente e pré-preenche valor e descrição
- Formulário de confirmação para revisar e salvar — sem redigitar nada

### 📊 Dashboard Mensal com 3 Visões

| Aba | Conteúdo |
|-----|----------|
| **👤 Divisão** | Gráfico de barras horizontais com total pago por cada membro da família |
| **📈 Evolução** | Gráfico de barras empilhadas por categoria ao longo dos meses |
| **🍕 Categoria** | Gráfico de rosca com distribuição percentual de gastos do mês |

- Filtro de mês por selectbox
- Métricas de **total pendente** e **total pago** no topo
- Lista completa dos lançamentos do mês com filtro Pendentes / Pagos / Todos

### ✅ Gestão de Status
- Marcar lançamentos como **Pagos** (com registro de quem pagou)
- **Editar** qualquer campo de um lançamento existente
- **Excluir** lançamentos com confirmação via modal

---

## 🏗️ Stack Técnica

| Camada | Tecnologia |
|--------|-----------|
| Interface | Streamlit (mobile-first com CSS customizado) |
| Linguagem | Python 3.10+ |
| Banco de dados | PostgreSQL via SQLAlchemy |
| OCR | Tesseract (`pytesseract`) + `pdf2image` |
| Gráficos | Plotly Express |
| Data | Pandas + NumPy |

---

## 🚀 Como rodar localmente

### Pré-requisitos

```bash
# Tesseract OCR (necessário para leitura de comprovantes)
sudo apt install tesseract-ocr tesseract-ocr-por  # Ubuntu/Debian
brew install tesseract                              # Mac

# Poppler (necessário para pdf2image)
sudo apt install poppler-utils  # Ubuntu/Debian
brew install poppler            # Mac
```

### Instalação

```bash
git clone https://github.com/GustavoDMentz/AppFinancasFamilia.git
cd AppFinancasFamilia

pip install -r requirements.txt
```

### Configure a conexão com o banco

Crie o arquivo `.streamlit/secrets.toml`:

```toml
[connections.financeiro]
url = "postgresql://usuario:senha@host:5432/nome_do_banco"
```

> 💡 Compatible com [Supabase](https://supabase.com) (gratuito) — basta copiar a connection string da aba *Database Settings*.

### Execute

```bash
streamlit run App.py
```

Acesse em: **http://localhost:8501**

---

## 📂 Estrutura

```
AppFinancasFamilia/
├── App.py              # App Streamlit completo (UI + lógica + DB)
├── requirements.txt    # Dependências Python
├── packages.txt        # Dependências de sistema (Tesseract/Poppler para deploy)
└── .gitignore
```

---

## ☁️ Deploy no Streamlit Cloud

O arquivo `packages.txt` já está configurado para instalar as dependências de sistema (Tesseract, Poppler) automaticamente no Streamlit Cloud:

1. Faça fork/push para o GitHub
2. Acesse [share.streamlit.io](https://share.streamlit.io) e conecte o repositório
3. Adicione a `secrets.toml` nas configurações do app (aba *Secrets*)
4. Deploy automático ✅

---

## 🔄 Diferenças em relação ao Planejaí

| | AppFinancasFamilia | Planejaí |
|--|--|--|
| Stack | Python + Streamlit | React + TypeScript |
| Banco | PostgreSQL (remoto) | IndexedDB (local/offline) |
| OCR de comprovantes | ✅ Tesseract | ❌ |
| Registro por voz | ❌ | ✅ Google Gemini |
| Multiusuário / família | ✅ Campo `quem_pagou` | ❌ |
| Deploy | Streamlit Cloud | Vite PWA |

---

## 📄 Licença

MIT — uso livre para fins pessoais e educacionais.
