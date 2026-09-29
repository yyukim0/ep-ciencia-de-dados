# EP01 — ETL e Arquitetura Medalhão: Pokédex + Batalhas

**Integrantes do grupo:**
   - Kauê Ibiapino
   - Danilo Yamamoto

**Declaração de uso de IA generativa:** o readme e as explicações do código foram feitos com o auxilio do claude

---

## 1. Visão geral

Pipeline de dados em arquitetura medalhão que combina duas fontes de naturezas opostas: a **PokéAPI** (JSON aninhado, descreve *o que as entidades são*) e o par de CSVs **pokemon.csv / combats.csv** (arquivos planos, descrevem *o que ocorreu*: 50.000 batalhas simuladas).

| Camada | Tecnologia | Banco / schema | Script | Conteúdo |
|---|---|---|---|---|
| 🥉 Bronze | MongoDB | `pokedex_bronze` | `extrair.py` | resposta bruta das fontes, com linhagem |
| 🥈 Silver | PostgreSQL | schema `silver` | `carregar.py` | esquema estrela, chaves conciliadas |
| 🥇 Gold | PostgreSQL | schema `gold` | `publicar.py` | agregados no grão de cada análise |

Cada script lê apenas da camada anterior e escreve apenas na seguinte. Nenhum script importa `pandas` ou equivalente (R11).

Estrutura do repositório:

```
├── README.md            ├── sql/silver.sql      (DDL do esquema estrela)
├── RELATORIO.md         ├── sql/gold.sql        (DDL das tabelas agregadas)
├── requirements.txt     ├── sql/consultas.sql   (as 8 análises)
├── extrair.py           ├── conciliacao.csv     (gerado por carregar.py, R4)
├── carregar.py          └── dados_brutos/       (cache local, no .gitignore)
└── publicar.py
```

---

## 2. Procedimento de execução

### 2.1 Bancos de dados

Escolha **uma** das opções.

**Docker (recomendado):**
```powershell
docker run -d --name mongo-bronze -p 27017:27017 mongo:7
docker run -d --name postgres-pg -p 5432:5432 -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=pokedex postgres:16
docker ps    # os dois contêineres devem estar "Up"
```
Se os contêineres já existirem: `docker start mongo-bronze postgres-pg`.

**Instalação local (Windows):** MongoDB Community Server (instalar como serviço, porta 27017) e PostgreSQL (anotar a senha do usuário `postgres`); depois `psql -U postgres -c "CREATE DATABASE pokedex;"`.

**Máquina virtual da disciplina:** apontar `MONGO_URI` e `POSTGRES_DSN` para o IP da VM.

### 2.2 Ambiente Python

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -c "import psycopg; print(psycopg.pq.__impl__)"   # deve imprimir: binary
```

> O driver deve ser instalado como `psycopg[binary]`. Sem o extra `binary`, o `psycopg` exige a biblioteca `libpq` do sistema (comum de faltar no Windows). Em versões muito novas do Python pode não haver *wheel* binário; nesse caso usar Python 3.12 ou 3.13.

`requirements.txt` (exatamente o que o pipeline usa):
```
requests
pymongo
psycopg[binary]
```

### 2.3 Variáveis de ambiente

Valores-padrão dos scripts, caso as variáveis não sejam definidas:

| Variável | Padrão |
|---|---|
| `MONGO_URI` | `mongodb://localhost:27017` |
| `POSTGRES_DSN` | `dbname=pokedex user=postgres host=localhost` |
| `POKEAPI_BASE` | `https://pokeapi.co/api/v2` |

Com o PostgreSQL do Docker acima (que exige senha):
```powershell
$env:POSTGRES_DSN = "dbname=pokedex user=postgres password=postgres host=localhost"
```

### 2.4 Ordem de execução

Sempre a partir da raiz do repositório (os caminhos `sql/...` são relativos):

```powershell
python extrair.py     # fontes -> bronze   (1ª execução: dezenas de minutos, por causa das requisições à API)
python carregar.py    # bronze -> silver   (gera também conciliacao.csv)
python publicar.py    # silver -> gold
psql "postgresql://postgres:postgres@localhost:5432/pokedex" -f sql/consultas.sql
```

