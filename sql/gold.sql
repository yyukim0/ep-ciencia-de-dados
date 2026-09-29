-- gold.sql — DDL das tabelas agregadas da camada gold.
--
-- Executado por publicar.py (R8). Contém apenas CREATE TABLE: a agregação
-- em si (INSERT INTO gold.<tabela> SELECT ... FROM silver.<tabela>) vive em
-- publicar.py, na forma de operação de conjunto executada pelo PostgreSQL
-- (seção 5.1) — não em Python, e não com pandas (R11).
--
-- Cada tabela atende ao grão de uma análise (seção 5): a consulta final em
-- consultas.sql lê estas tabelas com WHERE / ORDER BY / LIMIT apenas, sem
-- GROUP BY, função de agregação ou junção com o silver.

CREATE SCHEMA IF NOT EXISTS gold;

-- Análise 3 — taxa de vitórias por Pokémon.
-- O corte mínimo de combates da análise 3 é aplicado na CONSULTA, não aqui:
-- a coluna "combates" fica materializada para todos os ~800 Pokémon, e o
-- valor do corte é alterável em consultas.sql sem reprocessar o pipeline
-- (seção 5).
CREATE TABLE IF NOT EXISTS gold.ranking_pokemon (
    pokemon_key     INT PRIMARY KEY,
    nome            TEXT NOT NULL,
    numero_pokedex  INT,
    numero_csv      INT NOT NULL,
    tipo_1          TEXT NOT NULL,
    tipo_2          TEXT NOT NULL,
    combates        INT NOT NULL,
    vitorias        INT NOT NULL,
    taxa_vitorias   NUMERIC(6,4) NOT NULL
);

-- Análise 4 — taxa de vitórias por tipo primário.
CREATE TABLE IF NOT EXISTS gold.taxa_vitorias_por_tipo (
    tipo            TEXT PRIMARY KEY,
    combates        INT NOT NULL,
    vitorias        INT NOT NULL,
    taxa_vitorias   NUMERIC(6,4) NOT NULL
);

-- Análise 5 — relação entre diferença de velocidade e vitória.
-- As faixas e seus cortes são uma decisão do grupo (seção 7, análise 5),
-- justificada no README.md; "ordem" existe apenas para permitir ORDER BY
-- em sequência lógica (a faixa não tem ordenação alfabética natural).
CREATE TABLE IF NOT EXISTS gold.taxa_vitorias_por_faixa_velocidade (
    faixa               TEXT PRIMARY KEY,
    ordem               SMALLINT NOT NULL,
    limite_inferior     INT,
    limite_superior     INT,
    combates            INT NOT NULL,
    vitorias            INT NOT NULL,
    taxa_vitorias        NUMERIC(6,4) NOT NULL
);

-- Análise 6 — relação entre vantagem de tipo e vitória.
-- Uma linha por multiplicador de efetividade EFETIVAMENTE observado no
-- modelo (decisão 3 da seção 4.2: multiplicador combinado dos dois tipos do
-- oponente — 0, 0.25, 0.5, 1, 2 ou 4).
CREATE TABLE IF NOT EXISTS gold.taxa_vitorias_por_multiplicador (
    multiplicador   NUMERIC(4,2) PRIMARY KEY,
    combates        INT NOT NULL,
    vitorias        INT NOT NULL,
    taxa_vitorias   NUMERIC(6,4) NOT NULL
);

-- Análise 7 — matriz de confronto entre tipos (18 x 18).
-- "diverge" opera a comparação pedida pelo enunciado entre a taxa de
-- vitórias observada e o multiplicador da matriz de efetividade: TRUE
-- quando o sinal do multiplicador (>1, =1, <1) não corresponde ao sinal da
-- taxa de vitórias observada (>0.5, ~0.5, <0.5) — ver README.md.
CREATE TABLE IF NOT EXISTS gold.matriz_confronto (
    tipo_atacante            TEXT NOT NULL,
    tipo_defensor            TEXT NOT NULL,
    combates                 INT NOT NULL,
    vitorias_atacante        INT NOT NULL,
    taxa_vitorias_atacante   NUMERIC(6,4) NOT NULL,
    multiplicador_matriz     NUMERIC(3,2) NOT NULL,
    diverge                  BOOLEAN NOT NULL,
    PRIMARY KEY (tipo_atacante, tipo_defensor)
);

-- Análise 8 (proposta pelo grupo) — efeito de atacar primeiro sobre a taxa
-- de vitórias, por geração de introdução do combatente.
-- Capacidade exigida que as análises 3 a 7 não exigem: cruza uma dimensão
-- não utilizada por nenhuma das sete análises obrigatórias (dim_geracao,
-- ligada apenas à fato) com um atributo da própria fato quase não
-- explorado pelas demais (atacou_primeiro) — grão distinto (geração x
-- ordem de ataque), ver README.md.
CREATE TABLE IF NOT EXISTS gold.taxa_vitorias_geracao_ataque (
    geracao         INT NOT NULL,
    atacou_primeiro BOOLEAN NOT NULL,
    combates        INT NOT NULL,
    vitorias        INT NOT NULL,
    taxa_vitorias   NUMERIC(6,4) NOT NULL,
    PRIMARY KEY (geracao, atacou_primeiro)
);

-- Metadado de orquestração (não é fato nem dimensão): a contagem de linhas
-- de cada tabela do gold e o momento da carga, exigidos por R8 e pela
-- distinção feita na seção 5.1 entre "um arquivo SQL" e "uma etapa de
-- pipeline que verifica o próprio resultado".
CREATE TABLE IF NOT EXISTS gold._log_carga (
    tabela          TEXT NOT NULL,
    linhas          INT NOT NULL,
    carregado_em    TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tabela, carregado_em)
);
