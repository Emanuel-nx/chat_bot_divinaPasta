import fitz  # PyMuPDF
import re

def ler_cardapio_pdf(caminho_pdf):
    try:
        doc = fitz.open(caminho_pdf)
        texto = ""
        for pagina in doc:
            texto += pagina.get_text()
        doc.close()

        texto = texto.strip()

        # Separar história e cardápio
        if "Cardápio" in texto:
            partes = texto.split("Cardápio", maxsplit=1)
            historia = partes[0].strip()
            cardapio_raw = partes[1].strip()
        else:
            historia = texto
            cardapio_raw = ""

        # Limpa e formata o cardápio
        linhas_cardapio = cardapio_raw.splitlines()
        itens = []
        for linha in linhas_cardapio:
            linha = linha.strip()
            if linha and "R$" in linha:
                itens.append(f"- {linha}")

        cardapio_formatado = "\n".join(itens)
        return historia, cardapio_formatado

    except Exception as e:
        return f"Erro ao ler PDF: {e}", ""
