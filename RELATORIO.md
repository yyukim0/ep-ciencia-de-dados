# RELATORIO.md — Resultados e interpretação das análises

> ⚠️ **Status: resultados PENDENTES.** O pipeline ainda não foi executado contra dados reais. Cada resultado abaixo está marcado como `PENDENTE` e deve ser preenchido com a **saída real** de `sql/consultas.sql`. Nenhum número foi inventado, e as interpretações só devem ser concluídas depois de colar os resultados. Os trechos "Como ler" e "Verificações" indicam **o que checar**, não o que os dados mostram.

**Como gerar os resultados** (após `extrair.py`, `carregar.py` e `publicar.py`):

```powershell
psql "postgresql://postgres:postgres@localhost:5432/pokedex" -f sql/consultas.sql
```

Cole cada saída na tabela correspondente (ou use captura de tela).

**Verificações globais antes de interpretar** (valores de referência do enunciado):

| Verificação | Consulta | Esperado | Obtido |
|---|---|---|---|
| Combates na bronze | `db.combates.countDocuments({})` | 50.000 | PENDENTE |
| Linhas em `silver.fato_confronto` | `SELECT COUNT(*) FROM silver.fato_confronto;` | 100.000 (2 por combate) | PENDENTE |
| Combates distintos na fato | `SELECT COUNT(DISTINCT combate_id) FROM silver.fato_confronto;` | 50.000 | PENDENTE |
| Linhas em `silver.dim_pokemon` | `SELECT COUNT(*) FROM silver.dim_pokemon;` | ~800 | PENDENTE |
| Tipos reais em `silver.dim_tipo` | `SELECT COUNT(*) FROM silver.dim_tipo;` | 18 + 1 membro especial | PENDENTE |
| Linhas em `silver.efetividade_tipo` | `SELECT COUNT(*) FROM silver.efetividade_tipo;` | 324 | PENDENTE |
| Registros conciliados | `conciliacao.csv`, coluna `status` | PENDENTE (registrar quantos e quais não conciliaram) | PENDENTE |

---

## Análise 1 — Quantidade de Pokémon por tipo primário e por geração

**Pergunta:** quantos Pokémon existem em cada combinação de tipo primário e geração? *(verificação de consistência do cadastro)*

**Resultado:** PENDENTE

| tipo_primario | geracao_i | geracao_ii | geracao_iii | geracao_iv | geracao_v | geracao_vi | total |
|---|---|---|---|---|---|---|---|
| PENDENTE | | | | | | | |

**Verificações:**
- a soma da coluna `total` deve ser igual ao número de linhas de `dim_pokemon` (~800);
- a soma por geração inclui as formas alternativas (Mega etc.), herdadas da geração do CSV;
- tipos com contagem muito abaixo do esperado sugerem falha de conciliação; cruzar com `conciliacao.csv`.

**Interpretação:** PENDENTE. *(Comentar se a distribuição confere com a esperada e se a conciliação afetou algum tipo ou geração.)*

---

## Análise 2 — Média de cada atributo de status por tipo primário

**Pergunta:** qual tipo tem maior velocidade média, qual tem maior resistência média, e existe tipo superior em todos os atributos?

**Resultado:** PENDENTE

| tipo_primario | hp_medio | ataque_medio | defesa_media | ataque_especial_medio | defesa_especial_media | velocidade_media | resistencia_media |
|---|---|---|---|---|---|---|---|
| PENDENTE | | | | | | | |

- **Tipo de maior velocidade média:** PENDENTE
- **Tipo de maior resistência média:** PENDENTE (definida no projeto como a média de `(defesa + defesa_especial) / 2`)
- **Existe tipo dominante em todos os atributos?** PENDENTE (consulta auxiliar `vezes_em_primeiro`; um tipo com valor 6 seria dominante nos seis atributos)

**Como ler:** a análise é calculada em `dim_pokemon` (cada Pokémon conta uma vez), não sobre a fato, para evitar ponderação pelo número de combates.

**Interpretação:** PENDENTE.

---

## Análise 3 — Taxa de vitórias por Pokémon (dez maiores e dez menores)

**Pergunta:** quais Pokémon têm as maiores e as menores taxas de vitórias, com amostra suficiente?

**Distribuição de `combates` (para justificar o corte):** PENDENTE

```sql
SELECT MIN(combates),
       percentile_cont(0.05) WITHIN GROUP (ORDER BY combates) AS p05,
       percentile_cont(0.50) WITHIN GROUP (ORDER BY combates) AS mediana,
       MAX(combates),
       COUNT(*) FILTER (WHERE combates < 100) AS abaixo_de_100
FROM gold.ranking_pokemon;
```

| min | p05 | mediana | max | abaixo de 100 |
|---|---|---|---|---|
| PENDENTE | | | | |

**Corte mínimo adotado:** 100 combates (provisório). **Justificativa:** PENDENTE. *(Confirmar ou substituir pelo valor que a distribuição acima recomendar, e explicar quantos Pokémon o corte exclui.)*

**Dez maiores:**

| nome | tipo_1 | tipo_2 | combates | taxa_vitorias |
|---|---|---|---|---|
| PENDENTE | | | | |

**Dez menores:**

| nome | tipo_1 | tipo_2 | combates | taxa_vitorias |
|---|---|---|---|---|
| PENDENTE | | | | |

**Como ler:** a taxa é ininterpretável sem o denominador (seção 1.3 do enunciado), por isso `combates` acompanha cada linha. Verificar se algum registro do topo ou da base é uma forma alternativa ou o registro sem nome, e comparar seus status base com o resultado.

**Interpretação:** PENDENTE.

---

## Análise 4 — Taxa de vitórias por tipo primário

