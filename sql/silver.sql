-- silver.sql — DDL do modelo dimensional da camada silver.
--
-- Executado por carregar.py (R6, R7). Todos os comandos usam
-- IF NOT EXISTS / CREATE SCHEMA IF NOT EXISTS para que a reexecução seja
-- idempotente: comandos CREATE só produzem efeito na primeira execução, e
-- carregar.py é responsável por repovoar sem duplicar (ver o próprio script).
--
-- Grão da tabela fato (decisão 1 da seção 4.2, justificada no README.md):
--   uma linha por PARTICIPAÇÃO em um combate (100.000 linhas para 50.000
--   combates). Cada combate do combats.csv gera duas linhas em
--   silver.fato_confronto: uma do ponto de vista de First_pokemon, outra do
--   ponto de vista de Second_pokemon.
--
-- Esquema estrela (RS2): as três dimensões (dim_pokemon, dim_tipo,
-- dim_geracao) ligam-se diretamente à fato, e a nenhuma outra dimensão.
-- Em particular, dim_pokemon NÃO referencia dim_tipo (isso seria
-- snowflake): o tipo primário e secundário de cada Pokémon aparece em
-- dim_pokemon apenas como texto denormalizado (para as análises 1 e 2,
-- que leem exclusivamente as dimensões — RS6). Quando um tipo precisa ser
-- uma chave substituta consultável (para a matriz de efetividade, RS7),
-- ele aparece como coluna própria na fato, referenciando dim_tipo
-- diretamente — inclusive em papéis repetidos (dimensão papel, RS3/decisão 4
-- aplicada também ao tipo).

CREATE SCHEMA IF NOT EXISTS silver;

-- ─────────────────────────── DIMENSÕES ───────────────────────────

