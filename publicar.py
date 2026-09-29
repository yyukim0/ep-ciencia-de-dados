#!/usr/bin/env python3
"""
publicar.py — SILVER (PostgreSQL) -> GOLD (PostgreSQL)

Cria o schema gold (sql/gold.sql) e o repovoa a partir do silver por
INSERT INTO gold.<tabela> SELECT ... FROM silver.<tabela>: agregação
executada inteiramente pelo banco, sem transferir linha alguma para a
memória do processo Python (seção 5.1, R8, R11). Cada tabela do gold
corresponde ao grão de uma das análises 3 a 7 e da análise proposta pelo
grupo (análise 8).

Idempotência: cada tabela é truncada e reconstruída a cada execução —
mesmo padrão de carregar.py.

Uso:
    python publicar.py

Variáveis de ambiente:
    POSTGRES_DSN   default "dbname=pokedex user=postgres host=localhost"
"""

import os
import sys
from datetime import datetime, timezone

import psycopg

POSTGRES_DSN = os.environ.get("POSTGRES_DSN", "dbname=pokedex user=postgres host=localhost")
SQL_GOLD_PATH = os.path.join("sql", "gold.sql")

TABELAS_GOLD = [
    "ranking_pokemon",
    "taxa_vitorias_por_tipo",
    "taxa_vitorias_por_faixa_velocidade",
    "taxa_vitorias_por_multiplicador",
    "matriz_confronto",
    "taxa_vitorias_geracao_ataque",
]

SQL_POVOAMENTO = {
    # Análise 3 — taxa de vitórias por Pokémon. O corte mínimo de combates
    # NÃO é aplicado aqui (fica em consultas.sql, sobre a coluna "combates").
    "ranking_pokemon": """
        INSERT INTO gold.ranking_pokemon
            (pokemon_key, nome, numero_pokedex, numero_csv, tipo_1, tipo_2,
             combates, vitorias, taxa_vitorias)
        SELECT
            p.pokemon_key, p.nome, p.numero_pokedex, p.numero_csv,
            p.tipo_1, p.tipo_2,
            COUNT(f.confronto_key)                    AS combates,
            COALESCE(SUM(f.venceu), 0)                 AS vitorias,
            COALESCE(AVG(f.venceu::numeric), 0)         AS taxa_vitorias
        FROM silver.dim_pokemon p
        LEFT JOIN silver.fato_confronto f ON f.pokemon_key = p.pokemon_key
        GROUP BY p.pokemon_key, p.nome, p.numero_pokedex, p.numero_csv,
                 p.tipo_1, p.tipo_2
    """,
    # Análise 4 — taxa de vitórias por tipo primário. A fato liga-se
    # diretamente a dim_tipo (RS2): não há necessidade de passar por
    # dim_pokemon.
    "taxa_vitorias_por_tipo": """
        INSERT INTO gold.taxa_vitorias_por_tipo (tipo, combates, vitorias, taxa_vitorias)
        SELECT
            dt.nome_tipo,
            COUNT(*)                    AS combates,
            SUM(f.venceu)                AS vitorias,
            AVG(f.venceu::numeric)       AS taxa_vitorias
        FROM silver.fato_confronto f
        JOIN silver.dim_tipo dt ON dt.tipo_key = f.tipo_1_key
        GROUP BY dt.nome_tipo
    """,
    # Análise 5 — relação entre diferença de velocidade e vitória.
    # Faixas simétricas em torno de zero (decisão do grupo, justificada no
    # README.md): "muito mais lento" / "mais lento" / "empate" / "mais
    # rápido" / "muito mais rápido", com corte em +-50 pontos de velocidade
    # (aprox. um terço da amplitude típica do atributo Speed na Pokédex).
    "taxa_vitorias_por_faixa_velocidade": """
        INSERT INTO gold.taxa_vitorias_por_faixa_velocidade
            (faixa, ordem, limite_inferior, limite_superior, combates, vitorias, taxa_vitorias)
        SELECT faixa, ordem, limite_inferior, limite_superior,
               COUNT(*) AS combates,
               SUM(venceu) AS vitorias,
               AVG(venceu::numeric) AS taxa_vitorias
        FROM (
            SELECT
                f.venceu,
                CASE
                    WHEN f.diferenca_velocidade <= -50 THEN 'Muito mais lento (<= -50)'
                    WHEN f.diferenca_velocidade BETWEEN -49 AND -1 THEN 'Mais lento (-49 a -1)'
                    WHEN f.diferenca_velocidade = 0 THEN 'Empate de velocidade (0)'
                    WHEN f.diferenca_velocidade BETWEEN 1 AND 49 THEN 'Mais rápido (1 a 49)'
                    ELSE 'Muito mais rápido (>= 50)'
                END AS faixa,
                CASE
                    WHEN f.diferenca_velocidade <= -50 THEN 1
                    WHEN f.diferenca_velocidade BETWEEN -49 AND -1 THEN 2
                    WHEN f.diferenca_velocidade = 0 THEN 3
                    WHEN f.diferenca_velocidade BETWEEN 1 AND 49 THEN 4
                    ELSE 5
                END AS ordem,
                CASE WHEN f.diferenca_velocidade <= -50 THEN NULL ELSE
                    CASE
                        WHEN f.diferenca_velocidade BETWEEN -49 AND -1 THEN -49
                        WHEN f.diferenca_velocidade = 0 THEN 0
                        WHEN f.diferenca_velocidade BETWEEN 1 AND 49 THEN 1
                        ELSE 50
                    END
                END AS limite_inferior,
                CASE WHEN f.diferenca_velocidade >= 50 THEN NULL ELSE
                    CASE
                        WHEN f.diferenca_velocidade <= -50 THEN -50
                        WHEN f.diferenca_velocidade BETWEEN -49 AND -1 THEN -1
                        WHEN f.diferenca_velocidade = 0 THEN 0
                        ELSE 49
                    END
                END AS limite_superior
            FROM silver.fato_confronto f
        ) faixas
        GROUP BY faixa, ordem, limite_inferior, limite_superior
    """,
    # Análise 6 — vantagem de tipo x vitória. Multiplicador combinado dos
    # dois tipos do OPONENTE (decisão 3 da seção 4.2), a partir do tipo
    # próprio como atacante. O LEFT JOIN em e2 resolve sozinho o caso de
    # oponente com um único tipo: como "Nenhum" não existe em
    # efetividade_tipo, e2 fica NULL e o COALESCE aplica multiplicador 1.
    "taxa_vitorias_por_multiplicador": """
        INSERT INTO gold.taxa_vitorias_por_multiplicador
            (multiplicador, combates, vitorias, taxa_vitorias)
        SELECT multiplicador,
               COUNT(*) AS combates,
               SUM(venceu) AS vitorias,
               AVG(venceu::numeric) AS taxa_vitorias
        FROM (
            SELECT
                f.venceu,
                (e1.multiplicador * COALESCE(e2.multiplicador, 1))::numeric(4,2) AS multiplicador
            FROM silver.fato_confronto f
            JOIN silver.efetividade_tipo e1
                ON e1.tipo_atacante_key = f.tipo_1_key
               AND e1.tipo_defensor_key = f.tipo_oponente_1_key
            LEFT JOIN silver.efetividade_tipo e2
                ON e2.tipo_atacante_key = f.tipo_1_key
               AND e2.tipo_defensor_key = f.tipo_oponente_2_key
        ) combinados
        GROUP BY multiplicador
    """,
    # Análise 7 — matriz de confronto 18x18, por tipos PRIMÁRIOS (a
    # orientação é a do vencedor, não de quem atacou primeiro — por isso
    # não há filtro de atacou_primeiro aqui: cada combate contribui uma vez
    # como vitória em (A,B) e uma vez como derrota em (B,A), o que já é
    # garantido pelo grão "uma linha por participação").
    "matriz_confronto": """
        INSERT INTO gold.matriz_confronto
            (tipo_atacante, tipo_defensor, combates, vitorias_atacante,
             taxa_vitorias_atacante, multiplicador_matriz, diverge)
        SELECT
            ta.nome_tipo, td.nome_tipo,
            COUNT(*) AS combates,
            SUM(f.venceu) AS vitorias_atacante,
            AVG(f.venceu::numeric) AS taxa_vitorias_atacante,
            et.multiplicador,
            (et.multiplicador > 1 AND AVG(f.venceu::numeric) <= 0.5)
                OR (et.multiplicador < 1 AND AVG(f.venceu::numeric) >= 0.5) AS diverge
        FROM silver.fato_confronto f
        JOIN silver.dim_tipo ta ON ta.tipo_key = f.tipo_1_key
        JOIN silver.dim_tipo td ON td.tipo_key = f.tipo_oponente_1_key
        JOIN silver.efetividade_tipo et
            ON et.tipo_atacante_key = f.tipo_1_key
           AND et.tipo_defensor_key = f.tipo_oponente_1_key
        GROUP BY ta.nome_tipo, td.nome_tipo, et.multiplicador
    """,
    # Análise 8 (proposta pelo grupo) — efeito de atacar primeiro, por
    # geração de introdução. Ver justificativa da capacidade exigida em
    # sql/gold.sql e no README.md.
    "taxa_vitorias_geracao_ataque": """
        INSERT INTO gold.taxa_vitorias_geracao_ataque
            (geracao, atacou_primeiro, combates, vitorias, taxa_vitorias)
        SELECT
            dg.numero_geracao, f.atacou_primeiro,
            COUNT(*) AS combates,
            SUM(f.venceu) AS vitorias,
            AVG(f.venceu::numeric) AS taxa_vitorias
        FROM silver.fato_confronto f
        JOIN silver.dim_geracao dg ON dg.geracao_key = f.geracao_key
        GROUP BY dg.numero_geracao, f.atacou_primeiro
    """,
}


