-- consultas.sql — as oito análises da seção 7.
--
-- Análises 1 e 2: leitura direta de silver.dim_pokemon (cadastro), sem
-- tocar a fato — RS6 as exclui explicitamente da agregação sobre batalhas,
-- já que cada Pokémon participa de ~125 combates e agregar pela fato
-- introduziria dupla contagem.
--
-- Análises 3 a 7 e a proposta pelo grupo (8): leitura direta de tabelas do
-- schema gold, já agregadas no grão da pergunta. Apenas WHERE, ORDER BY e
-- LIMIT são usados sobre elas — nunca GROUP BY, função de agregação ou
-- junção com o silver (seção 5 / R9).


-- ═══════════════════════════════════════════════════════════════════════
-- Análise 1 — Quantidade de Pokémon por tipo primário e por geração,
-- em matriz de tipo por geração.
-- ═══════════════════════════════════════════════════════════════════════
SELECT
    tipo_1                                          AS tipo_primario,
    COUNT(*) FILTER (WHERE geracao = 1)              AS geracao_i,
    COUNT(*) FILTER (WHERE geracao = 2)              AS geracao_ii,
    COUNT(*) FILTER (WHERE geracao = 3)              AS geracao_iii,
    COUNT(*) FILTER (WHERE geracao = 4)              AS geracao_iv,
    COUNT(*) FILTER (WHERE geracao = 5)              AS geracao_v,
    COUNT(*) FILTER (WHERE geracao = 6)              AS geracao_vi,
    COUNT(*)                                         AS total
FROM silver.dim_pokemon
GROUP BY tipo_1
ORDER BY tipo_1;


-- ═══════════════════════════════════════════════════════════════════════
-- Análise 2 — Média de cada atributo de status por tipo primário.
-- "Resistência" é lida aqui como a média de (defesa + defesa_especial) / 2.
-- ═══════════════════════════════════════════════════════════════════════
SELECT
    tipo_1                                           AS tipo_primario,
    ROUND(AVG(hp), 1)                                AS hp_medio,
    ROUND(AVG(ataque), 1)                            AS ataque_medio,
    ROUND(AVG(defesa), 1)                            AS defesa_media,
    ROUND(AVG(ataque_especial), 1)                   AS ataque_especial_medio,
    ROUND(AVG(defesa_especial), 1)                   AS defesa_especial_media,
    ROUND(AVG(velocidade), 1)                        AS velocidade_media,
    ROUND(AVG((defesa + defesa_especial) / 2.0), 1)  AS resistencia_media
FROM silver.dim_pokemon
GROUP BY tipo_1
ORDER BY velocidade_media DESC;

-- Consulta auxiliar da análise 2: verifica se algum tipo tem desempenho
-- superior EM TODOS os seis atributos (dominância). Um tipo dominante
-- aparece em primeiro lugar (posicao = 1) nas seis linhas produzidas por
-- este UNION ALL.
WITH medias AS (
    SELECT
        tipo_1 AS tipo_primario,
        AVG(hp) AS hp_medio, AVG(ataque) AS ataque_medio,
        AVG(defesa) AS defesa_media, AVG(ataque_especial) AS ataque_especial_medio,
        AVG(defesa_especial) AS defesa_especial_media, AVG(velocidade) AS velocidade_media
    FROM silver.dim_pokemon
    GROUP BY tipo_1
),
posicoes AS (
    SELECT tipo_primario, 'hp' AS atributo, RANK() OVER (ORDER BY hp_medio DESC) AS posicao FROM medias
    UNION ALL
    SELECT tipo_primario, 'ataque', RANK() OVER (ORDER BY ataque_medio DESC) FROM medias
    UNION ALL
    SELECT tipo_primario, 'defesa', RANK() OVER (ORDER BY defesa_media DESC) FROM medias
    UNION ALL
    SELECT tipo_primario, 'ataque_especial', RANK() OVER (ORDER BY ataque_especial_medio DESC) FROM medias
    UNION ALL
    SELECT tipo_primario, 'defesa_especial', RANK() OVER (ORDER BY defesa_especial_media DESC) FROM medias
    UNION ALL
    SELECT tipo_primario, 'velocidade', RANK() OVER (ORDER BY velocidade_media DESC) FROM medias
)
SELECT tipo_primario, COUNT(*) FILTER (WHERE posicao = 1) AS vezes_em_primeiro
FROM posicoes
GROUP BY tipo_primario
ORDER BY vezes_em_primeiro DESC, tipo_primario;
-- Um tipo com vezes_em_primeiro = 6 é dominante em todos os atributos.


