#!/usr/bin/env python3
"""
extrair.py — FONTES -> BRONZE (MongoDB)

Extrai as cinco coleções da camada bronze, sem qualquer transformação:

    pokemon       (PokéAPI, /pokemon/{id})       ~800 documentos
    especies      (PokéAPI, /pokemon-species/{id}) 721 documentos
    tipos         (PokéAPI, /type/{id})           21 documentos
    pokemon_csv   (pokemon.csv)                   800 documentos
    combates      (combats.csv)                   50.000 documentos

Regras observadas (seção 3 do enunciado):
  - o documento reproduz a resposta da fonte, sem renomear, achatar ou
    descartar campos;
  - todo documento carrega linhagem em campos prefixados com "_";
  - o _id deriva da chave natural da origem, o que torna a carga uma
    operação de upsert (idempotente: R3);
  - o cache em disco precede a escrita no Mongo, e a API só é consultada
    quando o arquivo de cache correspondente não existe (R1: a segunda
    execução não faz nenhuma requisição).

Uso:
    python extrair.py

Variáveis de ambiente (todas opcionais, com valor-padrão local):
    MONGO_URI   default "mongodb://localhost:27017"
    POKEAPI_BASE default "https://pokeapi.co/api/v2"
"""

import csv
import io
import json
import os
import sys
import time
from datetime import datetime, timezone

import requests
from pymongo import MongoClient
from pymongo.errors import PyMongoError

MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017")
POKEAPI_BASE = os.environ.get("POKEAPI_BASE", "https://pokeapi.co/api/v2")

CACHE_DIR = "dados_brutos"
INTERVALO_ENTRE_REQUISICOES = 0.1  # segundos, recomendado pelo enunciado

POKEMON_CSV_URL = "https://raw.githubusercontent.com/cdiener/pokemon_app/master/pokemon.csv"
COMBATS_CSV_URL = "https://raw.githubusercontent.com/cdiener/pokemon_app/master/combats.csv"

# Gerações I a VI cobrem as espécies de Pokédex nacional 1 a 721 (escopo obrigatório).
PRIMEIRA_ESPECIE = 1
ULTIMA_ESPECIE = 721

# 18 tipos reais (1-18) + stellar (19) + unknown (10001) + shadow (10002) = 21,
# conforme a seção 1.1. Todos os 21 são extraídos para a bronze: a decisão de
# filtrar os três tipos que não existem no jogo de origem dos dados de batalha
# é tomada no silver (carregar.py), não aqui — a bronze não filtra nada.
IDS_TIPOS = list(range(1, 19)) + [19, 10001, 10002]


def agora_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def caminho_cache(*partes):
    return os.path.join(CACHE_DIR, *partes)


def garantir_diretorio(caminho):
    os.makedirs(os.path.dirname(caminho), exist_ok=True)


def obter_json(sessao, url, cache_path):
    """Lê do cache em disco se existir; caso contrário, consulta a API,
    grava o cache e só então aguarda o intervalo de cortesia. Retorna o
    payload já desserializado e um booleano indicando se houve requisição
    de rede (usado apenas para o resumo impresso ao final)."""
    if os.path.exists(cache_path):
        with open(cache_path, "r", encoding="utf-8") as f:
            return json.load(f), False

    resposta = sessao.get(url, timeout=30)
    resposta.raise_for_status()
    payload = resposta.json()

    garantir_diretorio(cache_path)
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    time.sleep(INTERVALO_ENTRE_REQUISICOES)
    return payload, True


def obter_texto(sessao, url, cache_path):
    if os.path.exists(cache_path):
        with open(cache_path, "r", encoding="utf-8") as f:
            return f.read(), False

    resposta = sessao.get(url, timeout=60)
    resposta.raise_for_status()
    texto = resposta.text

    garantir_diretorio(cache_path)
    with open(cache_path, "w", encoding="utf-8") as f:
        f.write(texto)

    time.sleep(INTERVALO_ENTRE_REQUISICOES)
    return texto, True


def upsert(colecao, _id, campos_linhagem, payload):
    """Grava um documento de bronze: linhagem + payload bruto, por upsert
    em _id — chave natural da fonte. Repetir a carga não duplica nem altera
    o resultado (idempotência, R3)."""
    documento = dict(campos_linhagem)
    documento.update(payload)
    documento["_id"] = _id
    colecao.update_one({"_id": _id}, {"$set": documento}, upsert=True)


def extrair_tipos(db, sessao):
    print("== tipos ==")
    colecao = db["tipos"]
    requisicoes = 0
    for tid in IDS_TIPOS:
        url = f"{POKEAPI_BASE}/type/{tid}"
        cache_path = caminho_cache("tipos", f"{tid}.json")
        payload, houve_requisicao = obter_json(sessao, url, cache_path)
        requisicoes += houve_requisicao
        upsert(
            colecao,
            f"tipo/{tid}",
            {
                "_fonte": "pokeapi",
                "_url": url,
                "_ingerido_em": agora_iso(),
            },
            payload,
        )
    print(f"  {len(IDS_TIPOS)} documentos ({requisicoes} requisições HTTP)")


