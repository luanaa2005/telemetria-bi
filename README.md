# Telemetria de licenças Microsoft 365

Abra `telemetria.pbip` no Power BI Desktop. O projeto contém quatro páginas, adaptadas à base anonimizada com muitas unidades e subunidades:

- **Visão geral:** contas, atribuições, Copilot, revisão e ranking das dez unidades com mais licenças.
- **Unidades:** lista completa e ordenável, com volume e taxa de revisão e percentual com Copilot. Selecione uma unidade na tabela ou no filtro para abrir suas subunidades.
- **Produtos:** combinações de produtos por conta e distribuição por vínculo. O filtro Empresa permite investigar as organizações contratadas.
- **Revisão:** unidades com mais contas sinalizadas, motivos e lista das contas para conferência.

Os filtros de Unidade, Vínculo funcional e Empresa têm busca e são sincronizados entre as páginas. Combinação de produtos é sincronizado nas três primeiras páginas; Motivo é específico de Revisão. Rankings, combinações e linhas das tabelas filtram os outros indicadores da página; clique novamente para limpar. O gráfico dos quatro produtos na visão geral é somente informativo. No modo de edição do Desktop, use **Ctrl + clique** nos botões da navegação lateral; no modo de leitura, use clique simples.

Os rankings mostram **até dez unidades dentro do recorte selecionado**, com desempate pelo nome. Os cartões consideram todo o recorte, não somente as dez unidades. Na página Unidades, os cabeçalhos permitem ordenar; a rolagem mantém todas as unidades disponíveis. Nenhum gráfico tenta exibir centenas de subunidades simultaneamente.

## Dados e atualização

A fonte é `data/fake-data.csv`, com delimitador `;` e codificação UTF-8. Cada arquivo representa **uma execução do job**, com uma linha por UPN. `Data da coleta` é preservada na origem, mas não participa dos filtros ou de comparações temporais. Substitua o CSV e clique em **Atualizar** no Desktop.

O parâmetro `CaminhoPasta`, no Power Query, aponta para a pasta `data`. Ajuste-o ao mover o projeto para outro computador.

## Definições dos indicadores

- **Contas na base:** quantidade de UPNs na fotografia do job.
- **Contas licenciadas:** UPNs com pelo menos um produto no recorte selecionado.
- **Licenças atribuídas:** quantidade de combinações UPN × produto com indicador igual a 1. Uma conta com E5 e Copilot soma duas atribuições.
- **Cobertura:** contas licenciadas divididas pelas contas do recorte organizacional. Ao selecionar um produto, o denominador continua sendo a população da unidade, vínculo e empresa selecionados.
- **Contas para revisão:** quantidade de contas distintas que apresentam ao menos uma das condições abaixo. Uma conta com vários motivos entra uma única vez.
- **Taxa de revisão:** contas sinalizadas divididas pela população do recorte organizacional. Selecionar um motivo restringe o numerador, mas preserva essa população no denominador.
- **% Copilot:** contas com Copilot atribuído divididas pelas contas do recorte; indica distribuição, sem medir utilização.
- **Subunidades no recorte:** pares distintos de Unidade + Subunidade. Um mesmo nome em unidades diferentes não é fundido.

Os motivos de revisão, na ordem de prioridade exibida na lista, são:

1. Situação funcional inativa com licença.
2. Situação funcional não informada com licença.
3. Conta desabilitada com licença.
4. Situação funcional ativa com conta desabilitada, mesmo sem licença.

Esses critérios identificam registros para conferência cadastral. Não comprovam ociosidade, utilização dos produtos, elegibilidade contratual ou economia financeira. Não há custos no novo relatório, pois a fonte não contém preços. O cálculo antigo com preços fixos foi retirado.

## Modelo

`FatoContas` mantém uma linha por conta e preserva as contas sem licença. `FatoLicencas` transforma as quatro colunas de produtos em atribuições individuais, mantendo somente valores iguais a 1.

As dimensões `DimConta`, `DimOrganizacao`, `DimVinculo`, `DimEmpresa` e `DimCombinacao` se relacionam com ambas as tabelas por relações 1 para muitos, com filtro da dimensão para o fato. `DimProduto` filtra somente as atribuições. As duas tabelas de fatos não se relacionam diretamente. `Indicadores` reúne as medidas do relatório.

`DimOrganizacao` usa a chave composta Unidade + Subunidade. `DimCombinacao` mantém o conjunto completo de produtos de uma conta, permitindo que a seleção de uma combinação filtre corretamente tanto contas quanto atribuições. A consulta importada com nome de data passou a referenciar `telemetria`, usando a mesma fonte e transformação.

As tabelas anteriores foram preservadas e ocultadas para compatibilidade. As novas páginas utilizam o novo modelo e as novas medidas.

## Verificação

Os totais, as combinações de produtos, os filtros, os rankings e a navegação foram conferidos no Power BI Desktop com a base fictícia anonimizada. Ao trocar o CSV, atualize o modelo e confira se os totais correspondem à nova fonte.