`carregar.py` não faz requisições de rede: lê exclusivamente do MongoDB (não importa `requests`). Portanto roda sem internet, desde que a bronze esteja populada.

---

## 3. Por que MongoDB na camada bronze

Os endpoints `/pokemon/{id}` e `/pokemon-species/{id}` devolvem JSON aninhado e heterogêneo:

- `stats[]`, `types[]` e `abilities[]` são **listas de objetos** cujo elemento contém outro objeto: por exemplo, cada item de `stats[]` traz `base_stat` e um sub-objeto `stat: {name, url}`. Em tabela relacional, cada lista viraria uma tabela filha, ou seja, uma **modelagem antecipada**, que já é transformação e é vedada na bronze.
- `habitat`, `color`, `shape` e `growth_rate` são **referências aninhadas** `{name, url}`, e `habitat` pode ser `null` por razões de domínio (Problema 3), não por falha de coleta.
- `varieties[]` em `/pokemon-species/` lista as formas alternativas com estrutura própria; `/type/{id}` traz `damage_relations` com **seis listas** de comprimento variável.
- O formato de um documento pode mudar entre registros e ao longo do tempo (a API é mantida por voluntários). Um esquema rígido a priori quebraria a carga; um documento aceita o que a fonte entrega.

Um banco de documentos armazena a resposta **exatamente como veio** (requisito central da bronze), sem esquema prévio, e o `_id` derivado da chave natural (`pokemon/25`) dá o upsert idempotente exigido por R3. As duas fontes CSV não exigiriam banco de documentos por si; ficam no mesmo banco por uniformidade da camada (`pokedex_bronze`, cinco coleções).

Coleções: `pokemon`, `especies` (721), `tipos` (21), `pokemon_csv` (800), `combates` (50.000).

**Linhagem.** Todo documento carrega `_fonte`, `_url` e `_ingerido_em` (e `_linha_csv` nos combates), em campos prefixados para não colidir com os da fonte. Todos os valores dos CSVs são mantidos como **texto** na bronze; a conversão numérica ocorre no silver.

**Escopo da extração.** `extrair.py` percorre as 721 espécies e, para cada uma, extrai **todas** as formas listadas em `varieties[]` a partir de `/pokemon/{nome}`. As formas alternativas têm id > 10000 e não existem em `/pokemon-species/`, então uma iteração de 1 a 721 não as alcançaria. Os 21 tipos são extraídos integralmente; o filtro é feito no silver, não na bronze.

> Observação: como `varieties[]` lista todas as formas de cada espécie, a coleção `pokemon` pode conter **mais** documentos do que as 800 linhas do `pokemon.csv` (por exemplo, formas regionais). Só as que casam por nome com o CSV entram no `dim_pokemon`; as demais permanecem intactas na bronze.

---

## 4. Modelo dimensional (silver)

### 4.1 Grão

> **Cada linha de `silver.fato_confronto` representa a participação de um Pokémon em um combate, do ponto de vista desse Pokémon.** Um combate do `combats.csv` gera exatamente duas linhas (uma para cada combatente); 50.000 combates produzem 100.000 linhas.

### 4.2 Diagrama

```
                        ┌───────────────────┐
                        │    dim_geracao    │
                        │    (6 linhas)     │
                        └─────────┬─────────┘
                                  │ geracao_key
 ┌────────────────────┐   ┌───────┴─────────┐   ┌─────────────────────────┐
 │    dim_pokemon     │   │                 │   │        dim_tipo         │
 │  (~800 linhas)     ├───┤ fato_confronto  ├───┤  (18 tipos + membro     │
 │  papéis: "eu" e    │   │ (100.000 linhas)│   │   especial "Nenhum")    │
 │  "oponente"        │   │                 │   │  papéis: meu tipo 1/2   │
 │  pokemon_key       │   │ venceu          │   │  e tipo 1/2 do oponente │
 │  oponente_key      │   │ diferenca_veloc.│   │  (4 chaves na fato)     │
 └────────────────────┘   │ atacou_primeiro │   └────────────┬────────────┘
                          │ combate_id (DD) │                │
                          └─────────────────┘                │
                                                   ┌─────────┴───────────┐
                                                   │  efetividade_tipo   │
                                                   │  (324 linhas)       │
                                                   │  tabela ponte       │
                                                   │  atacante x defensor│
                                                   └─────────────────────┘
```