**Pergunta:** existe tipo primário dominante em taxa de vitórias?

**Resultado:** PENDENTE

| tipo | combates | vitorias | taxa_vitorias |
|---|---|---|---|
| PENDENTE | | | |

**Verificações:**
- a soma de `combates` das 18 linhas deve ser 100.000 (todas as participações);
- a soma de `vitorias` deve ser 50.000 (cada combate tem um vencedor);
- **existe tipo dominante?** PENDENTE.

**Interpretação:** PENDENTE. *(Relacionar com a análise 2: tipos com status base mais altos vencem mais? Há tipos com bom status e baixa taxa, ou o contrário?)*

---

## Análise 5 — Diferença de velocidade e vitória

**Pergunta:** a taxa de vitórias cresce com a vantagem de velocidade?

**Faixas adotadas:** `≤ −50`, `−49 a −1`, `0`, `1 a 49`, `≥ 50` (cinco faixas simétricas). **Justificativa dos cortes:** PENDENTE. *(Confirmar contra a distribuição real de `diferenca_velocidade` e ajustar o `CASE` em `publicar.py` se necessário.)*

**Resultado:** PENDENTE

| faixa | combates | vitorias | taxa_vitorias |
|---|---|---|---|
| PENDENTE | | | |

**Verificações de sanidade (decorrem do grão por participação; se falharem, há erro de carga):**
- a faixa `0` deve ter taxa **exatamente 0,5**;
- as faixas espelhadas (`≤ −50` e `≥ 50`; `−49 a −1` e `1 a 49`) devem ter o **mesmo número de combates** e taxas que **somam 1**.

**Interpretação:** PENDENTE. *(A taxa cresce de forma monotônica? A magnitude do efeito é grande ou pequena? Lembrar que os resultados vêm de um simulador.)*

---

## Análise 6 — Vantagem de tipo e vitória

**Pergunta:** multiplicadores de efetividade maiores que 1 correspondem a taxas de vitórias maiores?

**Critério adotado (decisão 3):** multiplicador **combinado dos dois tipos do oponente**, com o tipo primário do Pokémon da linha como atacante; valores possíveis 0, 0,25, 0,5, 1, 2 e 4.

**Resultado:** PENDENTE

| multiplicador | combates | vitorias | taxa_vitorias |
|---|---|---|---|
| PENDENTE | | | |

**Verificações:**
- a soma de `combates` deve ser 100.000;
- conferir quais multiplicadores aparecem de fato (podem faltar valores raros, como 0 ou 0,25).

**Como ler:** o enunciado afirma que um resultado sem efeito de tipo, se corretamente apurado, é uma resposta válida, pois as batalhas são simuladas e o programa pode não ter usado a tabela de tipos.

**Interpretação:** PENDENTE. *(Registrar o que os dados mostram, seja um efeito claro ou a ausência dele, e a amostra de cada multiplicador.)*

---

## Análise 7 — Matriz de confronto entre tipos (18×18)

**Pergunta:** em quais pares de tipos a taxa de vitórias do atacante diverge do multiplicador da matriz de efetividade?

**Resultado completo:** PENDENTE. *(324 linhas são extensas demais para esta tabela; anexar a saída em arquivo, por exemplo `resultados/analise7_matriz.csv`, ou captura de tela.)*

**Definição de divergência:** `multiplicador > 1` com `taxa ≤ 0,5`, ou `multiplicador < 1` com `taxa ≥ 0,5`. Posições com multiplicador 1 não divergem por definição.

**Posições divergentes (`diverge = TRUE`):** PENDENTE

| tipo_atacante | tipo_defensor | combates | taxa_vitorias_atacante | multiplicador_matriz |
|---|---|---|---|---|
| PENDENTE | | | | |

**Verificações:**
- `COUNT(*)` da tabela: até 324 (pares sem combates não aparecem); registrar o valor obtido;
- para cada par A≠B, `taxa(A,B) + taxa(B,A) = 1` e o número de combates é igual;
- a diagonal (A,A) deve ter taxa **exatamente 0,5**.

**Interpretação:** PENDENTE. *(Quantas das posições divergem? A divergência se concentra em pares com poucos combates (ruído) ou também em pares bem amostrados (evidência de que o simulador não usa a tabela de tipos)? Comparar com a análise 6.)*

---

## Análise 8 (proposta pelo grupo) — Efeito de atacar primeiro por geração

**Pergunta de negócio (formulada antes da consulta):** o benefício de atacar primeiro é uniforme entre as gerações, ou varia conforme a geração de introdução do combatente?

**Capacidade exigida do modelo:** `dim_geracao` ligada à fato, cruzada com `atacou_primeiro` (ver `README.md`, seção 6).

**Resultado:** PENDENTE

| geracao | atacou_primeiro | combates | vitorias | taxa_vitorias |
|---|---|---|---|---|
| PENDENTE | | | | |

**Verificações:**
- 12 linhas (6 gerações × 2 valores de `atacou_primeiro`);
- a soma de `combates` com `atacou_primeiro = TRUE` deve ser 50.000, e igualmente com `FALSE`;
- a soma total de `vitorias` deve ser 50.000.

**Como ler:** a geração é a do combatente da linha e o oponente pode ser de outra geração; por isso, dentro de uma geração, as taxas de `TRUE` e `FALSE` **não** são complementares. Comparar a diferença entre as duas taxas de cada geração, e não o valor absoluto.

**Interpretação:** PENDENTE. *(A diferença entre atacar primeiro e depois é estável entre gerações ou varia? Relacionar com a hipótese sobre amplitude de status por geração e com o resultado da análise 5: se velocidade e ordem de ataque forem independentes no simulador, comentar.)*
