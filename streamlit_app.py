import os
import streamlit as st
import anthropic
import ollama as ollama_client
from dotenv import load_dotenv
from data_loader import load_all_data

load_dotenv()

SYSTEM_PROMPT = """
És o Agente de Stock da Cabelte — assistente especializado na análise de stock de cabos eléctricos.
Respondes sempre em português europeu.

## Contexto da empresa
A Cabelte é um fabricante de cabos eléctricos. O stock é medido em toneladas (ton) e organizado
por artigo (referência de produto). As extrações são feitas semanalmente do sistema SGP/AS400.

## Fontes de dados disponíveis
1. **TbStock** (WXX_XXXX.xlsx) — snapshot semanal do stock físico (STK238F)
   - PESO_TOTAL (TON): stock físico total
   - PESO_DISP. (TON): stock livre (disponível para venda)
   - QTD_DISPONIVEL: metros disponíveis
   - QTD_ALOCADA / QTD_RESERVA / QTD_P_FACT: stock comprometido (invisível no BI anterior)
   - PESO TON/KM: densidade linear do cabo
   - ARTIGO: referência do produto
   - LIMITE: corte mínimo comercial
   - Alerta_Bobina: LP+LK = bobine grande

2. **Carteira de Encomendas** (Sxx_Carteira Encomendas_*.xlsx) — encomendas de clientes

3. **Lotes Quarentena** — lotes com problema de qualidade, fora do circuito normal

## Reconciliação do stock (referência Jun 2026)
- Stock Total:         ~4.377 ton
- Disponível:          ~1.681 ton
- Bloqueado ERP:       ~2.696 ton  (Total - Disponível)
- Carteira Clientes:   ~2.003 ton
- Gap STK vs Carteira:   ~693 ton  → OFs internas, reservas, pendentes facturação sem encomenda
- Quarentena:            ~172 ton  → fonte separada, fora do TbStock

## Conceitos
- **Cortes curtos**: lotes com disponível > 0, Alerta_Bobina ≠ "LP+LK", LIMITE > 0,
  e QTD_DISPONIVEL < LIMITE × 0.97
- **Stock parado**: lotes sem nenhuma encomenda de cliente associada
- **Stock Bom**: Disponível − Cortes Curtos − Stock Parado

## Como responder
- Tens acesso a TODA a série histórica de snapshots — podes responder sobre qualquer período disponível
- Para perguntas sobre a situação actual, usa o último snapshot
- Para perguntas sobre períodos passados (ex: "em Fevereiro", "em W08_2026"), usa a série histórica
- Para tendências, compara os valores ao longo do tempo
- Apresenta valores em toneladas com 2 casas decimais (ex: 1.681,45 ton)
- Se o período pedido não existir nos dados, diz quais os períodos disponíveis
- Quando o utilizador perguntar sobre um artigo específico, usa o detalhe do snapshot actual
- Sê directo e profissional — os utilizadores são da área de logística/planeamento
"""

DATA_INTRO = [
    {
        "role": "user",
        "content": "Carrega os dados actuais e confirma que estás pronto."
    },
    {
        "role": "assistant",
        "content": (
            "Dados carregados. Estou pronto para responder a perguntas sobre o stock, "
            "carteira de encomendas e lotes em quarentena. Como posso ajudar?"
        )
    }
]


def ask_agent(messages, data_context):
    provider = os.getenv("LLM_PROVIDER", "ollama").lower()
    system_with_data = SYSTEM_PROMPT + f"\n\n## DADOS ACTUAIS\n{data_context}"

    if provider == "anthropic":
        key = os.getenv("ANTHROPIC_API_KEY")
        if not key:
            st.error("ANTHROPIC_API_KEY não encontrada no ficheiro .env.")
            st.stop()
        client = anthropic.Anthropic(api_key=key)
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            system=system_with_data,
            messages=DATA_INTRO + messages,
        )
        return response.content[0].text

    else:  # ollama (default)
        model = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
        ollama_messages = [
            {"role": "system", "content": system_with_data},
            *DATA_INTRO,
            *messages,
        ]
        try:
            response = ollama_client.chat(model=model, messages=ollama_messages)
            return response.message.content
        except Exception as e:
            msg = str(e).lower()
            if any(x in msg for x in ["connect", "refused", "ollama"]):
                st.error("Ollama não está a correr. Abre o Ollama (menu Iniciar) e tenta novamente.")
                st.stop()
            raise


def main():
    st.set_page_config(
        page_title="Agente Stock — Cabelte",
        page_icon="📦",
        layout="wide"
    )

    # Carregar dados uma vez por sessão
    if "data" not in st.session_state:
        progress_bar = st.progress(0, text="A carregar ficheiros Excel...")

        def on_progress(pct, msg):
            progress_bar.progress(min(pct, 0.99), text=msg)

        st.session_state.data = load_all_data(progress_callback=on_progress)
        progress_bar.empty()

    data = st.session_state.data

    # ── Sidebar ──────────────────────────────────────────────────
    with st.sidebar:
        st.title("📦 Agente Stock")
        st.caption("Cabelte — Caracterização do Stock")
        st.divider()

        m = data["metrics"]
        if m:
            st.metric("Total", f"{m.get('total_ton', 0):,.1f} ton")
            st.metric("Disponível", f"{m.get('disponivel_ton', 0):,.1f} ton")
            st.metric("Bloqueado", f"{m.get('bloqueado_ton', 0):,.1f} ton")
            if "gap_ton" in m:
                delta_color = "inverse" if m["gap_ton"] > 0 else "normal"
                st.metric("Gap STK/Carteira", f"{m['gap_ton']:,.1f} ton", delta_color=delta_color)
            if "quarentena_ton" in m:
                st.metric("Quarentena", f"{m.get('quarentena_ton', 0):,.1f} ton")
        else:
            st.warning("Métricas não disponíveis")

        st.divider()
        st.caption(f"📄 Stock: {data['stock_file']}")
        st.caption(f"📄 Carteira: {data['carteira_file']}")

        if data.get("periodos_disponiveis"):
            with st.expander(f"📅 {len(data['periodos_disponiveis'])} períodos carregados"):
                for p in data["periodos_disponiveis"]:
                    st.caption(p)

        if data["errors"]:
            with st.expander("⚠️ Avisos"):
                for err in data["errors"]:
                    st.warning(err)

        if st.button("🔄 Actualizar dados", use_container_width=True):
            del st.session_state["data"]
            if "messages" in st.session_state:
                del st.session_state["messages"]
            st.rerun()

    # ── Chat principal ────────────────────────────────────────────
    st.title("Agente de Análise de Stock")

    if "messages" not in st.session_state:
        st.session_state.messages = []
        with st.chat_message("assistant"):
            st.write(
                "Olá! Sou o agente de análise de stock da Cabelte. "
                "Podes perguntar-me sobre stock disponível, lotes em quarentena, "
                "cortes curtos, reconciliação com a carteira de clientes, ou qualquer artigo específico."
            )

    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.write(msg["content"])

    if prompt := st.chat_input("Escreve a tua pergunta..."):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.write(prompt)

        with st.chat_message("assistant"):
            with st.spinner("A analisar..."):
                response = ask_agent(st.session_state.messages, data["context"])
            st.write(response)

        st.session_state.messages.append({"role": "assistant", "content": response})


if __name__ == "__main__":
    main()