- `combate_id` é **dimensão degenerada** (número da linha em `combats.csv`).
- `efetividade_tipo` **não é FK da fato**: é tabela ponte entre duas chaves de `dim_tipo`, consultada por junção (RS7).
- Nenhuma dimensão referencia outra dimensão (RS2). `dim_pokemon` guarda `tipo_1` e `tipo_2` apenas como **texto denormalizado**, usado pelas análises de cadastro (1 e 2); a versão em chave substituta, necessária para a efetividade, vive só na fato.

### 4.3 Atendimento aos requisitos RS1–RS8

| Req. | Como é atendido |
|---|---|
| RS1 grão | Frase do grão em 4.1, declarada antes do DDL |
| RS2 estrela | Fato ligada diretamente a `dim_pokemon`, `dim_tipo`, `dim_geracao`; nenhuma dimensão aponta para outra |
| RS3 chaves substitutas | `pokemon_key`, `tipo_key`, `geracao_key` (`SERIAL`). `numero_csv` e `numero_pokedex` são **atributos** de `dim_pokemon`, nunca PK/FK |
| RS4 sem FK nula | Todas as FKs da fato são `NOT NULL`. Ausência de 2º tipo = membro especial `Nenhum` em `dim_tipo` (ver 4.5 sobre o registro sem nome) |
| RS5 integridade | `PRIMARY KEY` em todas as tabelas, `FOREIGN KEY` em todas as chaves da fato e da ponte, `CHECK (venceu IN (0,1))`, `UNIQUE (combate_id, pokemon_key)` |
| RS6 métricas aditivas | `venceu` (0/1) e `diferenca_velocidade` são numéricas; a taxa de vitórias é `AVG(venceu)` em qualquer agrupamento. Análises 1 e 2 leem só `dim_pokemon` |
| RS7 efetividade em SQL | `damage_relations` materializado em `silver.efetividade_tipo` (324 linhas), consumida por `JOIN` em `publicar.py` |
| RS8 suficiência | As análises leem só `silver` e `gold`; nenhuma acessa bronze, API ou CSV |

### 4.4 As seis decisões de modelagem (seção 4.2 do enunciado)

**Decisão 1 — Grão: uma linha por participação (100.000), não uma por combate (50.000).**
*Justificativa:* com uma linha por combate, localizar um Pokémon exige olhar duas colunas (`First_pokemon` e `Second_pokemon`) e tratar a vitória condicionalmente em cada uma, com risco de dupla contagem ou contagem incompleta. Com uma linha por participação, a taxa de vitórias de **qualquer** agrupamento (Pokémon, tipo, geração, faixa de velocidade) é apenas `AVG(venceu)`, como RS6 pede.
*Custo:* o dobro de linhas na fato e a duplicação, nas duas linhas de cada combate, dos atributos "do outro lado" (tipos e velocidade do oponente).
*Consequência de projeto:* como cada combate aparece uma vez como vitória e uma como derrota, a fato é simétrica por construção. Isso é usado como verificação de consistência no `RELATORIO.md`.

**Decisão 2 — Diferença de velocidade: gravada na fato (`diferenca_velocidade`), não calculada na consulta.**
*Justificativa:* `carregar.py` já tem os dois perfis em mãos ao montar cada linha; gravar `velocidade_meu − velocidade_oponente` deixa a análise 5 como um agrupamento direto sobre uma coluna numérica, sem auto-junção de `dim_pokemon` via `oponente_key` a cada consulta.
*Custo:* uma coluna a mais e a obrigação de recalculá-la quando a bronze é reprocessada, o que já ocorre porque a fato é reconstruída do zero a cada carga.

