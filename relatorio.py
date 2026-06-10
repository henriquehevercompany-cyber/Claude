import requests
import os
from datetime import date, timedelta

EVOLUTION_URL = os.environ["EVOLUTION_URL"]
INSTANCE      = os.environ["EVOLUTION_INSTANCE"]
TOKEN         = os.environ["EVOLUTION_TOKEN"]
NUMERO        = os.environ["WHATSAPP_NUMERO"]

NOTION_TOKEN  = os.environ["NOTION_TOKEN"]
NOTION_DB_ID  = os.environ["NOTION_DB_ID"]
SHEETS_ID     = os.environ["SHEETS_ID"]
ABAS          = ["Conta 1", "Conta 2", "Conta 3"]
CLIENTE       = "APVS"


def get_gasto_dia(data_str):
    total = 0.0
    for aba in ABAS:
        url = f"https://docs.google.com/spreadsheets/d/{SHEETS_ID}/gviz/tq?tqx=out:csv&sheet={aba.replace(' ', '%20')}"
        r = requests.get(url)
        for linha in r.text.strip().split("\n")[1:]:
            cols = linha.strip().split(",")
            if len(cols) >= 2:
                data_cel = cols[0].replace('"', '').strip()
                valor_cel = cols[1].replace('"', '').replace(',', '.').strip()
                if data_cel == data_str:
                    try:
                        total += float(valor_cel)
                    except:
                        pass
    return total


def get_notion_leads(data_str):
    url = f"https://api.notion.com/v1/databases/{NOTION_DB_ID}/query"
    headers = {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json"
    }
    payload = {
        "filter": {
            "and": [
                {"property": "Data de chegada", "created_time": {"equals": data_str}},
                {"property": "Status", "select": {"does_not_equal": "INDICAÇÃO"}},
                {"property": "Indicação?", "select": {"is_empty": True}}
            ]
        },
        "page_size": 100
    }
    total = 0
    while True:
        r = requests.post(url, headers=headers, json=payload).json()
        total += len(r.get("results", []))
        if not r.get("has_more"):
            break
        payload["start_cursor"] = r["next_cursor"]
    return total


def get_notion_vendas(data_str):
    url = f"https://api.notion.com/v1/databases/{NOTION_DB_ID}/query"
    headers = {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json"
    }
    payload = {
        "filter": {
            "and": [
                {"property": "FONTE", "select": {"equals": "Google ads"}},
                {"property": "Status", "select": {"equals": "VENDA CONCLUIDA"}},
                {"property": "Data da venda", "date": {"equals": data_str}}
            ]
        },
        "page_size": 100
    }
    total = 0
    while True:
        r = requests.post(url, headers=headers, json=payload).json()
        total += len(r.get("results", []))
        if not r.get("has_more"):
            break
        payload["start_cursor"] = r["next_cursor"]
    return total


def enviar_whatsapp(mensagem):
    r = requests.post(
        f"{EVOLUTION_URL}/message/sendText/{INSTANCE}",
        headers={"apikey": TOKEN},
        json={"number": NUMERO, "text": mensagem}
    )
    print(f"WhatsApp status: {r.status_code}")
    return r.status_code


def relatorio_diario():
    ontem = date.today() - timedelta(days=1)
    ontem_str = ontem.strftime("%Y-%m-%d")
    ontem_br  = ontem.strftime("%d/%m/%Y")

    gasto  = get_gasto_dia(ontem_str)
    leads  = get_notion_leads(ontem_str)
    vendas = get_notion_vendas(ontem_str)
    cpl    = round(gasto / leads, 2) if leads > 0 else 0.0

    mensagem = f"""🗓️ Relatório diário | {ontem_br}

{CLIENTE}
• 📥 Leads Gerados: {leads}
• ✅ Vendas Realizadas: {vendas}
• 💰 Custo por Lead (CPL): R$ {cpl:,.2f}
• 💰 Valor investido: R$ {gasto:,.2f}"""

    print(mensagem)
    enviar_whatsapp(mensagem)


def relatorio_semanal():
    hoje  = date.today()
    fim   = hoje - timedelta(days=1)
    inicio = hoje - timedelta(days=7)

    gasto_total  = 0.0
    leads_total  = 0
    vendas_total = 0

    d = inicio
    while d <= fim:
        d_str = d.strftime("%Y-%m-%d")
        gasto_total  += get_gasto_dia(d_str)
        leads_total  += get_notion_leads(d_str)
        vendas_total += get_notion_vendas(d_str)
        d += timedelta(days=1)

    cpl = round(gasto_total / leads_total, 2) if leads_total > 0 else 0.0
    inicio_br = inicio.strftime("%d/%m/%Y")
    fim_br    = fim.strftime("%d/%m/%Y")

    mensagem = f"""🗓️ Relatório semanal | {inicio_br} a {fim_br}

{CLIENTE}
• 📥 Leads Gerados: {leads_total}
• ✅ Vendas Realizadas: {vendas_total}
• 💰 Custo por Lead (CPL): R$ {cpl:,.2f}
• 💰 Valor investido: R$ {gasto_total:,.2f}"""

    print(mensagem)
    enviar_whatsapp(mensagem)


if __name__ == "__main__":
    import sys
    modo = sys.argv[1] if len(sys.argv) > 1 else "diario"
    if modo == "semanal":
        relatorio_semanal()
    else:
        relatorio_diario()