def extrair_especies(db, sessao):
    """Extrai as 721 espécies e devolve a lista de (nome, url) de TODAS as
    variedades (formas) referenciadas em varieties[], para que a etapa
    seguinte busque cada forma em /pokemon/. Isso alcança as formas
    alternativas exigidas pela seção 1.1, que uma iteração 1..721 não
    alcançaria (elas têm id > 10000 e não têm registro próprio em
    /pokemon-species/)."""
    print("== especies ==")
    colecao = db["especies"]
    requisicoes = 0
    variedades = []  # lista de dicts {"name":..., "url":...}
    vistas = set()

    for sid in range(PRIMEIRA_ESPECIE, ULTIMA_ESPECIE + 1):
        url = f"{POKEAPI_BASE}/pokemon-species/{sid}"
        cache_path = caminho_cache("especies", f"{sid}.json")
        payload, houve_requisicao = obter_json(sessao, url, cache_path)
        requisicoes += houve_requisicao
        upsert(
            colecao,
            f"especie/{sid}",
            {
                "_fonte": "pokeapi",
                "_url": url,
                "_ingerido_em": agora_iso(),
            },
            payload,
        )
        for variedade in payload.get("varieties", []):
            ref = variedade.get("pokemon", {})
            if ref.get("name") and ref["name"] not in vistas:
                vistas.add(ref["name"])
                variedades.append(ref)

    print(f"  {ULTIMA_ESPECIE} documentos ({requisicoes} requisições HTTP)")
    print(f"  {len(variedades)} formas referenciadas em varieties[] (default + alternativas)")
    return variedades


def id_a_partir_da_url(url):
    """/pokemon/10034/ -> 10034"""
    return url.rstrip("/").split("/")[-1]


def extrair_pokemon(db, sessao, variedades):
    print("== pokemon ==")
    colecao = db["pokemon"]
    requisicoes = 0
    for ref in variedades:
        nome = ref["name"]
        url = ref["url"]
        pid = id_a_partir_da_url(url)
        # A URL de varieties[] aponta para /pokemon-form/ em alguns casos raros;
        # aqui sempre resolvemos por nome contra o endpoint /pokemon/, que é o
        # exigido pela seção 1.1 (campos height, weight, types[], stats[] etc.).
        url_pokemon = f"{POKEAPI_BASE}/pokemon/{nome}"
        cache_path = caminho_cache("pokemon", f"{pid}.json")
        payload, houve_requisicao = obter_json(sessao, url_pokemon, cache_path)
        requisicoes += houve_requisicao
        upsert(
            colecao,
            f"pokemon/{payload['id']}",
            {
                "_fonte": "pokeapi",
                "_url": url_pokemon,
                "_ingerido_em": agora_iso(),
            },
            payload,
        )
    print(f"  {len(variedades)} documentos ({requisicoes} requisições HTTP)")


def extrair_csv_pokemon(db, sessao):
    print("== pokemon_csv ==")
    colecao = db["pokemon_csv"]
    cache_path = caminho_cache("csv", "pokemon.csv")
    texto, houve_requisicao = obter_texto(sessao, POKEMON_CSV_URL, cache_path)

    leitor = csv.DictReader(io.StringIO(texto))
    total = 0
    for linha in leitor:
        # Todos os campos são preservados como texto: a conversão numérica é
        # uma transformação de silver, e a bronze não transforma (seção 3).
        numero = linha["#"]
        upsert(
            colecao,
            f"pokemon_csv/{numero}",
            {
                "_fonte": "pokemon.csv",
                "_url": POKEMON_CSV_URL,
                "_ingerido_em": agora_iso(),
            },
            dict(linha),
        )
        total += 1
    print(f"  {total} documentos ({1 if houve_requisicao else 0} requisição HTTP)")


def extrair_csv_combates(db, sessao):
    print("== combates ==")
    colecao = db["combates"]
    cache_path = caminho_cache("csv", "combats.csv")
    texto, houve_requisicao = obter_texto(sessao, COMBATS_CSV_URL, cache_path)

    leitor = csv.DictReader(io.StringIO(texto))
    total = 0
    for numero, linha in enumerate(leitor, start=1):
        upsert(
            colecao,
            f"combate/{numero}",
            {
                "_fonte": "combats.csv",
                "_url": COMBATS_CSV_URL,
                "_ingerido_em": agora_iso(),
                "_linha_csv": numero,
            },
            dict(linha),
        )
        total += 1
    print(f"  {total} documentos ({1 if houve_requisicao else 0} requisição HTTP)")


def main():
    try:
        client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        client.admin.command("ping")
    except PyMongoError as erro:
        print(f"Não foi possível conectar ao MongoDB em {MONGO_URI}: {erro}", file=sys.stderr)
        sys.exit(1)

    db = client["pokedex_bronze"]
    sessao = requests.Session()
    sessao.headers.update({"User-Agent": "ep01-pokedex-bronze/1.0"})

    extrair_tipos(db, sessao)
    variedades = extrair_especies(db, sessao)
    extrair_pokemon(db, sessao, variedades)
    extrair_csv_pokemon(db, sessao)
    extrair_csv_combates(db, sessao)

    print("\n== resumo ==")
    for nome_colecao in ["pokemon", "especies", "tipos", "pokemon_csv", "combates"]:
        print(f"  {nome_colecao}: {db[nome_colecao].count_documents({})} documentos")


if __name__ == "__main__":
    main()