**Decisão 3 — Efetividade de tipos: tabela ponte de 324 linhas (18×18), com multiplicador do defensor de dois tipos calculado por dois `JOIN`s.**
*Justificativa:* a ponte reproduz o grão de `damage_relations` (RS7). O JSON lista só as exceções; `carregar.py` preenche as 324 combinações com **1,0** como padrão e sobrescreve com 2, 0,5 ou 0 conforme as listas `double_damage_to`, `half_damage_to` e `no_damage_to`. Para defensor com dois tipos, `publicar.py` junta a ponte duas vezes (`e1` para o tipo 1 do oponente, `e2` para o tipo 2) e calcula `e1.multiplicador * COALESCE(e2.multiplicador, 1)`. Oponente de tipo único aponta para o membro `Nenhum`, que **não existe** na ponte; o `LEFT JOIN` devolve `NULL` e o `COALESCE` aplica 1.
*Critério adotado na análise 6:* multiplicador **combinado dos dois tipos do oponente**, atacando com o **tipo primário** do Pokémon da linha; valores possíveis 0, 0,25, 0,5, 1, 2 e 4. O tipo secundário do atacante não é usado.
*Custo:* consultas com efetividade precisam de dois joins. Em contrapartida, a ponte é pequena e serve às análises 6 e 7. Pré-computar todos os pares (tipo1, tipo2) do defensor ou gravar o multiplicador na fato não traria ganho relevante nesta escala.

**Decisão 4 — Oponente: `dim_pokemon` referenciada duas vezes pela fato (`pokemon_key` e `oponente_key`).**
*Justificativa:* o oponente é a **mesma entidade em outro papel** (dimensão papel). Uma `dim_oponente` separada duplicaria as ~800 linhas e quebraria a dimensão conformada. O mesmo raciocínio vale para `dim_tipo`, referenciada quatro vezes (`tipo_1_key`, `tipo_2_key`, `tipo_oponente_1_key`, `tipo_oponente_2_key`).
*Custo:* consultas que precisam de atributos do oponente exigem aliases explícitos (`dim_pokemon AS eu`, `dim_pokemon AS oponente`). Não há custo de espaço.

**Decisão 5 — Atributos de status: em `dim_pokemon`; na fato, apenas a diferença de velocidade.**
*Justificativa:* HP, ataque, defesa, ataque especial, defesa especial e velocidade descrevem o Pokémon, não o combate. Em `dim_pokemon`, as análises 1 e 2 os leem sem risco de dupla contagem (cada Pokémon aparece em ~125 combates; a média por tipo calculada sobre a fato seria ponderada por combates disputados). A única comparação entre lados necessária às análises obrigatórias é a de velocidade (análise 5), e ela está na fato (decisão 2).
*Custo:* comparar outro atributo (por exemplo, ataque) entre os lados exigiria auto-junção de `dim_pokemon` via `oponente_key`. Duplicar os seis atributos dos dois lados na fato evitaria isso ao preço de doze colunas redundantes em 100.000 linhas.

**Decisão 6 — Categoria de raridade: derivada na carga (`categoria_raridade`), não por `CASE` em cada consulta.**
*Justificativa:* nenhuma fonte fornece categoria consolidada, só os booleanos `is_legendary`, `is_mythical` e `is_baby` (PokéAPI) e `Legendary` (CSV). `carregar.py` combina os três com precedência **mítico > lendário > bebê > comum**. A precedência é defensiva: na PokéAPI esses indicadores costumam ser mutuamente exclusivos. Para registros **não conciliados**, o único sinal disponível é `Legendary` do CSV, usado para separar `lendário` de `comum`.
*Custo:* mudar a regra exige reprocessar a silver (barato, pois a bronze é imutável). Em contrapartida, resolver por `CASE` em toda consulta repetiria a mesma expressão em cada agrupamento por raridade.

### 4.5 Conciliação de chaves (R4) e tratamento dos problemas das fontes

