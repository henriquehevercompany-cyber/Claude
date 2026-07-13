import os
import sys
import requests

NOTION_TOKEN = os.environ["NOTION_TOKEN"]
NOTION_DB_ID_ORIGEM = os.environ["NOTION_DB_ID_ORIGEM"]      # Regional Pavuna (todos os leads)
NOTION_DB_ID_INTERNO = os.environ["NOTION_DB_ID_INTERNO"]     # Regional Pavuna Time Interno

# O rodízio do n8n ("Atribuição Kris") já escolhe um consultor por lead e grava esse
# nome em "Consultor atribuido". Quando o escolhido for um destes, o lead é movido
# para o board do time interno (onde essa pessoa realmente atende).
CONSULTORES_TIME_INTERNO = {"Sara Ferreira", "Isabelly Floriano", "Kristopher Souza"}

# Leads chegados antes deste corte nunca são movidos, mesmo que estejam atribuídos a um
# dos consultores acima — evita mover retroativamente centenas de leads antigos já
# atendidos (só entram os que chegarem a partir de agora).
CORTE_INICIO = "2026-07-13T17:21:00.000Z"

PROP_CONSULTOR = "Consultor atribuido"
PROP_DATA_ORIGINAL = "Data de chegada original"

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
    consultor = "".join(t["plain_text"] for t in pagina["properties"][PROP_CONSULTOR]["rich_text"])

    if dry_run:
        print(f"  [DRY-RUN] moveria lead '{nome}' (consultor={consultor}, id={pagina['id']})")
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
    print(f"  Movido: '{nome}' (consultor={consultor}) -> Time Interno (id origem {pagina['id']} arquivado)")


def run(dry_run=True):
    if not dry_run:
        get_ensure_data_original_property()

    filtro = {
        "and": [
            {"property": "Data de chegada", "created_time": {"after": CORTE_INICIO}},
            {
                "or": [
                    {"property": PROP_CONSULTOR, "rich_text": {"equals": nome}}
                    for nome in CONSULTORES_TIME_INTERNO
                ]
            },
        ]
    }
    candidatos = query_database(NOTION_DB_ID_ORIGEM, filter_=filtro)

    print(f"Leads na origem atribuídos a {sorted(CONSULTORES_TIME_INTERNO)}: {len(candidatos)}")

    movidos = 0
    for pagina in candidatos:
        mover_lead(pagina, dry_run)
        movidos += 1

    print(f"{'[DRY-RUN] ' if dry_run else ''}Total movidos nesta execução: {movidos}")


if __name__ == "__main__":
    modo = sys.argv[1] if len(sys.argv) > 1 else "dry-run"
    run(dry_run=(modo != "apply"))