CREATE TABLE IF NOT EXISTS silver.dim_geracao (
    geracao_key     SERIAL PRIMARY KEY,
    numero_geracao  INT NOT NULL UNIQUE,   -- 1 a 6 (chave natural do CSV/PokéAPI)
    nome_geracao    TEXT NOT NULL,
    regiao          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS silver.dim_tipo (
    tipo_key    SERIAL PRIMARY KEY,
    nome_tipo   TEXT NOT NULL UNIQUE,      -- chave natural (nome do tipo), nunca PK/FK
    id_pokeapi  INT UNIQUE                 -- NULL apenas para o membro especial abaixo
);

-- Membro especial de dim_tipo (RS4): representa a ausência de um segundo
-- tipo. Evita chave estrangeira nula em fato_confronto.tipo_2_key e
-- .tipo_oponente_2_key sempre que o Pokémon é de tipo único.
-- (o INSERT vive em carregar.py, não aqui, porque o restante do conteúdo
--  de dim_tipo depende dos 18 tipos obtidos da PokéAPI na bronze.)

CREATE TABLE IF NOT EXISTS silver.dim_pokemon (
    pokemon_key            SERIAL PRIMARY KEY,

    -- chaves naturais das duas fontes: nunca PK/FK, apenas atributos
    -- auditáveis da conciliação (RS3, R4).
    numero_csv              INT NOT NULL UNIQUE,   -- campo "#" do pokemon.csv
    numero_pokedex          INT,                    -- id de /pokemon-species/; NULL se não conciliado

    nome                    TEXT,
    nome_desconhecido       BOOLEAN NOT NULL DEFAULT FALSE,  -- Problema 2 (seção 1.4): dado ausente
    conciliado              BOOLEAN NOT NULL DEFAULT TRUE,   -- FALSE = não foi possível casar com a PokéAPI (R4)

    is_forma_alternativa    BOOLEAN NOT NULL DEFAULT FALSE,
    forma_slug              TEXT,                   -- ex. "charizard-mega-x"; NULL para a forma padrão

    -- atributos herdados da espécie (forma alternativa herda da espécie-mãe;
    -- procedimento descrito no README.md)
    geracao                 INT NOT NULL,           -- sempre disponível: vem do CSV (coluna Generation)
    habitat                 TEXT,                   -- NULL genuíno = dado não coletado;
                                                     -- 'não se aplica' = Problema 3 (conceito inaplicável)
    cor                     TEXT,
    forma_corporal          TEXT,
    taxa_captura             INT,
    felicidade_base          INT,
    taxa_crescimento         TEXT,
    quantidade_habilidades   INT,
    categoria_raridade       TEXT NOT NULL DEFAULT 'comum',  -- derivada na carga (decisão 6)

    -- tipo: denormalizado como texto (RS2 — evita snowflake); ver fato_confronto
    -- para a versão em chave substituta usada pela efetividade de tipos.
    tipo_1                  TEXT NOT NULL,
    tipo_2                  TEXT NOT NULL DEFAULT 'Nenhum',

    -- atributos de status (decisão 5): residem aqui como cadastro do Pokémon;
    -- a única duplicação para a fato é a diferença de velocidade (decisão 2),
    -- que é a única métrica de status efetivamente usada por uma análise de
    -- combate (análise 5).
    hp                       INT,
    ataque                   INT,
    defesa                   INT,
    ataque_especial          INT,
    defesa_especial          INT,
    velocidade               INT,

    altura                   INT,   -- decímetros, como retornado pela PokéAPI
    peso                     INT,   -- hectogramas, como retornado pela PokéAPI
    experiencia_base         INT
);

-- ─────────────────────── EFETIVIDADE DE TIPOS ───────────────────────
-- Materialização de damage_relations (RS7): tabela ponte de 18x18 = 324
-- linhas, restrita aos 18 tipos reais do jogo (decisão do grupo, seção 1.1:
-- stellar/unknown/shadow são descartados aqui porque não existem no
-- programa que gerou os dados de batalha — justificado no README.md).
CREATE TABLE IF NOT EXISTS silver.efetividade_tipo (
    tipo_atacante_key   INT NOT NULL REFERENCES silver.dim_tipo(tipo_key),
    tipo_defensor_key   INT NOT NULL REFERENCES silver.dim_tipo(tipo_key),
    multiplicador       NUMERIC(3,2) NOT NULL,  -- 0, 0.5, 1 ou 2
    PRIMARY KEY (tipo_atacante_key, tipo_defensor_key)
);

-- ─────────────────────────────── FATO ───────────────────────────────
-- Grão: uma participação de um Pokémon em um combate (decisão 1).
-- Toda chave estrangeira referencia uma linha existente (RS5); a ausência
-- de segundo tipo é resolvida pelo membro especial de dim_tipo (RS4), e o
-- registro #63 sem nome permanece em dim_pokemon com nome_desconhecido =
-- TRUE, de modo que nenhum combate é descartado (R5).
CREATE TABLE IF NOT EXISTS silver.fato_confronto (
    confronto_key           BIGSERIAL PRIMARY KEY,

    combate_id               INT NOT NULL,     -- dimensão degenerada: linha de combats.csv (1..50000)

    pokemon_key               INT NOT NULL REFERENCES silver.dim_pokemon(pokemon_key),
    oponente_key              INT NOT NULL REFERENCES silver.dim_pokemon(pokemon_key), -- dimensão papel (decisão 4)

    geracao_key                INT NOT NULL REFERENCES silver.dim_geracao(geracao_key), -- geração do combatente desta linha

    tipo_1_key                 INT NOT NULL REFERENCES silver.dim_tipo(tipo_key), -- meu tipo primário
    tipo_2_key                 INT NOT NULL REFERENCES silver.dim_tipo(tipo_key), -- meu tipo secundário (ou membro especial)
    tipo_oponente_1_key        INT NOT NULL REFERENCES silver.dim_tipo(tipo_key),
    tipo_oponente_2_key        INT NOT NULL REFERENCES silver.dim_tipo(tipo_key),

    atacou_primeiro             BOOLEAN NOT NULL,  -- TRUE se este Pokémon é o First_pokemon do combate
    venceu                      SMALLINT NOT NULL CHECK (venceu IN (0, 1)),  -- métrica aditiva (RS6): AVG(venceu) = taxa de vitórias
    diferenca_velocidade        INT NOT NULL,      -- minha velocidade - velocidade do oponente (decisão 2)

    UNIQUE (combate_id, pokemon_key)
);

CREATE INDEX IF NOT EXISTS idx_fato_confronto_pokemon   ON silver.fato_confronto (pokemon_key);
CREATE INDEX IF NOT EXISTS idx_fato_confronto_oponente  ON silver.fato_confronto (oponente_key);
CREATE INDEX IF NOT EXISTS idx_fato_confronto_tipos     ON silver.fato_confronto (tipo_1_key, tipo_oponente_1_key);

-- Observação sobre silver.log_conciliacao (seção 4.3): o grupo optou pela
-- forma preferida do requisito R4 — o arquivo conciliacao.csv, versionado
-- na raiz do repositório — e por isso esta tabela não é criada aqui. Veja
-- a justificativa no README.md.