**Problema 1 — `#` do CSV ≠ número da Pokédex.** A única via é o **nome**. Para cada linha do CSV, `carregar.py` gera slugs candidatos da PokéAPI, em ordem de prioridade, e aceita o primeiro que existir na coleção `pokemon` da bronze:

1. dicionário `OVERRIDES_EXPLICITOS` para nomes sem padrão regular (`Nidoran♀/♂`, `Farfetch'd`, `Mr. Mime`, `Mime Jr.`, `Porygon2`, `Kyurem Black/White`, `Hoopa Unbound`, `Keldeo Resolute Forme`, `Meloetta Pirouette Forme` etc.);
2. regras por família: `Mega X [X|Y]` → `x-mega[-x|-y]`; `Primal X` → `x-primal`; `X <Variante> Forme`, `X <Variante> Cloak`, `X <Variante> Size` → `x-variante`; `X Zen Mode` → `x-zen`;
3. normalização direta (minúsculas, espaços → hífen, remoção de pontuação).

O resultado é gravado em **`conciliacao.csv`** (forma escolhida para o artefato de R4), com uma linha por registro do CSV: `numero_csv`, `nome_csv`, `slug_pokeapi`, `status` (`conciliado` / `não conciliado`) e `tratamento`. Nada é descartado em silêncio. Como o CSV e a PokéAPI não coincidem integralmente, o dicionário é **refinado iterativamente** a partir do que a primeira execução real listar como `não conciliado`.

**Registros não conciliados** permanecem em `dim_pokemon` com `conciliado = FALSE`, mantendo tipos, status e geração vindos do CSV; os atributos que dependem exclusivamente da PokéAPI ficam `NULL`.

**Problema 2 — registro 63 sem nome (dado ausente).** O registro tem tipo, atributos e participa de combates. Ele é mantido em `dim_pokemon` com `nome = 'Desconhecido (registro 63 do CSV)'` e `nome_desconhecido = TRUE`; consequentemente, seus combates permanecem na fato e nenhum dos 50.000 combates é omitido (R5). Seus atributos de espécie da PokéAPI ficam `NULL`, pois não há nome para conciliar. Optou-se por **linha própria com sinalizador**, e não por um membro especial genérico, porque o registro possui dados reais (tipo, status, geração) que continuam alimentando as análises 1 a 3. Um membro especial genérico os perderia.

**Problema 3 — `habitat` nulo (conceito inaplicável).** Quando a espécie é encontrada na PokéAPI e `habitat` é nulo, grava-se o texto **`'não se aplica'`**: o conceito não existe nos jogos posteriores a FireRed/LeafGreen. Quando o registro **não foi conciliado** (nenhuma espécie disponível), `habitat` permanece `NULL`, que aqui significa **dado ausente**. Assim, as duas situações, idênticas no JSON (`null`), ficam distinguíveis na modelagem: `'não se aplica'` ≠ `NULL`.

**Herança de atributos das formas alternativas.** Formas alternativas (`is_default = false`, id > 10000) não existem em `/pokemon-species/`. Para cada uma, `carregar.py` lê `species.name` do documento da forma, localiza a espécie correspondente na coleção `especies` e herda dela habitat, cor, forma corporal, taxa de captura, felicidade base, taxa de crescimento e os indicadores de raridade. A **geração** é lida do campo `Generation` do CSV, sempre presente, inclusive para o registro sem nome.

**Filtro de tipos.** `/type/` devolve 21 tipos. O silver mantém apenas os **18 tipos reais** (ids 1 a 18) e descarta `stellar`, `unknown` e `shadow`: nenhuma linha do CSV os usa e nenhuma combinação com eles pode ser exercitada pelas análises 6 e 7. Incluí-los levaria a ponte de 324 a 441 linhas, com combinações inalcançáveis por qualquer FK da fato. A bronze mantém os 21 intactos.

---

## 5. Gold

Cada tabela do gold é populada por `INSERT INTO gold.<t> SELECT ... FROM silver...`, executado **inteiramente no PostgreSQL**; nenhum dado passa pela memória do Python (seção 5.1 do enunciado, R11). As consultas finais leem as tabelas do gold com `WHERE`/`ORDER BY`/`LIMIT` apenas.

