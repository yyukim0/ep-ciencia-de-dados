#!/usr/bin/env python3
"""
carregar.py — BRONZE (MongoDB) -> SILVER (PostgreSQL)

Lê exclusivamente da camada bronze (nunca da API ou dos arquivos CSV — a
verificação da correção executa este script sem acesso à rede, R7), concilia
as duas fontes por nome (R4), aplica as seis decisões de modelagem descritas
no README.md, e popula o esquema estrela definido em sql/silver.sql.

Idempotência: a cada execução, as tabelas de silver são truncadas e
totalmente reconstruídas a partir da bronze. Isso é deliberado — a bronze é
a fonte da verdade imutável, e reprocessar do zero a cada carga é a forma
mais simples de garantir "reexecução sem duplicar linhas" (R7), sem exigir
lógica de upsert coluna a coluna sobre um modelo dimensional inteiro.

Uso:
    python carregar.py

Variáveis de ambiente:
    MONGO_URI      default "mongodb://localhost:27017"
    POSTGRES_DSN   default "dbname=pokedex user=postgres host=localhost"
"""

import csv
import os
import re
import sys
from datetime import datetime, timezone

import psycopg
from pymongo import MongoClient
from pymongo.errors import PyMongoError

MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017")
POSTGRES_DSN = os.environ.get("POSTGRES_DSN", "dbname=pokedex user=postgres host=localhost")

SQL_SILVER_PATH = os.path.join("sql", "silver.sql")
RELATORIO_CONCILIACAO_PATH = "conciliacao.csv"

GERACOES = [
    (1, "Geração I", "Kanto"),
    (2, "Geração II", "Johto"),
    (3, "Geração III", "Hoenn"),
    (4, "Geração IV", "Sinnoh"),
    (5, "Geração V", "Unova"),
    (6, "Geração VI", "Kalos"),
]

# ─────────────────────── conciliação de chaves (R4) ───────────────────────
#
# O campo "#" do CSV é um índice sequencial (Problema 1, seção 1.4): a única
# via de conciliação é o nome. A normalização abaixo cobre os padrões
# regulares observados nas ~79 formas alternativas descritas na seção 1.1
# ("Mega X [Y]", "Primal X", "X Y Forme", "X Y Cloak", "X Y Size",
# "X Zen Mode"), e um dicionário cobre os nomes que não seguem nenhum padrão
# regular (espécies com nome composto, símbolos de gênero, apóstrofo etc.).
#
# Nenhuma estratégia de normalização produz correspondência integral (seção
# 1.4): o que não casar aqui é registrado em conciliacao.csv, e não
# descartado silenciosamente (R4). Como este ambiente de desenvolvimento não
# tem acesso à PokéAPI, este dicionário não pôde ser validado contra as
# respostas reais — o grupo deve conferir e completá-lo a partir do
# conciliacao.csv gerado na primeira execução real do pipeline.

OVERRIDES_EXPLICITOS = {
    "Nidoran♀": "nidoran-f",
    "Nidoran♂": "nidoran-m",
    "Farfetch'd": "farfetchd",
    "Mr. Mime": "mr-mime",
    "Mime Jr.": "mime-jr",
    "Ho-oh": "ho-oh",
    "Ho-Oh": "ho-oh",
    "Porygon2": "porygon2",
    "Porygon-Z": "porygon-z",
    "Kyurem Black": "kyurem-black",
    "Kyurem White": "kyurem-white",
    "Hoopa Unbound": "hoopa-unbound",
    "Keldeo Resolute Forme": "keldeo-resolute",
    "Meloetta Pirouette Forme": "meloetta-pirouette",
}


