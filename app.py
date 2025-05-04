import warnings
warnings.filterwarnings("ignore", category=UserWarning, module="fuzzywuzzy")
from flask import Flask, render_template, request, jsonify, session,redirect, url_for
from flask_session import Session
import os
from dotenv import load_dotenv
from datetime import datetime
import logging
from urllib.parse import quote_plus
from langchain_groq import ChatGroq
from langchain_core.chat_history import InMemoryChatMessageHistory
from langchain_core.runnables.history import RunnableWithMessageHistory
from langchain_core.prompts import ChatPromptTemplate
from langchain.prompts import PromptTemplate
from langchain_core.runnables import RunnableLambda
from ler_pdf import ler_cardapio_pdf
from unidecode import unidecode
from fuzzywuzzy import fuzz
import re

# Load environment variables
load_dotenv()

logging.basicConfig(
    filename="chatbot.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

app = Flask(__name__, template_folder="templates")
app.config["SECRET_KEY"] = os.getenv("FLASK_SECRET_KEY", "segredo-seguro")
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

# Initialize Groq
groq = ChatGroq(api_key=os.getenv("GROQ_API_KEY"), model="llama3-70b-8192")

# Load PDF data
CARDAPIO_TEXT, HISTORY_TEXT = ler_cardapio_pdf("cardapio.pdf")

# WhatsApp number
WHATSAPP_NUMBER = os.getenv("WHATSAPP_NUMBER", "86999474682")

# Prompt
GENERAL_PROMPT = PromptTemplate(
    input_variables=["cardapio", "pergunta", "historia"],
    template="""
Você é o atendente virtual da Divina Pasta. Sempre responda em HTML organizado e bonito para chat, usando:
- Títulos curtos com <strong> e emojis;
- Listas claras com marcadores (•);
- Destaque nomes de produtos e preços;
- Blocos separados com <br> simples;
- Valor total do pedido.

⚠ Importante:
- NÃO invente prazos de entrega.
- Sempre oriente que o fechamento final será resolvido diretamente no WhatsApp, fornecendo o link com os itens escolhidos.

CARDÁPIO:
{cardapio}

HISTÓRIA:
{historia}

CLIENTE:
{pergunta}

RESPOSTA:
"""
)

def limpar_texto(texto):
    texto = re.sub(r'R\$ ?\d+(?:[.,]\d{2})?', '', texto)
    texto = re.sub(r'[^\w\s]', '', texto)
    return unidecode(texto.lower()).strip()

def gerar_whatsapp_link(pedido):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    itens_formatados = ', '.join(pedido['itens']) if pedido['itens'] else 'Nenhum item selecionado'
    texto = f"Novo pedido Divina Pasta%0ADate: {timestamp}%0AItens: {itens_formatados}"
    link = f"https://wa.me/{WHATSAPP_NUMBER}?text={quote_plus(texto)}"
    return link

def build_runnable():
    prompt = ChatPromptTemplate.from_template(GENERAL_PROMPT.template)
    def mapping(x):
        mensagem = x[-1].content if isinstance(x, list) and hasattr(x[-1], 'content') else str(x)
        return {
            "cardapio": CARDAPIO_TEXT,
            "historia": HISTORY_TEXT,
            "pergunta": mensagem
        }
    return RunnableLambda(mapping) | prompt | groq

def initialize_conversation(cliente_id):
    chat_history = InMemoryChatMessageHistory()
    session[f"chain_{cliente_id}"] = chat_history
    session[f"pedido_{cliente_id}"] = {"itens": []}
    return RunnableWithMessageHistory(
        runnable=build_runnable(),
        get_session_history=lambda: chat_history
    )

def get_conversation(cliente_id):
    if f"chain_{cliente_id}" not in session:
        return initialize_conversation(cliente_id)
    chat_history = session[f"chain_{cliente_id}"]
    return RunnableWithMessageHistory(
        runnable=build_runnable(),
        get_session_history=lambda: chat_history
    )

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/perguntar", methods=["POST"])
def perguntar():
    data = request.get_json()
    pergunta = data.get("pergunta", "").strip()
    if not pergunta:
        return jsonify({"resposta": "Por favor, envie uma pergunta válida.", "status": "error"}), 400

    cliente_id = request.remote_addr
    pedido = session.get(f"pedido_{cliente_id}", {"itens": []})
    conversation = get_conversation(cliente_id)

    # Checar palavras-chave para dúvidas
    if any(palavra in pergunta.lower() for palavra in ["duvida", "dúvida", "ajuda", "atendente", "falar"]):
        link = f"https://wa.me/{WHATSAPP_NUMBER}"
        resposta = f"📲 <strong>Para dúvidas ou atendimento humano, fale conosco diretamente no WhatsApp:</strong><br><a href='{link}' target='_blank'>💬 Abrir WhatsApp</a>"
        return jsonify({"resposta": resposta, "status": "success"})

    try:
        result = conversation.invoke({"input": pergunta})
        resposta = result.content.strip() if hasattr(result, 'content') else str(result)
        resposta = resposta.replace('\n', '<br>')

    except Exception as e:
        logging.error(f"Erro ao chamar IA: {e}")
        return jsonify({"resposta": "Erro ao consultar o assistente. Tente novamente.", "status": "error"}), 500

    # Fuzzy match direto
    pergunta_limpa = limpar_texto(pergunta)
    best_match = None
    best_score = 0
    cardapio_items = [line.strip() for line in CARDAPIO_TEXT.split("\n") if line.strip()]
    for item in cardapio_items:
        item_limpo = limpar_texto(item)
        score = fuzz.partial_ratio(pergunta_limpa, item_limpo)
        if score > 80 and score > best_score:
            best_match = item
            best_score = score

    if best_match:
        pedido["itens"].append(best_match)
        session[f"pedido_{cliente_id}"] = pedido
        link = gerar_whatsapp_link(pedido)
        itens_list = ''.join([f"• <strong>{item}</strong><br>" for item in pedido['itens']])
        resposta = f"✅ <strong>Pedido anotado!</strong><br>{itens_list}<br><br>Finalize pagamento e combine entrega diretamente no WhatsApp:<br><a href='{link}' target='_blank'>💬 Abrir WhatsApp</a>"

    return jsonify({"resposta": resposta, "status": "success"})

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
