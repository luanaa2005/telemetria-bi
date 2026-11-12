# Dashboard HTML — alternativa ao Power BI

Versão em HTML/CSS/JS puro do relatório `telemetria.pbip`, sem Power BI, sem
servidor e sem dependências. O resultado é **um único arquivo** que abre com
duplo clique, funciona offline e pode ser anexado em e-mail ou jogado num
SharePoint.

Esta pasta é independente: nada aqui lê ou escreve dentro de
`telemetria.Report/` ou `telemetria.SemanticModel/`. O projeto do Power BI
continua funcionando exatamente como antes.

## Como gerar

```bash
python3 web/gerar_dashboard.py
```

Sem argumentos, lê `\\ger-sinet\telemetria` — o mesmo caminho do parâmetro
`CaminhoPasta` do modelo semântico. **Lê a pasta inteira**: o CSV mais recente
alimenta as páginas de detalhe e todos juntos formam a série histórica. Outras
formas:

```bash
python3 web/gerar_dashboard.py /caminho/da/pasta         # outra pasta
python3 web/gerar_dashboard.py coleta.csv                # um CSV específico
python3 web/gerar_dashboard.py coleta.csv -o painel.html # outro nome de saída
python3 web/gerar_dashboard.py --historico 30            # só as 30 últimas coletas
python3 web/gerar_dashboard.py --historico 0             # todas, sem limite
```

## Como a pasta de coletas é organizada

A coleta grava **uma subpasta por execução**, com o CSV e um XLSX dentro:

```
\\ger-sinet\telemetria\
  03-11-2026-inventarioLicOffice365-050039\
    03-11-2026-inventarioLicOffice365-050039.csv     ← é este que importa
    03-11-2026-inventarioLicOffice365-050039.xlsx    ← ignorado
  03-11-2026-inventarioLicOffice365-142210\          ← execução avulsa do mesmo dia
  02-11-2026-inventarioLicOffice365-050043\
  ...
```

Por isso a varredura é **recursiva**, igual ao `Folder.Files()` do Power Query.
Olhar só a raiz não acharia nada.

A coleta automática roda diariamente por volta das 5h, e às vezes alguém dispara
execuções extras durante o dia. O gerador lida com isso em duas etapas:

1. **Antes de ler qualquer arquivo**, fica só a execução mais recente de cada
   dia. Cada CSV tem ~1,5 MB e vem pela rede, então ler três arquivos do mesmo
   dia para descartar dois seria desperdício puro.
2. **Depois de ler**, deduplica de novo pela `Data da coleta` de dentro do CSV —
   rede de segurança caso a data do arquivo e a data do conteúdo divirjam.

O resultado é um ponto por dia no gráfico de Evolução.

### O esquema das coletas mudou com o tempo

CSVs antigos não trazem todas as colunas de hoje — `M365 F5 Security`, por
exemplo, foi adicionada depois. O Power BI nunca tropeçou nisso porque lê só o
arquivo mais recente; aqui, que lemos a série inteira, isso apareceu.

Por isso só são **obrigatórias** as colunas sem substituto: `Unidade`,
`Subunidade`, `Qualidade` e `Situação funcional`. Faltando qualquer uma delas, o
arquivo é rejeitado com a lista do que foi encontrado.

As demais são opcionais e assumem um padrão quando ausentes — colunas de licença
viram zero, `Conta` e `Empresa` viram vazio. A ausência é registrada e aparece:

- no terminal (`Coluna ausente ...: M365 F5 Security em 3 coleta(s)`);
- na nota da página de Evolução, para que uma linha caindo a zero no passado não
  seja lida como queda real de licenças.

`Data da coleta` também é opcional: faltando ou em formato desconhecido, o
gerador usa a data do nome do arquivo, e só então a data de modificação. É por
isso que copiar a pasta de rede — o que reescreve todas as datas de modificação
— não destrói o histórico.

### O limite de histórico

Com coleta diária, a pasta cresce o ano todo. O padrão é ler as **90 coletas
mais recentes**; o resto é ignorado sem ser baixado. O comando informa quantos
arquivos ficaram de fora:

```
CSVs encontrados .: 412
  ignorados ......: 47 (outra execucao no mesmo dia)
  fora do limite .: 275 (use --historico 0 para ler tudo)
CSVs lidos .......: 90
```

Aumente com `--historico 180`, ou tire o limite com `--historico 0` — só saiba
que cada coleta a mais são ~1,5 MB trafegando.

A saída padrão é `web/dashboard.html`. Repita o comando a cada nova coleta.

Requisito: Python 3.8 ou superior. Nenhuma biblioteca externa.

## Arquivos

| Arquivo | O que é |
|---|---|
| `gerar_dashboard.py` | Lê o CSV, refaz as agregações e injeta os dados no template |
| `template.html` | Layout, estilos e gráficos. Edite aqui para mudar a aparência |
| `dashboard.html` | A saída gerada (não versionada por padrão) |
| `PUBLICAR.md` | Como servir por HTTPS e embutir numa aba do Teams |

## Os dois modos de saída

```bash
python3 web/gerar_dashboard.py                    # embutido: um arquivo só
python3 web/gerar_dashboard.py --modo externo     # dashboard.html + dados.json
```

**Embutido** (padrão) é um arquivo autocontido: abre do disco, vai por e-mail,
funciona offline. Para atualizar, você reenvia o arquivo.

**Externo** separa os dados num `dados.json` ao lado. A página busca o JSON ao
abrir, então basta regerar o JSON no servidor para todo mundo ver os números
novos — o HTML nunca muda. É o modo exigido pela aba do Teams, e **não**
funciona abrindo o arquivo do disco, porque o navegador bloqueia a leitura de
arquivos vizinhos em `file://`.

Os dois convivem: o externo alimenta a aba do Teams, o embutido é o que você
anexa num e-mail. Receita completa de publicação em [PUBLICAR.md](PUBLICAR.md).

O gerador substitui o marcador `/*{{DADOS}}*/` do template por um JSON com os
dados agregados. Para mexer no visual, edite `template.html` e gere de novo.

## As cinco páginas

As duas primeiras são a tradução do relatório atual. As três últimas não
existem no Power BI.

| Página | O que mostra |
|---|---|
| **Visão Gerencial** | Porte do relatório atual: licenças por vínculo, ociosas, composição |
| **Alocação por Unidade** | Porte do relatório atual: E5, terceiros, % e custo |
| **Economia potencial** | Desperdício em R$/ano com simulador de cenário de revogação |
| **Evolução** | Série histórica de todas as coletas da pasta |
| **Terceiros** | Licenças e custo por empresa contratada |

### Economia potencial

Classifica cada licença premium desperdiçada em um de três motivos
**exclusivos**, nesta ordem de precedência:

1. `desabilitada` — conta já desligada no diretório, ainda com licença
2. `inativo` — situação funcional INATIVO, conta ainda habilitada
3. `naoInformado` — sem situação funcional no cadastro

Como os baldes são exclusivos, marcar e desmarcar no simulador soma e subtrai
sem contar a mesma licença duas vezes. O total em reais usa o preço unitário de
cada produto, então revogar um E5 vale mais que revogar um Copilot.

Isso **não** é a mesma conta da coluna `Ociosas` do modelo, que olha só a
situação funcional e ignora o estado da conta. A diferença entre os dois
números é gente com conta desligada cuja situação funcional ainda diz ATIVO — o
dashboard explica isso em texto na própria página.

### Evolução

O `Table.Sort` + `Sorted{0}[Content]` do Power Query pega o arquivo mais novo e
**descarta todas as coletas anteriores**. Aqui cada CSV da pasta vira um ponto
da série, identificado pela `Data da coleta` (não pelo nome do arquivo). Duas
exportações da mesma data: vale a mais recente no disco.

Com um CSV só, a página mostra um aviso em vez de um gráfico vazio — a série
passa a existir a partir da segunda coleta.

### Terceiros

Agrupa só quem tem `Qualidade = TERCEIRIZADO` por `Empresa`. Cada pessoa cai em
um de quatro estados exclusivos (ativo / inativo / conta desabilitada / sem
situação), então a barra empilhada fecha no total de pessoas da empresa.