| Tabela | Grão | Análise |
|---|---|---|
| `gold.ranking_pokemon` | um Pokémon | 3 |
| `gold.taxa_vitorias_por_tipo` | um tipo primário | 4 |
| `gold.taxa_vitorias_por_faixa_velocidade` | uma faixa de diferença de velocidade | 5 |
| `gold.taxa_vitorias_por_multiplicador` | um multiplicador de efetividade | 6 |
| `gold.matriz_confronto` | tipo atacante × tipo defensor | 7 |
| `gold.taxa_vitorias_geracao_ataque` | geração × atacou primeiro | 8 |
| `gold._log_carga` | metadado: tabela, linhas, momento da carga | — |

**Análise 3 e o corte mínimo.** `gold.ranking_pokemon` materializa `combates` para **todos** os Pokémon; o corte é aplicado na consulta (`WHERE combates >= 100`), então pode ser alterado sem reexecutar o pipeline, e a contagem aparece ao lado da taxa (seção 1.3 do enunciado). O valor 100 é **provisório**: com ~100.000 participações para ~800 Pokémon a média é ~125, e o corte deve ser confirmado contra a distribuição real de `combates` (ver `RELATORIO.md`, análise 3).

**Análise 4.** Usa `tipo_1_key` da fato, ligada direto a `dim_tipo`, sem passar por `dim_pokemon`.

**Análise 5 — faixas.** Cinco faixas simétricas em torno de zero: `≤ −50`, `−49 a −1`, `0`, `1 a 49`, `≥ 50`. O empate (0) é isolado porque é o ponto neutro da simetria. Os cortes em ±50 são **provisórios** e devem ser revisados contra a distribuição real de `diferenca_velocidade`.

**Análise 7 — orientação e `diverge`.** A célula (A, B) é a proporção de participações de um Pokémon de tipo primário A contra um de tipo primário B que terminaram em vitória de A; a orientação é a do **vencedor**, e `atacou_primeiro` não participa. Cada combate alimenta (A, B) e (B, A), então as duas células somam 1. `multiplicador_matriz` é o valor 18×18 (tipo primário contra tipo primário).
A coluna `diverge` é verdadeira quando o multiplicador é **> 1 e a taxa ≤ 0,5**, ou **< 1 e a taxa ≥ 0,5**. Consequências documentadas: (i) posições com multiplicador 1 **nunca** divergem por esta definição; (ii) pares de tipos sem nenhum combate não aparecem na tabela, portanto ela pode ter **menos de 324 linhas**.

---

## 6. A análise proposta pelo grupo (análise 8)

**Pergunta de negócio:** o benefício de atacar primeiro em um combate é uniforme entre as gerações, ou varia conforme a geração de introdução do combatente?

**Relevância:** `combats.csv` registra quem atacou primeiro, mas as sete análises obrigatórias não usam essa informação como critério de agrupamento. A pergunta mede se a "vantagem de iniciativa" é um efeito estável do simulador ou depende da geração. Hipótese a testar (não afirmada): se as gerações mais recentes têm maior amplitude de status, a ordem de ataque pode pesar menos nelas.

**Capacidade do modelo exigida e ausente nas análises 1 a 7:**
- usa `dim_geracao` **ligada diretamente à fato** por `geracao_key`; nenhuma das análises 3 a 7 agrupa por geração;
- cruza essa dimensão com `atacou_primeiro`, atributo **situacional do combate** que as demais não usam como critério de agrupamento;
- o grão resultante (geração × atacou primeiro, até 12 linhas) é distinto do de todas as outras tabelas do gold.

**Limitação a considerar na interpretação:** a geração é a do combatente da linha, e o oponente pode ser de outra geração; por isso as taxas de `atacou_primeiro = TRUE` e `FALSE` dentro de uma mesma geração **não** são complementares.

**Tabela:** `gold.taxa_vitorias_geracao_ataque`. **Interpretação:** ver `RELATORIO.md`.

---

## 7. Idempotência por camada