-- ═══════════════════════════════════════════════════════════════════════
-- Análise 3 — Taxa de vitórias por Pokémon (dez maiores e dez menores).
-- Corte mínimo de combates: 100 (aproximadamente 800 combates médios por
-- Pokémon esperados sobre 100.000 participações / ~800 Pokémon ~= 125;
-- 100 exclui apenas os poucos casos claramente sub-representados sem
-- descartar boa parte da amostra — justificado no README.md).
-- ═══════════════════════════════════════════════════════════════════════
(
    SELECT nome, tipo_1, tipo_2, combates, taxa_vitorias
    FROM gold.ranking_pokemon
    WHERE combates >= 100
    ORDER BY taxa_vitorias DESC, combates DESC
    LIMIT 10
)
UNION ALL
(
    SELECT nome, tipo_1, tipo_2, combates, taxa_vitorias
    FROM gold.ranking_pokemon
    WHERE combates >= 100
    ORDER BY taxa_vitorias ASC, combates DESC
    LIMIT 10
);


-- ═══════════════════════════════════════════════════════════════════════
-- Análise 4 — Taxa de vitórias por tipo primário, ordenada.
-- ═══════════════════════════════════════════════════════════════════════
SELECT tipo, combates, vitorias, taxa_vitorias
FROM gold.taxa_vitorias_por_tipo
ORDER BY taxa_vitorias DESC;


-- ═══════════════════════════════════════════════════════════════════════
-- Análise 5 — Relação entre diferença de velocidade e vitória.
-- ═══════════════════════════════════════════════════════════════════════
SELECT faixa, combates, vitorias, taxa_vitorias
FROM gold.taxa_vitorias_por_faixa_velocidade
ORDER BY ordem;


-- ═══════════════════════════════════════════════════════════════════════
-- Análise 6 — Relação entre vantagem de tipo e vitória (multiplicador
-- combinado dos dois tipos do oponente — decisão 3 da seção 4.2).
-- ═══════════════════════════════════════════════════════════════════════
SELECT multiplicador, combates, vitorias, taxa_vitorias
FROM gold.taxa_vitorias_por_multiplicador
ORDER BY multiplicador;


-- ═══════════════════════════════════════════════════════════════════════
-- Análise 7 — Matriz de confronto entre tipos (18 x 18), com as posições
-- em que a taxa de vitórias observada diverge do multiplicador da matriz.
-- ═══════════════════════════════════════════════════════════════════════
SELECT tipo_atacante, tipo_defensor, combates, taxa_vitorias_atacante,
       multiplicador_matriz, diverge
FROM gold.matriz_confronto
ORDER BY tipo_atacante, tipo_defensor;

-- Só as posições divergentes:
SELECT tipo_atacante, tipo_defensor, combates, taxa_vitorias_atacante, multiplicador_matriz
FROM gold.matriz_confronto
WHERE diverge = TRUE
ORDER BY tipo_atacante, tipo_defensor;


-- ═══════════════════════════════════════════════════════════════════════
-- Análise 8 (proposta pelo grupo) — Efeito de atacar primeiro sobre a
-- taxa de vitórias, por geração de introdução do combatente.
-- Pergunta de negócio: "o benefício de atacar primeiro é uniforme entre as
-- gerações, ou pokémon de gerações mais recentes (com status mais altos
-- em média) dependem menos da ordem de ataque para vencer?"
-- ═══════════════════════════════════════════════════════════════════════
SELECT geracao, atacou_primeiro, combates, vitorias, taxa_vitorias
FROM gold.taxa_vitorias_geracao_ataque
ORDER BY geracao, atacou_primeiro DESC;