## O que foi portado

As três consultas do Power Query viraram funções em `gerar_dashboard.py`:

| Modelo semântico | Função |
|---|---|
| `Visão Gerencial` | `visao_gerencial()` |
| `Alocação por unidade` | `alocacao_por_unidade()` |
| `AlocacaoPessoas` (coluna `Classificação`) | `classificar()` |

As páginas novas acrescentam `economia()`, `fornecedores()` e
`resumo_coleta()`, que não têm equivalente no modelo.

As medidas DAX viraram somas e divisões em JavaScript, calculadas no navegador
a cada mudança de filtro. Os números foram conferidos contra um cálculo
independente feito direto do CSV e batem exatamente.

Constantes de negócio ficam no topo de `gerar_dashboard.py`:

```python
CUSTO_ANUAL_E5 = 3120.60
CUSTO_ANUAL_COPILOT = 2590.08
LIMITE_CRITICO = 0.50   # faixas da medida "% E5 Terceiros Color"
LIMITE_ATENCAO = 0.25
```

## Três diferenças conscientes em relação ao relatório atual

**1. Os cards da página Alocação só contam nível UNIDADE.**
Fiel ao modelo: as medidas usam `CALCULATE(..., 'Alocação por unidade'[Nível] =
"UNIDADE")`, então ignoram as subunidades *e* ignoram o filtro de Nível. É por
isso que "Total de E5" nessa página costuma ser bem menor que "M365 E5" na Visão
Gerencial — são recortes diferentes. O dashboard avisa isso em texto, abaixo dos
cards. Para fazer os cards responderem ao filtro como o resto da página, troque
`DADOS.alocacao.filter((l) => l.nivel === "UNIDADE")` por `filtrar(DADOS.alocacao)`
em `desenharAlocacao()`.

**2. O gráfico de % de E5 em terceiros usa a razão, não a soma.**
No relatório atual o gráfico soma a coluna `% E5 em terceiros` ao agregar as
subunidades de uma unidade — somar percentuais infla o resultado e pode passar
de 100%. Aqui a porcentagem é recalculada como
`soma(E5 terceiros) / soma(E5 total)` dentro do recorte filtrado, que é o número
que a medida `% E5 Terceiros` entrega.

**3. Barras empilhadas no lugar de barras agrupadas.**
Em "Licenças por vínculo" os quatro vínculos somam o total da unidade, e em "E5
em terceiros" um segmento é subconjunto do outro — nos dois casos a relação é
parte/todo, que a barra empilhada mostra e a agrupada esconde.

## Privacidade

O HTML gerado contém **apenas números agregados** por unidade, subunidade,
empresa e data de coleta. Nome, UPN, e-mail e CPF ficam no CSV e não entram no
arquivo — ao contrário de um `.pbix`, que carrega a tabela inteira junto. Dá
para distribuir o dashboard sem distribuir dado pessoal.

A razão social das empresas terceirizadas aparece na página Terceiros, porque é
o eixo da análise. Se isso for sensível no seu contexto, o lugar de tratar é a
função `fornecedores()` em `gerar_dashboard.py`.

Por isso `dashboard.html` não está no `.gitignore`: ele não tem dado sensível.
Se preferir não versionar os snapshots, acrescente `web/dashboard.html`.

## Visualizar durante o desenvolvimento

```bash
python3 -m http.server 8777 --directory web
```

Depois abra `http://localhost:8777/dashboard.html`. Abrir o arquivo direto do
disco (`file://`) também funciona — o servidor só facilita recarregar.

## Acessibilidade e aparência

- Tema claro e escuro, seguindo a preferência do sistema, com botão para trocar.
- Paleta validada para daltonismo e contraste. Não troque um hex isolado sem
  revalidar o conjunto — a ordem das cores é o que garante a separação.
- Todo gráfico tem um botão "Tabela" que mostra os mesmos valores em texto.
- Dicas aparecem no hover e no foco pelo teclado; nenhum valor existe só na dica.
- Imprime em uma folha razoável (`Ctrl+P`), com as duas páginas e sem os controles.