| Camada | Mecanismo | Efeito da 2ª execução |
|---|---|---|
| Bronze (`extrair.py`) | **Cache em disco** (`dados_brutos/`) consultado antes de qualquer requisição; **upsert** (`update_one` com `upsert=True`) por `_id` derivado da chave natural (`pokemon/25`, `especie/25`, `tipo/1`, `pokemon_csv/7`, `combate/12345`) | **Zero requisições HTTP**; nenhum documento duplicado. O documento é regravado com o mesmo conteúdo da fonte, e `_ingerido_em` é atualizado |
| Silver (`carregar.py`) | Executa `sql/silver.sql` (`CREATE ... IF NOT EXISTS`), depois `TRUNCATE ... RESTART IDENTITY CASCADE` e reconstrução integral a partir da bronze, em uma única transação | Estado final idêntico ao da 1ª execução; se algo falhar, a transação é revertida |
| Gold (`publicar.py`) | Executa `sql/gold.sql`, `TRUNCATE` das seis tabelas e repovoamento por `INSERT ... SELECT` sobre o silver, em uma única transação | Mesmo estado final, sem duplicar linhas |

`gold._log_carga` é um **histórico** acumulativo (uma linha por tabela a cada execução, com contagem e momento), e não é reconstruído; ele é metadado de orquestração, fora do esquema estrela. Ao final, `carregar.py` imprime a contagem de cada tabela e alerta se `fato_confronto` não tiver exatamente 2 × (número de combates da bronze) linhas.

---

## 8. Decisões de projeto não especificadas pelo enunciado

1. **Reconstrução total (truncate + reload) em silver e gold, em vez de upsert incremental.** A bronze é a fonte imutável e as camadas seguintes são inteiramente derivadas dela; reprocessar do zero é mais simples de raciocinar (corretude, idempotência) do que lógica de merge, ao custo de tempo de carga, aceitável em ~800 dimensões e 100.000 fatos. A transação única evita estado parcial.
2. **`conciliacao.csv` em vez de `silver.log_conciliacao`.** Escolha da forma preferida de R4; o arquivo é regenerado a cada `carregar.py` e versionado no repositório.
3. **`COPY ... FROM STDIN` (`cursor.copy()` do psycopg) para `efetividade_tipo` e `fato_confronto`.** Recurso nativo do driver, sem biblioteca tabular; evita 100.000 `INSERT`s individuais.
4. **Colunas `nome_desconhecido` e `conciliado` em `dim_pokemon`.** Separam auditavelmente o dado ausente (Problema 2) das falhas de conciliação (Problema 1), sem depender da presença de `NULL` em outras colunas.
5. **Tipo do Pokémon duplicado como texto em `dim_pokemon` e como chave na fato.** O texto atende às análises 1 e 2 sem tocar a fato; a chave atende às análises 4, 6 e 7 sem criar snowflake.
6. **Faixas da análise 5 e corte da análise 3 tratados como parâmetros revisáveis:** o corte por consulta (coluna `combates` materializada) e as faixas por `CASE` em `publicar.py`.
7. **Bibliotecas:** `requests` (só em `extrair.py`), `pymongo` e `psycopg[binary]`. Nenhum `import` de `pandas`, `polars`, `numpy` ou `pyarrow`; os CSVs são lidos com `csv` da biblioteca padrão, e toda agregação ocorre em SQL.

---

## 9. Limitações conhecidas

- `_ingerido_em` é regravado a cada execução de `extrair.py`; a contagem de documentos e o conteúdo da fonte não mudam.
- O dicionário `OVERRIDES_EXPLICITOS` precisa ser refinado a partir do `conciliacao.csv` da primeira execução real; a expectativa é de que nem todos os nomes casem de primeira.
- O enunciado (R5) menciona "membro especial" para o registro sem nome; este projeto o trata como linha real sinalizada (seção 4.5). A escolha está justificada, mas é uma interpretação do requisito.
- As batalhas são **simuladas**: qualquer padrão medido (ou a ausência dele, especialmente nas análises 5, 6 e 7) reflete o programa que as gerou, não partidas reais.