def executar_ddl(cur):
    with open(SQL_GOLD_PATH, "r", encoding="utf-8") as f:
        cur.execute(f.read())


def main():
    inicio = datetime.now(timezone.utc)

    with psycopg.connect(POSTGRES_DSN) as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                print("Executando sql/gold.sql (DDL)...")
                executar_ddl(cur)

                print("Truncando gold para repovoamento idempotente...")
                cur.execute(
                    "TRUNCATE TABLE " + ", ".join(f"gold.{t}" for t in TABELAS_GOLD)
                )

                contagens = {}
                for tabela in TABELAS_GOLD:
                    print(f"Publicando gold.{tabela}...")
                    cur.execute(SQL_POVOAMENTO[tabela])
                    cur.execute(f"SELECT COUNT(*) FROM gold.{tabela}")
                    contagens[tabela] = cur.fetchone()[0]

                agora = datetime.now(timezone.utc)
                for tabela, linhas in contagens.items():
                    cur.execute(
                        "INSERT INTO gold._log_carga (tabela, linhas, carregado_em) "
                        "VALUES (%s, %s, %s)",
                        (tabela, linhas, agora),
                    )

    duracao = (datetime.now(timezone.utc) - inicio).total_seconds()
    print("\n== resumo da publicação ==")
    for tabela, linhas in contagens.items():
        print(f"  gold.{tabela}: {linhas} linhas")
    print(f"  duração: {duracao:.1f}s")


if __name__ == "__main__":
    main()