def normalizar(texto):
    s = texto.strip().lower()
    s = s.replace("♀", "-f").replace("♂", "-m")
    s = s.replace("'", "").replace(".", "")
    s = re.sub(r"\s+", "-", s)
    s = re.sub(r"[^a-z0-9\-]", "", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s


def candidatos_de_slug(nome_csv):
    """Gera, em ordem de prioridade, os slugs candidatos da PokéAPI para um
    nome do pokemon.csv. O primeiro que existir em pokemon_by_name é aceito."""
    candidatos = []

    if nome_csv in OVERRIDES_EXPLICITOS:
        candidatos.append(OVERRIDES_EXPLICITOS[nome_csv])

    palavras = nome_csv.split()

    if len(palavras) >= 2 and palavras[-1].lower() == "forme":
        especie, variante = palavras[0], palavras[1:-1]
        candidatos.append(normalizar(especie) + "-" + normalizar(" ".join(variante)))
    elif len(palavras) >= 2 and palavras[-1].lower() == "cloak":
        especie, variante = palavras[0], palavras[1:-1]
        candidatos.append(normalizar(especie) + "-" + normalizar(" ".join(variante)))
    elif len(palavras) >= 2 and palavras[-1].lower() == "size":
        especie, variante = palavras[0], palavras[1:-1]
        candidatos.append(normalizar(especie) + "-" + normalizar(" ".join(variante)))
    elif len(palavras) >= 3 and [p.lower() for p in palavras[-2:]] == ["zen", "mode"]:
        candidatos.append(normalizar(palavras[0]) + "-zen")
    elif palavras and palavras[0].lower() == "mega":
        sufixo = ""
        corpo = palavras[1:]
        if corpo and corpo[-1] in ("X", "Y"):
            sufixo = "-" + corpo[-1].lower()
            corpo = corpo[:-1]
        candidatos.append(normalizar(" ".join(corpo)) + "-mega" + sufixo)
    elif palavras and palavras[0].lower() == "primal":
        candidatos.append(normalizar(" ".join(palavras[1:])) + "-primal")

    if len(palavras) == 2:
        candidatos.append(normalizar(palavras[0]) + "-" + normalizar(palavras[1]))

    candidatos.append(normalizar(nome_csv))

    vistos, resultado = set(), []
    for c in candidatos:
        if c not in vistos:
            vistos.add(c)
            resultado.append(c)
    return resultado


def conectar_mongo():
    try:
        client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        client.admin.command("ping")
    except PyMongoError as erro:
        print(f"Não foi possível conectar ao MongoDB em {MONGO_URI}: {erro}", file=sys.stderr)
        sys.exit(1)
    return client["pokedex_bronze"]


def carregar_bronze(db):
    """Lê as cinco coleções da bronze para estruturas Python simples (dict/
    list) — sem qualquer biblioteca tabular, nos termos do R11."""
    tipos = list(db["tipos"].find({}))
    especies = list(db["especies"].find({}))
    pokemon = list(db["pokemon"].find({}))
    pokemon_csv = list(db["pokemon_csv"].find({}))
    combates = list(db["combates"].find({}))
    return tipos, especies, pokemon, pokemon_csv, combates


def executar_ddl(cur):
    with open(SQL_SILVER_PATH, "r", encoding="utf-8") as f:
        cur.execute(f.read())


def truncar_silver(cur):
    cur.execute(
        """
        TRUNCATE TABLE
            silver.fato_confronto,
            silver.efetividade_tipo,
            silver.dim_pokemon,
            silver.dim_tipo,
            silver.dim_geracao
        RESTART IDENTITY CASCADE
        """
    )


def carregar_dim_geracao(cur):
    key_por_numero = {}
    for numero, nome, regiao in GERACOES:
        cur.execute(
            "INSERT INTO silver.dim_geracao (numero_geracao, nome_geracao, regiao) "
            "VALUES (%s, %s, %s) RETURNING geracao_key",
            (numero, nome, regiao),
        )
        key_por_numero[numero] = cur.fetchone()[0]
    return key_por_numero


def carregar_dim_tipo(cur, tipos_bronze):
    """Filtra os 18 tipos reais (ids 1-18); stellar/unknown/shadow (ids 19,
    10001, 10002) não são carregados no silver — decisão do grupo (seção
    1.1), justificada no README.md: não existem no jogo que gerou os dados
    de batalha, logo não podem ser referenciados por nenhum combate."""
    key_por_nome = {}
    tipos_reais = [t for t in tipos_bronze if 1 <= t["id"] <= 18]
    for tipo in sorted(tipos_reais, key=lambda t: t["id"]):
        cur.execute(
            "INSERT INTO silver.dim_tipo (nome_tipo, id_pokeapi) VALUES (%s, %s) "
            "RETURNING tipo_key",
            (tipo["name"], tipo["id"]),
        )
        key_por_nome[tipo["name"]] = cur.fetchone()[0]

    # membro especial (RS4): ausência de segundo tipo
    cur.execute(
        "INSERT INTO silver.dim_tipo (nome_tipo, id_pokeapi) VALUES (%s, NULL) "
        "RETURNING tipo_key",
        ("Nenhum",),
    )
    key_por_nome["Nenhum"] = cur.fetchone()[0]

    return key_por_nome, {t["id"]: t for t in tipos_reais}


def carregar_efetividade_tipo(cur, tipos_por_id, tipo_key_por_nome):
    nomes_validos = set(tipo_key_por_nome.keys()) - {"Nenhum"}
    matriz = {(a, d): 1.0 for a in nomes_validos for d in nomes_validos}

    for tipo in tipos_por_id.values():
        atacante = tipo["name"]
        relacoes = tipo.get("damage_relations", {})
        for alvo in relacoes.get("double_damage_to", []):
            if alvo["name"] in nomes_validos:
                matriz[(atacante, alvo["name"])] = 2.0
        for alvo in relacoes.get("half_damage_to", []):
            if alvo["name"] in nomes_validos:
                matriz[(atacante, alvo["name"])] = 0.5
        for alvo in relacoes.get("no_damage_to", []):
            if alvo["name"] in nomes_validos:
                matriz[(atacante, alvo["name"])] = 0.0

    with cur.copy(
        "COPY silver.efetividade_tipo (tipo_atacante_key, tipo_defensor_key, multiplicador) "
        "FROM STDIN"
    ) as copy:
        for (atacante, defensor), multiplicador in matriz.items():
            copy.write_row(
                (tipo_key_por_nome[atacante], tipo_key_por_nome[defensor], multiplicador)
            )


def categoria_de_raridade(is_legendary, is_mythical, is_baby):
    if is_mythical:
        return "mítico"
    if is_legendary:
        return "lendário"
    if is_baby:
        return "bebê"
    return "comum"


def montar_indices_pokeapi(especies_bronze, pokemon_bronze):
    especies_por_nome = {e["name"]: e for e in especies_bronze}
    pokemon_por_nome = {p["name"]: p for p in pokemon_bronze}
    return especies_por_nome, pokemon_por_nome


def conciliar_e_carregar_dim_pokemon(cur, pokemon_csv_bronze, especies_por_nome, pokemon_por_nome):
    """Resolve cada linha do pokemon.csv contra a PokéAPI, grava
    silver.dim_pokemon e devolve:
      - perfil_por_numero_csv: {numero_csv: dict com pokemon_key, tipo_1,
        tipo_2, velocidade, geracao} — usado para montar a fato;
      - linhas_conciliacao: lista de dicts para o conciliacao.csv (R4).
    """
    perfil_por_numero_csv = {}
    linhas_conciliacao = []

    for doc in sorted(pokemon_csv_bronze, key=lambda d: int(d["#"])):
        numero_csv = int(doc["#"])
        nome_csv = (doc.get("Name") or "").strip()

        hp = int(doc["HP"])
        ataque = int(doc["Attack"])
        defesa = int(doc["Defense"])
        ataque_especial = int(doc["Sp. Atk"])
        defesa_especial = int(doc["Sp. Def"])
        velocidade = int(doc["Speed"])
        geracao = int(doc["Generation"])
        tipo_1 = doc["Type 1"]
        tipo_2 = doc["Type 2"] or "Nenhum"
        legendary_csv = doc["Legendary"].strip().lower() == "true"

        nome_desconhecido = nome_csv == ""

        pdoc = None
        candidato_aceito = None
        if not nome_desconhecido:
            for candidato in candidatos_de_slug(nome_csv):
                if candidato in pokemon_por_nome:
                    pdoc = pokemon_por_nome[candidato]
                    candidato_aceito = candidato
                    break

        if pdoc is not None:
            conciliado = True
            is_forma_alternativa = not pdoc.get("is_default", True)
            forma_slug = pdoc["name"] if is_forma_alternativa else None
            altura = pdoc.get("height")
            peso = pdoc.get("weight")
            experiencia_base = pdoc.get("base_experience")
            quantidade_habilidades = len(pdoc.get("abilities") or [])

            especie_nome = (pdoc.get("species") or {}).get("name")
            edoc = especies_por_nome.get(especie_nome)
            if edoc is not None:
                numero_pokedex = edoc.get("id")
                habitat_ref = edoc.get("habitat")
                # Problema 3: habitat nulo em espécies pós FireRed/LeafGreen
                # é um CONCEITO INAPLICÁVEL, não um dado ausente -> sentinela
                # textual explícita, nunca NULL puro.
                habitat = habitat_ref["name"] if habitat_ref else "não se aplica"
                cor = (edoc.get("color") or {}).get("name")
                forma_corporal = (edoc.get("shape") or {}).get("name")
                taxa_captura = edoc.get("capture_rate")
                felicidade_base = edoc.get("base_happiness")
                taxa_crescimento = (edoc.get("growth_rate") or {}).get("name")
                is_legendary = bool(edoc.get("is_legendary"))
                is_mythical = bool(edoc.get("is_mythical"))
                is_baby = bool(edoc.get("is_baby"))
            else:
                numero_pokedex = None
                habitat = None
                cor = forma_corporal = taxa_crescimento = None
                taxa_captura = felicidade_base = None
                is_legendary = is_mythical = is_baby = False
        else:
            conciliado = False
            is_forma_alternativa = False
            forma_slug = None
            altura = peso = experiencia_base = quantidade_habilidades = None
            numero_pokedex = None
            habitat = cor = forma_corporal = taxa_crescimento = None
            taxa_captura = felicidade_base = None
            # Problema 2 (nome ausente) e falhas genuínas de conciliação não
            # têm indicador de raridade da PokéAPI; usa-se o único sinal
            # disponível no próprio CSV.
            is_legendary, is_mythical, is_baby = legendary_csv, False, False

        categoria_raridade = categoria_de_raridade(is_legendary, is_mythical, is_baby)
        nome_final = nome_csv if nome_csv else "Desconhecido (registro 63 do CSV)"

        cur.execute(
            """
            INSERT INTO silver.dim_pokemon (
                numero_csv, numero_pokedex, nome, nome_desconhecido, conciliado,
                is_forma_alternativa, forma_slug, geracao, habitat, cor,
                forma_corporal, taxa_captura, felicidade_base, taxa_crescimento,
                quantidade_habilidades, categoria_raridade, tipo_1, tipo_2,
                hp, ataque, defesa, ataque_especial, defesa_especial, velocidade,
                altura, peso, experiencia_base
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            ) RETURNING pokemon_key
            """,
            (
                numero_csv, numero_pokedex, nome_final, nome_desconhecido, conciliado,
                is_forma_alternativa, forma_slug, geracao, habitat, cor,
                forma_corporal, taxa_captura, felicidade_base, taxa_crescimento,
                quantidade_habilidades, categoria_raridade, tipo_1, tipo_2,
                hp, ataque, defesa, ataque_especial, defesa_especial, velocidade,
                altura, peso, experiencia_base,
            ),
        )
        pokemon_key = cur.fetchone()[0]

        perfil_por_numero_csv[numero_csv] = {
            "pokemon_key": pokemon_key,
            "tipo_1": tipo_1,
            "tipo_2": tipo_2,
            "velocidade": velocidade,
            "geracao": geracao,
        }

        if nome_desconhecido:
            status, tratamento = (
                "não conciliado",
                "nome ausente na fonte (Problema 2, seção 1.4); "
                "mantido no modelo com os atributos do CSV, "
                "sem atributos de espécie da PokéAPI (membro especial em dim_pokemon)",
            )
        elif conciliado:
            status, tratamento = "conciliado", f"casado com o slug '{candidato_aceito}' da PokéAPI"
        else:
            status, tratamento = (
                "não conciliado",
                "nenhum candidato de normalização casou com a PokéAPI; "
                "mantido no modelo apenas com os atributos do CSV",
            )

        linhas_conciliacao.append(
            {
                "numero_csv": numero_csv,
                "nome_csv": nome_csv,
                "slug_pokeapi": candidato_aceito or "",
                "status": status,
                "tratamento": tratamento,
            }
        )

    return perfil_por_numero_csv, linhas_conciliacao


def gravar_conciliacao_csv(linhas):
    with open(RELATORIO_CONCILIACAO_PATH, "w", newline="", encoding="utf-8") as f:
        campos = ["numero_csv", "nome_csv", "slug_pokeapi", "status", "tratamento"]
        escritor = csv.DictWriter(f, fieldnames=campos)
        escritor.writeheader()
        escritor.writerows(linhas)

    total = len(linhas)
    conciliados = sum(1 for l in linhas if l["status"] == "conciliado")
    print(f"  conciliacao.csv: {conciliados}/{total} registros conciliados com a PokéAPI")


def carregar_fato_confronto(cur, combates_bronze, perfil_por_numero_csv, geracao_key_por_numero, tipo_key_por_nome):
    def tipo_key(nome_tipo):
        return tipo_key_por_nome[nome_tipo]

    with cur.copy(
        "COPY silver.fato_confronto ("
        "combate_id, pokemon_key, oponente_key, geracao_key, "
        "tipo_1_key, tipo_2_key, tipo_oponente_1_key, tipo_oponente_2_key, "
        "atacou_primeiro, venceu, diferenca_velocidade"
        ") FROM STDIN"
    ) as copy:
        for doc in combates_bronze:
            combate_id = doc["_linha_csv"]
            primeiro = int(doc["First_pokemon"])
            segundo = int(doc["Second_pokemon"])
            vencedor = int(doc["Winner"])

            perfil_1 = perfil_por_numero_csv[primeiro]
            perfil_2 = perfil_por_numero_csv[segundo]

            for meu, dele, atacou_primeiro in (
                (perfil_1, perfil_2, True),
                (perfil_2, perfil_1, False),
            ):
                venceu = 1 if vencedor == (primeiro if meu is perfil_1 else segundo) else 0
                copy.write_row(
                    (
                        combate_id,
                        meu["pokemon_key"],
                        dele["pokemon_key"],
                        geracao_key_por_numero[meu["geracao"]],
                        tipo_key(meu["tipo_1"]),
                        tipo_key(meu["tipo_2"]),
                        tipo_key(dele["tipo_1"]),
                        tipo_key(dele["tipo_2"]),
                        atacou_primeiro,
                        venceu,
                        meu["velocidade"] - dele["velocidade"],
                    )
                )


def main():
    inicio = datetime.now(timezone.utc)
    db = conectar_mongo()

    print("Lendo bronze do MongoDB...")
    tipos_bronze, especies_bronze, pokemon_bronze, pokemon_csv_bronze, combates_bronze = carregar_bronze(db)
    print(
        f"  tipos={len(tipos_bronze)} especies={len(especies_bronze)} "
        f"pokemon={len(pokemon_bronze)} pokemon_csv={len(pokemon_csv_bronze)} "
        f"combates={len(combates_bronze)}"
    )

    with psycopg.connect(POSTGRES_DSN) as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                print("Executando sql/silver.sql (DDL)...")
                executar_ddl(cur)

                print("Truncando silver para reconstrução idempotente...")
                truncar_silver(cur)

                print("Carregando dim_geracao...")
                geracao_key_por_numero = carregar_dim_geracao(cur)

                print("Carregando dim_tipo...")
                tipo_key_por_nome, tipos_por_id = carregar_dim_tipo(cur, tipos_bronze)

                print("Carregando efetividade_tipo (324 combinações)...")
                carregar_efetividade_tipo(cur, tipos_por_id, tipo_key_por_nome)

                print("Conciliando e carregando dim_pokemon...")
                especies_por_nome, pokemon_por_nome = montar_indices_pokeapi(especies_bronze, pokemon_bronze)
                perfil_por_numero_csv, linhas_conciliacao = conciliar_e_carregar_dim_pokemon(
                    cur, pokemon_csv_bronze, especies_por_nome, pokemon_por_nome
                )
                gravar_conciliacao_csv(linhas_conciliacao)

                print("Carregando fato_confronto (uma linha por participação)...")
                carregar_fato_confronto(
                    cur, combates_bronze, perfil_por_numero_csv, geracao_key_por_numero, tipo_key_por_nome
                )

                cur.execute("SELECT COUNT(*) FROM silver.dim_pokemon")
                n_pokemon = cur.fetchone()[0]
                cur.execute("SELECT COUNT(*) FROM silver.fato_confronto")
                n_fato = cur.fetchone()[0]
                cur.execute("SELECT COUNT(*) FROM silver.efetividade_tipo")
                n_efet = cur.fetchone()[0]

    duracao = (datetime.now(timezone.utc) - inicio).total_seconds()
    print("\n== resumo da carga ==")
    print(f"  silver.dim_geracao      : {len(GERACOES)} linhas")
    print(f"  silver.dim_tipo         : {len(tipo_key_por_nome)} linhas")
    print(f"  silver.efetividade_tipo : {n_efet} linhas")
    print(f"  silver.dim_pokemon      : {n_pokemon} linhas")
    print(f"  silver.fato_confronto   : {n_fato} linhas")
    print(f"  duração: {duracao:.1f}s")

    if n_fato != 2 * len(combates_bronze):
        print(
            f"ATENÇÃO: esperava {2 * len(combates_bronze)} linhas em fato_confronto "
            f"(2 por combate), obteve {n_fato}. Nenhum combate pode ser omitido (R5).",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
