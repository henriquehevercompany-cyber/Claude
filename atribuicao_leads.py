import os
import sys
import requests
from datetime import datetime, timezone, timedelta

NOTION_TOKEN = os.environ["NOTION_TOKEN"]
NOTION_DB_ID_ORIGEM = os.environ["NOTION_DB_ID_ORIGEM"]      # Regional Pavuna (todos os leads)
NOTION_DB_ID_INTERNO = os.environ["NOTION_DB_ID_INTERNO"]     # Regional Pavuna Time Interno

# Leads criados antes deste corte nunca entram na contagem (evita mover retroativamente
# os ~10k leads que já existiam quando este fluxo foi criado).
CORTE_INICIO = "2026-07-13T15:07:00.000Z"

PROP_DATA_ORIGINAL = "Data de chegada original"
A_CADA = 5  # 1 a cada 5 leads (20%) vai para o time interno

BRASILIA = timezone(timedelta(hours=-3))
HORA_INICIO_COMERCIAL = 7   # inclusive
HORA_FIM_COMERCIAL = 18     # exclusive: leads chegados às 18:00 ou depois não contam


def dentro_horario_comercial(iso_ts):
    hora = datetime.fromisoformat(iso_ts.replace("Z", "+00:00")).astimezone(BRASILIA).hour
    return HORA_INICIO_COMERCIAL <= hora < HORA_FIM_COMERCIAL

HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json",
}

SKIP_PROPERTY_TYPES = {
    "files", "formula", "rollup", "created_time", "created_by",
    "last_edited_time", "last_edited_by", "unique_id",
}


def query_database(db_id, filter_=None):
    url = f"https://api.notion.com/v1/databases/{db_id}/query"
    payload = {"page_size": 100}
    if filter_:
        payload["filter"] = filter_
    resultados = []
    while True:
        r = requests.post(url, headers=HEADERS, json=payload)
        r.raise_for_status()
        data = r.json()
        resultados += data.get("results", [])
        if not data.get("has_more"):
            break
        payload["start_cursor"] = data["next_cursor"]
    return resultados


def get_ensure_data_original_property():
    """Garante que a propriedade auxiliar existe no board destino."""
    url = f"https://api.notion.com/v1/databases/{NOTION_DB_ID_INTERNO}"
    r = requests.get(url, headers=HEADERS)
    r.raise_for_status()
    props = r.json()["properties"]
    if PROP_DATA_ORIGINAL in props:
        return
    payload = {"properties": {PROP_DATA_ORIGINAL: {"date": {}}}}
    r = requests.patch(url, headers=HEADERS, json=payload)
    r.raise_for_status()
    print(f"Propriedade '{PROP_DATA_ORIGINAL}' criada no board destino.")


def sanitize_properties(properties):
    novo = {}
    for nome, valor in properties.items():
        tipo = valor.get("type")
        if tipo in SKIP_PROPERTY_TYPES:
            continue
        if tipo == "people":
            novo[nome] = {"people": [{"id": pessoa["id"]} for pessoa in valor["people"]]}
        else:
            novo[nome] = {tipo: valor[tipo]}
    return novo


def mover_lead(pagina, dry_run):
    props = sanitize_properties(pagina["properties"])
    props[PROP_DATA_ORIGINAL] = {"date": {"start": pagina["created_time"]}}
    nome = "".join(t["plain_text"] for t in pagina["properties"]["Name"]["title"]) or "(sem nome)"

    if dry_run:
        print(f"  [DRY-RUN] moveria lead '{nome}' (id={pagina['id']}, chegou em {pagina['created_time']})")
        return

    create_payload = {
        "parent": {"database_id": NOTION_DB_ID_INTERNO},
        "properties": props,
    }
    r = requests.post("https://api.notion.com/v1/pages", headers=HEADERS, json=create_payload)
    r.raise_for_status()

    r2 = requests.patch(
        f"https://api.notion.com/v1/pages/{pagina['id']}",
        headers=HEADERS,
        json={"archived": True},
    )
    r2.raise_for_status()
    print(f"  Movido: '{nome}' -> Time Interno (id origem {pagina['id']} arquivado)")


def run(dry_run=True):
    if not dry_run:
        get_ensure_data_original_property()

    destino_pages = query_database(NOTION_DB_ID_INTERNO)
    destino_seq = []
    for p in destino_pages:
        data_original = p["properties"].get(PROP_DATA_ORIGINAL, {}).get("date")
        ts = data_original["start"] if data_original else p["created_time"]
        destino_seq.append((ts, "destino", p))

    origem_pages = query_database(
        NOTION_DB_ID_ORIGEM,
        filter_={"property": "Data de chegada", "created_time": {"after": CORTE_INICIO}},
    )
    # Leads fora do horário comercial (7h-18h Brasília) nunca entram na rotação:
    # ficam sempre na origem e não contam posição para os outros leads.
    origem_seq = [
        (p["created_time"], "origem", p)
        for p in origem_pages
        if dentro_horario_comercial(p["created_time"])
    ]

    todos = sorted(destino_seq + origem_seq, key=lambda x: x[0])

    print(f"Total de leads pós-corte considerados: {len(todos)} "
          f"(ja no destino: {len(destino_seq)}, ainda na origem: {len(origem_seq)})")

    movidos = 0
    for i, (ts, origem_tipo, pagina) in enumerate(todos, start=1):
        if origem_tipo == "destino":
            continue  # já processado em execução anterior
        if i % A_CADA == 0:
            mover_lead(pagina, dry_run)
            movidos += 1

    print(f"{'[DRY-RUN] ' if dry_run else ''}Total movidos nesta execução: {movidos}")


if __name__ == "__main__":
    modo = sys.argv[1] if len(sys.argv) > 1 else "dry-run"
    run(dry_run=(modo != "apply"))
