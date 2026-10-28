"""Build the editable Power BI report and its snapshot semantic model.

Run from any directory: python scripts/build_report.py
Only the Python standard library is needed. Existing definitions are backed up
outside the repository before the first rebuild.
"""

from __future__ import annotations

import csv
import hashlib
import json
import pathlib
import re
import shutil
import tempfile
import uuid

from product_catalog import read_product_catalog

ROOT = pathlib.Path(__file__).resolve().parents[1]
REPORT = ROOT / 'telemetria.Report'
MODEL = ROOT / 'telemetria.SemanticModel'
PAGES = REPORT / 'definition/pages'
TABLES = MODEL / 'definition/tables'
PAGE_IDS = ['9f35d08d89b3d2309cd7', 'b8c9d0e1f2a3b4c5d6e7', 'd207f6b821e450c9b341', 'c106e5a710d349b8a230']
PRODUCTS = [source for source, name, order in read_product_catalog()]
LEGACY_TABLES = {'27-10-2026-inventarioLicOffice365-050041', 'Visão Gerencial',
                 'Alocação por unidade', 'Preços', 'AlocacaoPessoas', 'dim Nível', 'Pessoas por vínculo'}
NAVY, BLUE, TEAL, PURPLE = '#12263F', '#3867E8', '#087F83', '#8060C5'
TEXT, MUTED, LIGHT, LINE, AMBER = '#20354D', '#65778B', '#F3F6FA', '#E1E8F0', '#A86913'
WHITE = '#FFFFFF'


def identifier(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()[:20]


def tag(value):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, 'telemetria-bi/' + value))


def quoted(value):
    return "'" + value.replace("'", "''") + "'"


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def backup():
    key = identifier(str(ROOT).lower())[:10]
    destination = pathlib.Path(tempfile.gettempdir()) / ('telemetria-bi-before-scale-redesign-' + key)
    if not destination.exists():
        destination.mkdir()
        for source in (REPORT, MODEL):
            shutil.copytree(source, destination / source.name, ignore=shutil.ignore_patterns('.pbi'))
    print('Original definitions:', destination)


def table(name, columns, source, measures=None, hidden=False, hierarchy=None):
    lines = [f'table {quoted(name)}', f'\tlineageTag: {tag(name)}']
    if hidden:
        lines.append('\tisHidden')
    for mname, expression, fmt, description in measures or []:
        lines.append('')
        if description:
            lines.append('\t/// ' + description)
        lines += [f'\tmeasure {quoted(mname)} = {expression}', f'\t\tlineageTag: {tag(name + "/" + mname)}']
        if fmt:
            lines.append(f'\t\tformatString: {fmt}')
    for column in columns:
        cname, dtype = column[:2]
        options = column[2] if len(column) > 2 else {}
        lines += ['', f'\tcolumn {quoted(cname)}', f'\t\tdataType: {dtype}',
                  f'\t\tlineageTag: {tag(name + "/" + cname)}',
                  f'\t\tsummarizeBy: {"sum" if options.get("sum") else "none"}',
                  f'\t\tsourceColumn: {cname}']
        if options.get('hidden'):
            lines.append('\t\tisHidden')
        if options.get('sort'):
            lines.append(f'\t\tsortByColumn: {quoted(options["sort"])}')
        if dtype == 'int64':
            lines.append('\t\tformatString: 0')
    if hierarchy:
        hname, levels = hierarchy
        lines += ['', f'\thierarchy {quoted(hname)}', f'\t\tlineageTag: {tag(name + "/hierarchy")}']
        for level in levels:
            lines += [f'\t\tlevel {quoted(level)}', f'\t\t\tcolumn: {quoted(level)}']
    lines += ['', f'\tpartition {quoted(name)} = m', '\t\tmode: import', '\t\tsource =']
    lines.extend('\t\t\t\t' + line for line in source.strip().splitlines())
    lines += ['', '\tannotation PBI_ResultType = Table', '']
    (TABLES / (name + '.tmdl')).write_text('\n'.join(lines), encoding='utf-8')


def build_model():
    new_names = {'FatoContas', 'FatoLicencas', 'DimConta', 'DimOrganizacao',
                 'DimVinculo', 'DimEmpresa', 'DimProduto', 'DimCombinacao', 'Indicadores'}
    for name in LEGACY_TABLES:
        path = (TABLES / (name + '.tmdl')).resolve()
        if not path.is_relative_to(TABLES.resolve()):
            raise RuntimeError('Legacy table path escaped the model workspace')
        if path.exists():
            path.unlink()

    original = TABLES / 'telemetria.tmdl'
    content = original.read_text(encoding='utf-8')
    # A UPN is the account key; normalize it before constructing dimensions.
    if '{"UPN", each Text.Lower' not in content:
        content = content.replace('{"Qualidade", each', '{"UPN", each Text.Lower(Text.Trim(_)), type text},\n\t\t\t\t        {"Qualidade", each')
    content = content.replace('QuoteStyle.None', 'QuoteStyle.Csv')
    original.write_text(content, encoding='utf-8')
    with (ROOT / 'data/fake-data.csv').open(encoding='utf-8-sig', newline='') as handle:
        header = next(csv.reader(handle, delimiter=';'))
    raw = [(c, 'int64' if c in PRODUCTS else 'dateTime' if c == 'Data da coleta' else 'string',
            {'hidden': c in {'Data da coleta', 'UPN', 'Qualidade', 'Empresa', 'Unidade', 'Subunidade', *PRODUCTS}})
           for c in header]
    table('FatoContas', raw + [
        ('OrganizacaoKey', 'string', {'hidden': True}), ('Total de licenças', 'int64'),
        ('Produtos', 'string'), ('Cobertura', 'string'), ('Situação', 'string'),
        ('Motivo da revisão', 'string'), ('Revisar', 'int64', {'hidden': True}),
    ], '''let
    Fonte = telemetria,
    Catalogo = Table.Buffer(CatalogoProdutos),
    ColunasProdutos = Catalogo[ColunaOrigem],
    ComChave = Table.AddColumn(Fonte, "OrganizacaoKey", each [Unidade] & "|" & [Subunidade], type text),
    ComTotal = Table.AddColumn(ComChave, "Total de licenças", each List.Sum(Record.FieldValues(Record.SelectFields(_, ColunasProdutos))), Int64.Type),
    ComProdutos = Table.AddColumn(ComTotal, "Produtos", each
        let
            ContaAtual = _,
            Atribuidos = Table.SelectRows(Catalogo, (ProdutoAtual) => Record.Field(ContaAtual, ProdutoAtual[ColunaOrigem]) = 1)
        in
            Text.Combine(Atribuidos[Produto], " · "), type text),
    ProdutosVisiveis = Table.ReplaceValue(ComProdutos, "", "Sem licença", Replacer.ReplaceValue, {"Produtos"}),
    ComCobertura = Table.AddColumn(ProdutosVisiveis, "Cobertura", each if [#"Total de licenças"] > 0 then "Com licença" else "Sem licença", type text),
    ComSituacao = Table.AddColumn(ComCobertura, "Situação", each if [#"Situação funcional"] = "ATIVO" then "Ativa" else if [#"Situação funcional"] = "INATIVO" then "Inativa" else "Não informada", type text),
    ComMotivo = Table.AddColumn(ComSituacao, "Motivo da revisão", each
        if [#"Total de licenças"] > 0 and [#"Situação funcional"] = "INATIVO" then "Inativa com licença"
        else if [#"Total de licenças"] > 0 and [#"Situação funcional"] <> "ATIVO" and [#"Situação funcional"] <> "INATIVO" then "Situação não informada com licença"
        else if [#"Total de licenças"] > 0 and [Conta] = "Desabilitada" then "Desabilitada com licença"
        else if [#"Situação funcional"] = "ATIVO" and [Conta] = "Desabilitada" then "Ativa, mas desabilitada"
        else "Sem pendência", type text),
    ComRevisao = Table.AddColumn(ComMotivo, "Revisar", each if [#"Motivo da revisão"] = "Sem pendência" then 0 else 1, Int64.Type)
in
    ComRevisao''')

    table('FatoLicencas', [
        ('UPN', 'string', {'hidden': True}), ('OrganizacaoKey', 'string', {'hidden': True}),
        ('Qualidade', 'string', {'hidden': True}), ('Empresa', 'string', {'hidden': True}),
        ('Produtos', 'string', {'hidden': True}),
        ('Produto', 'string', {'hidden': True}), ('Quantidade', 'int64', {'sum': True}),
    ], '''let
    Catalogo = Table.Buffer(CatalogoProdutos),
    ColunasProdutos = Catalogo[ColunaOrigem],
    Fonte = Table.SelectColumns(FatoContas, {"UPN", "OrganizacaoKey", "Qualidade", "Empresa", "Produtos"} & ColunasProdutos),
    ProdutosEmLinhas = Table.Unpivot(Fonte, ColunasProdutos, "ColunaOrigem", "Quantidade"),
    Atribuidas = Table.SelectRows(ProdutosEmLinhas, each [Quantidade] = 1),
    ComCatalogo = Table.NestedJoin(Atribuidas, {"ColunaOrigem"}, Catalogo, {"ColunaOrigem"}, "Cadastro", JoinKind.Inner),
    ComProduto = Table.ExpandTableColumn(ComCatalogo, "Cadastro", {"Produto"}, {"Produto"}),
    SemOrigem = Table.RemoveColumns(ComProduto, {"ColunaOrigem"}),
    Tipos = Table.TransformColumnTypes(SemOrigem, {{"Quantidade", Int64.Type}})
in
    Tipos''')
    table('DimConta', [('UPN', 'string'), ('Nome', 'string')],
          'Table.Distinct(Table.SelectColumns(telemetria, {"UPN", "Nome"}))')
    table('DimOrganizacao', [('OrganizacaoKey', 'string', {'hidden': True}), ('Unidade', 'string'), ('Subunidade', 'string')],
          'Table.Distinct(Table.SelectColumns(FatoContas, {"OrganizacaoKey", "Unidade", "Subunidade"}))',
          hierarchy=('Estrutura organizacional', ['Unidade', 'Subunidade']))
    table('DimEmpresa', [('Empresa', 'string')], 'Table.Distinct(Table.SelectColumns(telemetria, {"Empresa"}))')
    table('DimCombinacao', [('Produtos', 'string')], 'Table.Distinct(Table.SelectColumns(FatoContas, {"Produtos"}))')
    table('DimVinculo', [('Qualidade', 'string', {'hidden': True}), ('Vínculo', 'string', {'sort': 'Ordem'}), ('Ordem', 'int64', {'hidden': True})], '''let
    Fonte = Table.Distinct(Table.SelectColumns(telemetria, {"Qualidade"})),
    ComNome = Table.AddColumn(Fonte, "Vínculo", each if [Qualidade] = "AUTORIDADE" then "Autoridades" else if [Qualidade] = "SERVIDOR" then "Servidores" else if [Qualidade] = "TERCEIRIZADO" then "Terceirizados" else if [Qualidade] = "ESTAGIARIO" then "Estagiários" else if [Qualidade] = "NAO_CLASSIFICADO" then "Não classificado" else Text.Proper([Qualidade]), type text),
    ComOrdem = Table.AddColumn(ComNome, "Ordem", each if [Qualidade] = "AUTORIDADE" then 1 else if [Qualidade] = "SERVIDOR" then 2 else if [Qualidade] = "TERCEIRIZADO" then 3 else if [Qualidade] = "ESTAGIARIO" then 4 else 5, Int64.Type)
in
    ComOrdem''')
    table('DimProduto', [('ColunaOrigem', 'string', {'hidden': True}), ('Produto', 'string', {'sort': 'Ordem'}),
                         ('Ordem', 'int64', {'hidden': True})], 'CatalogoProdutos')
    measures = [
        ('Contas na base', 'COALESCE(COUNTROWS(FatoContas), 0)', '0', 'Contas distintas na fotografia atual do job. Uma linha por UPN.'),
        ('Contas licenciadas', 'COALESCE(DISTINCTCOUNT(FatoLicencas[UPN]), 0)', '0', 'UPNs com ao menos um dos produtos no contexto selecionado.'),
        ('Contas sem licença', 'COALESCE(CALCULATE(COUNTROWS(FatoContas), FatoContas[Total de licenças] = 0), 0)', '0', 'Contas sem qualquer produto do cadastro.'),
        ('Licenças atribuídas', 'COALESCE(SUM(FatoLicencas[Quantidade]), 0)', '0', 'Cada combinação de conta e produto conta como uma atribuição.'),
        ('Cobertura', 'DIVIDE([Contas licenciadas], [Contas na base])', '0%', 'Contas com os produtos selecionados divididas por todas as contas do recorte organizacional.'),
        ('Contas para revisão', 'COALESCE(CALCULATE(COUNTROWS(FatoContas), FatoContas[Revisar] = 1), 0)', '0', 'UPNs distintos com ao menos um motivo para revisão cadastral. Não mede uso ou ociosidade.'),
        ('Inativas com licença', 'COALESCE(CALCULATE(COUNTROWS(FatoContas), FatoContas[Situação] = "Inativa", FatoContas[Total de licenças] > 0), 0)', '0', 'Situação funcional inativa e ao menos um produto atribuído.'),
        ('Não informadas com licença', 'COALESCE(CALCULATE(COUNTROWS(FatoContas), FatoContas[Situação] = "Não informada", FatoContas[Total de licenças] > 0), 0)', '0', 'Situação funcional não informada e ao menos um produto atribuído.'),
        ('Ativas desabilitadas', 'COALESCE(CALCULATE(COUNTROWS(FatoContas), FatoContas[Situação] = "Ativa", FatoContas[Conta] = "Desabilitada"), 0)', '0', 'Situação funcional ativa e conta desabilitada, com ou sem licença.'),
        ('Desabilitadas com licença', 'COALESCE(CALCULATE(COUNTROWS(FatoContas), FatoContas[Conta] = "Desabilitada", FatoContas[Total de licenças] > 0), 0)', '0', 'Conta desabilitada e ao menos um produto atribuído.'),
        ('Nota de cobertura', 'IF([Contas na base] = 0, "Sem contas no recorte", FORMAT([Cobertura], "0%") & " de cobertura no recorte")', None, None),
        ('Nota da base', 'FORMAT([Contas sem licença], "0") & " contas sem licença"', None, None),
        ('Nota da revisão', '"Contagem de contas, sem duplicação"', None, None),
        ('Nota das licenças', '"Uma conta pode ter vários produtos"', None, None),
    ]
    # These four named KPIs remain explicit; generic totals and combinations use the catalog.
    for product, short in [('M365 E5', 'E5'), ('M365 F3', 'F3'), ('Copilot', 'Copilot'), ('M365 F5 Security', 'F5 Security')]:
        measures.append((short, f'CALCULATE([Licenças atribuídas], KEEPFILTERS(DimProduto[ColunaOrigem] = "{product}"))', '0', None))
    measures += [
        ('Taxa de revisão', 'DIVIDE([Contas para revisão], CALCULATE([Contas na base], REMOVEFILTERS(FatoContas[Motivo da revisão]), REMOVEFILTERS(FatoContas[Revisar])))', '0.0%', 'Contas para revisão sobre a população do recorte, incluindo a combinação de produtos; selecionar um motivo não reduz o denominador.'),
        ('Adoção de Copilot', 'DIVIDE([Copilot], [Contas na base])', '0.0%', 'Proporção de contas com Copilot atribuído. Não mede utilização.'),
        ('Nota do Copilot', 'IF([Contas na base] = 0, "Sem contas no recorte", FORMAT([Adoção de Copilot], "0.0%", "pt-BR") & " das contas do recorte")', None, None),
        ('Nota da taxa de revisão', 'IF(ISBLANK([Taxa de revisão]), "Sem contas no recorte", FORMAT([Taxa de revisão], "0.0%", "pt-BR") & " das contas do recorte")', None, None),
        ('Unidades no recorte', 'COALESCE(DISTINCTCOUNT(FatoContas[Unidade]), 0)', '#,0', None),
        ('Subunidades no recorte', 'COALESCE(DISTINCTCOUNT(FatoContas[OrganizacaoKey]), 0)', '#,0', 'Pares distintos de unidade e subunidade.'),
        ('E5 e F3 simultâneos', 'COALESCE(CALCULATE(COUNTROWS(FatoContas), FatoContas[M365 E5] = 1, FatoContas[M365 F3] = 1), 0)', '#,0', 'Combinação para análise. Não comprova redundância ou irregularidade.'),
        ('Nota da combinação', 'FORMAT([E5 e F3 simultâneos], "#,0") & " contas com E5 + F3 simultâneos · conferir contexto e regras contratuais antes de agir."', None, None),
        ('Orientação de subunidades', 'IF(HASONEVALUE(DimOrganizacao[Unidade]), "Detalhe de " & SELECTEDVALUE(DimOrganizacao[Unidade]), "Selecione uma unidade na tabela ou no filtro acima")', None, None),
    ]
    for name, source in [('Contas exibidas', 'Contas na base'), ('Licenças exibidas', 'Licenças atribuídas'),
                         ('Copilot exibido', 'Adoção de Copilot'), ('Revisão exibida', 'Contas para revisão'), ('Taxa exibida', 'Taxa de revisão')]:
        measures.append((name, f'IF([Contas na base] > 0, [{source}])', '0.0%' if 'Taxa' in name or 'Copilot' in name else '#,0', None))
    for name, source in [('Contas da subunidade', 'Contas na base'), ('Licenças da subunidade', 'Licenças atribuídas'), ('Revisão da subunidade', 'Contas para revisão')]:
        measures.append((name, f'IF(HASONEFILTER(DimOrganizacao[Unidade]) && [Contas na base] > 0, [{source}])', '#,0', None))
    for name, source in [('Top 10 unidades', 'Licenças atribuídas'), ('Top 10 revisão', 'Contas para revisão')]:
        expression = f'''VAR Ranking = TOPN(10, FILTER(ALLSELECTED(DimOrganizacao[Unidade]), CALCULATE([{source}]) > 0), [{source}], DESC, DimOrganizacao[Unidade], ASC) RETURN IF(CONTAINS(Ranking, DimOrganizacao[Unidade], SELECTEDVALUE(DimOrganizacao[Unidade])), [{source}])'''
        measures.append((name, expression, '#,0', 'Até dez unidades dentro dos filtros ativos; desempate pelo nome.'))
    measures = [(name, expression, '#,0' if fmt == '0' else fmt, description) for name, expression, fmt, description in measures]
    table('Indicadores', [('Valor', 'int64', {'hidden': True})], '#table(type table [Valor = Int64.Type], {{0}})', measures=measures)

    relationships = []
    # Dimensions are shared; the two fact tables are never joined to each other.
    for fact in ['FatoContas', 'FatoLicencas']:
        for dimension, fk, pk in [('DimConta', 'UPN', 'UPN'), ('DimOrganizacao', 'OrganizacaoKey', 'OrganizacaoKey'),
                                  ('DimVinculo', 'Qualidade', 'Qualidade'), ('DimEmpresa', 'Empresa', 'Empresa'),
                                  ('DimCombinacao', 'Produtos', 'Produtos')]:
            relationships += [f'relationship r_{fact}_{dimension}', '\tfromCardinality: many',
                              '\ttoCardinality: one', '\tcrossFilteringBehavior: oneDirection',
                              f'\tfromColumn: {quoted(fact)}.{quoted(fk)}',
                              f'\ttoColumn: {quoted(dimension)}.{quoted(pk)}', '']
    relationships += ['relationship r_FatoLicencas_DimProduto', '\tfromCardinality: many', '\ttoCardinality: one',
                      '\tcrossFilteringBehavior: oneDirection', "\tfromColumn: FatoLicencas.Produto", '\ttoColumn: DimProduto.Produto', '']
    relpath = MODEL / 'definition/relationships.tmdl'
    relpath.write_text('\n'.join(relationships), encoding='utf-8')

    modelpath = MODEL / 'definition/model.tmdl'
    model = modelpath.read_text(encoding='utf-8')
    model = model.replace('annotation __PBI_TimeIntelligenceEnabled = 1', 'annotation __PBI_TimeIntelligenceEnabled = 0')
    model = model.replace('culture: en-US', 'culture: pt-BR')
    # Desktop normalizes quoted names on save; reconcile names, not literal lines.
    model = '\n'.join(line for line in model.splitlines()
                      if not (line.startswith('ref table ') and line[10:].strip().strip("'") in new_names | LEGACY_TABLES))
    model = model.rstrip()
    for name in sorted(new_names):
        model += f'\nref table {quoted(name)}'
    model += '\n'
    query_order = ['CaminhoPasta', 'CatalogoProdutos', 'telemetria'] + sorted(new_names)
    model = re.sub(r'^annotation PBI_QueryOrder = .*$',
                   'annotation PBI_QueryOrder = ' + json.dumps(query_order, ensure_ascii=False), model, flags=re.M)
    modelpath.write_text(model, encoding='utf-8')

    diagram_path = MODEL / 'diagramLayout.json'
    diagram = json.loads(diagram_path.read_text(encoding='utf-8-sig'))
    for view in diagram['diagrams']:
        view['nodes'] = [node for node in view['nodes'] if node['nodeIndex'] not in LEGACY_TABLES]
    write_json(diagram_path, diagram)


def literal(value):
    if isinstance(value, bool):
        encoded = 'true' if value else 'false'
    elif isinstance(value, int):
        encoded = f'{value}L'
    elif isinstance(value, float):
        encoded = f'{value}D'
    else:
        encoded = quoted(value)
    return {'expr': {'Literal': {'Value': encoded}}}


def color(value):
    return {'solid': {'color': literal(value)}}


def obj(**values):
    return [{'properties': values}]


def column(entity, name):
    return {'Column': {'Expression': {'SourceRef': {'Entity': entity}}, 'Property': name}}


def measure(name):
    return {'Measure': {'Expression': {'SourceRef': {'Entity': 'Indicadores'}}, 'Property': name}}


def projection(field, display=None, active=False):
    item = field.get('Column', field.get('Measure'))
    ref = item['Expression']['SourceRef']['Entity'] + '.' + item['Property']
    result = {'field': field, 'queryRef': ref, 'nativeQueryRef': display or item['Property']}
    if display:
        result['displayName'] = display
    if active:
        result['active'] = True
    return result


class Page:
    def __init__(self, index, title, subtitle):
        self.index, self.id, self.visuals = index, PAGE_IDS[index], []
        self.folder = PAGES / self.id
        # Remove only the visual definitions belonging to these redesigned pages.
        # A complete copy of the initial report has already been retained in Temp.
        for path in self.folder.glob('visuals/*/visual.json'):
            resolved = path.resolve()
            if not resolved.is_relative_to(PAGES.resolve()):
                raise RuntimeError('Visual path escaped the report workspace')
            path.unlink()
        write_json(self.folder / 'page.json', {
            '$schema': 'https://developer.microsoft.com/json-schemas/fabric/item/report/definition/page/2.1.0/schema.json',
            'name': self.id, 'displayName': title, 'displayOption': 'FitToPage', 'height': 1000, 'width': 1600,
            'objects': {'background': obj(color=color(LIGHT), transparency=literal(0)),
                        'outspace': obj(color=color('#E8EDF4'))},
        })
        self.panel('sidebar', 0, 0, 224, 1000, NAVY, radius=0, border=False)
        self.panel('brand-tile', 30, 38, 42, 42, '#264563', radius=10, border=False)
        self.text('brand-icon', 'T', 35, 41, 32, 34, 22, WHITE, bold=True, align='center')
        self.text('brand', 'TELEMETRIA', 84, 38, 130, 26, 12, WHITE, bold=True)
        self.text('brand-caption', 'Microsoft 365', 84, 64, 130, 22, 9, '#A8BED4')
        self.text('nav-caption', 'PAINEL DE LICENÇAS', 30, 160, 180, 22, 9, '#91AAC2', bold=True)
        for i, label in enumerate(['01   Visão geral', '02   Unidades', '03   Produtos', '04   Revisão']):
            self.button('nav-' + str(i), label, 20, 208 + i * 60, 184, 46, PAGE_IDS[i], i == index)
        self.panel('sidebar-rule', 30, 831, 164, 1, '#31465E', radius=0, border=False)
        self.text('sidebar-note', 'UMA EXECUÇÃO DO JOB', 30, 852, 174, 22, 9, '#B3C7DA', bold=True)
        self.text('sidebar-note-detail', 'Distribuição de licenças\ne situação cadastral.', 30, 883, 174, 60, 10, '#91AAC2')
        self.text('eyebrow', 'GESTÃO DE LICENÇAS  /  MICROSOFT 365', 264, 36, 850, 24, 10, TEAL, bold=True)
        self.text('page-title', title, 264, 65, 900, 53, 30, NAVY, bold=True)
        self.text('page-subtitle', subtitle, 264, 125, 1250, 28, 12, MUTED)
        self.panel('demo-badge', 1326, 40, 234, 32, '#E6EDF5', radius=8, border=False)
        self.text('demo-label', 'BASE ANONIMIZADA', 1336, 44, 214, 24, 9, '#4F6680', bold=True, align='center')
        for i, (entity, field, label) in enumerate([
            ('DimOrganizacao', 'Unidade', 'Unidade'), ('DimVinculo', 'Vínculo', 'Vínculo funcional'), ('DimEmpresa', 'Empresa', 'Empresa')
        ] + ([('FatoContas', 'Motivo da revisão', 'Motivo da revisão')] if index == 3 else [('DimCombinacao', 'Produtos', 'Combinação de produtos')])):
            self.slicer('filter-' + str(i), entity, field, label, 264 + i * 328, 181, 312, 68)
        self.text('footer', 'Fonte: fake-data.csv  ·  Fotografia única do job  ·  Filtros com busca  ·  Ctrl + clique na navegação lateral no Desktop.',
                  264, 960, 1270, 22, 9, MUTED)

    def add(self, key, kind, x, y, w, h, objects=None, query=None, container=None):
        name = identifier(self.id + '/' + key)
        visual = {'visualType': kind, 'drillFilterOtherVisuals': True,
                  'visualContainerObjects': {
                      'title': obj(show=literal(False)),
                      'background': obj(show=literal(False)),
                      'border': obj(show=literal(False)),
                      'visualHeader': obj(show=literal(False)),
                      'general': obj(keepLayerOrder=literal(True)),
                      'padding': obj(top=literal(0), bottom=literal(0), left=literal(0), right=literal(0)),
                  }}
        if objects:
            visual['objects'] = objects
        if query:
            visual['query'] = query
        if container:
            visual['visualContainerObjects'].update(container)
        data = {'$schema': 'https://developer.microsoft.com/json-schemas/fabric/item/report/definition/visualContainer/2.7.0/schema.json',
                'name': name, 'position': {'x': x, 'y': y, 'z': len(self.visuals), 'width': w, 'height': h, 'tabOrder': len(self.visuals)},
                'visual': visual}
        self.visuals.append((key, data))
        return data

    def panel(self, key, x, y, w, h, fill=WHITE, radius=14, border=True):
        return self.add(key, 'shape', x, y, w, h,
                        objects={'shape': obj(tileShape=literal('rectangle')),
                                 'fill': obj(show=literal(False)), 'outline': obj(show=literal(False)),
                                 'text': obj(show=literal(False))},
                        container={'background': obj(show=literal(True), color=color(fill), transparency=literal(0)),
                                   'border': obj(show=literal(border), color=color(LINE), radius=literal(radius), width=literal(1))})

    def text(self, key, value, x, y, w, h, size=12, fill=TEXT, bold=False, align='left'):
        paragraphs = [{'textRuns': [{'value': line, 'textStyle': {
            'fontFamily': 'Segoe UI', 'fontSize': f'{size}pt', 'color': fill,
            'fontWeight': 'bold' if bold else 'normal'}}], 'horizontalTextAlignment': align}
                      for line in value.split('\n')]
        return self.add(key, 'textbox', x, y, w, h, objects={'general': obj(paragraphs=paragraphs)})

    def button(self, key, label, x, y, w, h, target, selected):
        self.panel(key + '-background', x, y, w, h, '#294A69' if selected else NAVY, radius=8, border=False)
        self.text(key + '-label', label, x + 14, y + 10, w - 24, h - 14,
                  11, WHITE if selected else '#B1C6DA', bold=selected)
        return self.add(key, 'actionButton', x, y, w, h, objects={
            'shape': obj(tileShape=literal('rectangle'), rectangleRoundedCurve=literal(10)),
            'fill': [{'selector': {'id': state}, 'properties': {
                'show': literal(True), 'fillColor': color('#345675'), 'transparency': literal(transparency)}}
                     for state, transparency in [('default', 100), ('hover', 70)]],
            'outline': obj(show=literal(False)), 'icon': obj(show=literal(False)),
            'text': [{'selector': {'id': state}, 'properties': {
                'show': literal(False), 'text': literal(label), 'fontFamily': literal('Segoe UI'),
                'fontSize': literal(11), 'fontColor': color(WHITE if selected else '#B1C6DA'),
                'bold': literal(selected), 'horizontalAlignment': literal('left'), 'leftMargin': literal(14),
            }} for state in ['default', 'hover']],
        }, container={'visualLink': obj(show=literal(True), type=literal('PageNavigation'), navigationSection=literal(target), enabledTooltip=literal(label)),
                      'general': obj(keepLayerOrder=literal(True), altText=literal(label))})

    def slicer(self, key, entity, field, label, x, y, w, h):
        self.panel(key + '-panel', x, y, w, h, radius=10)
        result = self.add(key, 'slicer', x + 14, y + 8, w - 28, h - 16, objects={
            'general': obj(selfFilterEnabled=literal(True)),
            'data': obj(mode=literal('Dropdown')),
            'header': obj(show=literal(True), text=literal(label), fontColor=color(MUTED), textSize=literal(10), fontFamily=literal('Segoe UI')),
            'items': obj(fontColor=color(TEXT), textSize=literal(11), fontFamily=literal('Segoe UI'), padding=literal(4)),
            'selection': obj(singleSelect=literal(False), selectAllCheckboxEnabled=literal(True)),
        }, query={'queryState': {'Values': {'projections': [projection(column(entity, field), active=True)]}}})
        result['visual']['syncGroup'] = {'groupName': entity + '-' + field, 'fieldChanges': True, 'filterChanges': True}
        return result

    def value(self, key, mname, x, y, w, h, size=38, fill=NAVY):
        return self.add(key, 'card', x, y, w, h, objects={
            'labels': obj(fontSize=literal(size), fontFamily=literal('Segoe UI Semibold'), color=color(fill), labelDisplayUnits=literal(1), labelPrecision=literal(0)),
            'categoryLabels': obj(show=literal(False)), 'wordWrap': obj(show=literal(True)),
        }, query={'queryState': {'Values': {'projections': [projection(measure(mname))]}}})

    def kpi(self, index, title, mname, note=None, dynamic_note=None, fill=WHITE, accent=BLUE):
        x, y, w = 264 + index * 328, 274, 312
        self.panel('kpi-' + str(index), x, y, w, 144, fill)
        self.panel('kpi-accent-' + str(index), x + 20, y + 20, 4, 18, accent, radius=2, border=False)
        self.text('kpi-title-' + str(index), title, x + 34, y + 18, w - 48, 28, 10, TEXT, bold=True)
        self.value('kpi-value-' + str(index), mname, x + 20, y + 51, w - 40, 52, 37, accent if fill != WHITE else NAVY)
        if dynamic_note:
            self.value('kpi-note-' + str(index), dynamic_note, x + 12, y + 111, w - 24, 23, 10, MUTED)
        elif note:
            self.text('kpi-note-' + str(index), note, x + 12, y + 114, w - 24, 23, 9, MUTED, align='center')

    def chart_panel(self, key, title, subtitle, x, y, w, h):
        self.panel(key + '-panel', x, y, w, h)
        self.text(key + '-title', title, x + 22, y + 18, w - 44, 30, 15, NAVY, bold=True)
        self.text(key + '-subtitle', subtitle, x + 22, y + 55, w - 44, 24, 10, MUTED)

    def bar(self, key, entity, category, mname, x, y, w, h, fill=BLUE, percent=False, extra_tooltips=None):
        query = {'queryState': {
            'Category': {'projections': [projection(column(entity, category), active=True)]},
            'Y': {'projections': [projection(measure(mname))]},
            'Tooltips': {'projections': [projection(measure(name)) for name in extra_tooltips or []]},
        }, 'sortDefinition': {'sort': [{'field': measure(mname), 'direction': 'Descending'}], 'isDefaultSort': True}}
        if not extra_tooltips:
            del query['queryState']['Tooltips']
        value_axis = dict(show=literal(True), showAxisTitle=literal(False), labelColor=color(MUTED),
                          fontSize=literal(10), gridlineShow=literal(True), gridlineColor=color('#E9EEF4'),
                          gridlineStyle=literal('dotted'), start=literal(0), labelDisplayUnits=literal(1))
        if percent:
            value_axis['end'] = literal(1)
        return self.add(key, 'clusteredBarChart', x, y, w, h, objects={
            'dataPoint': obj(defaultColor=color(fill)), 'legend': obj(show=literal(False)),
            'labels': obj(show=literal(True), color=color(TEXT), fontFamily=literal('Segoe UI Semibold'), fontSize=literal(12),
                          labelDisplayUnits=literal(1), labelPrecision=literal(0), labelPosition=literal('OutsideEnd')),
            'categoryAxis': obj(show=literal(True), showAxisTitle=literal(False), labelColor=color(TEXT),
                                fontFamily=literal('Segoe UI'), fontSize=literal(11), innerPadding=literal(45), maxMarginFactor=literal(38)),
            'valueAxis': obj(**value_axis),
        }, query=query)

    def finish(self):
        # Cross-filter rather than cross-highlight: the displayed ratio has one clear context.
        charts = [data for _, data in self.visuals if data['visual']['visualType'] in {'clusteredBarChart', 'pivotTable', 'tableEx'}]
        data_visuals = [data for _, data in self.visuals if 'query' in data['visual'] and data['visual']['visualType'] != 'slicer']
        page = json.loads((self.folder / 'page.json').read_text(encoding='utf-8'))
        page['visualInteractions'] = [{'source': source['name'], 'target': target['name'], 'type': 'NoFilter' if source['name'] == identifier(self.id + '/product-bars') else 'DataFilter'}
                                      for source in charts for target in data_visuals if source != target]
        write_json(self.folder / 'page.json', page)
        for key, data in self.visuals:
            write_json(self.folder / 'visuals' / data['name'] / 'visual.json', data)


def data_table(p, key, fields, x, y, w, h, sort=None, row_padding=8):
    """Fields contain (semantic field, display label, width)."""
    return p.add(key, 'tableEx', x, y, w, h, objects={
        'columnHeaders': obj(fontFamily=literal('Segoe UI Semibold'), fontSize=literal(10), fontColor=color(NAVY),
                             backColor=color('#EEF3F9'), wordWrap=literal(True), autoSizeColumnWidth=literal(False), outlineStyle=literal(0)),
        'values': obj(fontFamily=literal('Segoe UI'), fontSize=literal(11), fontColorPrimary=color(TEXT), fontColorSecondary=color(TEXT),
                      backColorPrimary=color(WHITE), backColorSecondary=color('#F6F8FB'), wordWrap=literal(False)),
        'grid': obj(gridVertical=literal(False), gridHorizontal=literal(True), gridHorizontalColor=color(LINE), rowPadding=literal(row_padding), outlineStyle=literal(0)),
        'total': obj(totals=literal(False)),
        'columnWidth': [{'selector': {'metadata': projection(field)['queryRef']}, 'properties': {'value': literal(width)}} for field, _, width in fields],
    }, query={'queryState': {'Values': {'projections': [projection(field, label) for field, label, _ in fields]}},
              'sortDefinition': {'sort': [{'field': sort or fields[0][0], 'direction': 'Descending' if sort else 'Ascending'}], 'isDefaultSort': True}})


def note(p, key, text, warning=False):
    p.panel(key, 264, 912, 1296, 34, '#FFF0D8' if warning else '#E8EFF8', radius=8, border=False)
    p.text(key + '-text', text, 278, 917, 1268, 24, 10, '#8A621F' if warning else '#49637F')


def build_visual_pages():
    p = Page(0, 'Visão geral', 'O tamanho da base, a concentração das licenças e as contas que pedem conferência.')
    p.kpi(0, 'CONTAS NO RECORTE', 'Contas na base', note='Uma conta por UPN')
    p.kpi(1, 'LICENÇAS ATRIBUÍDAS', 'Licenças atribuídas', note='Uma conta pode ter vários produtos', accent=TEAL)
    p.kpi(2, 'CONTAS COM COPILOT', 'Copilot', dynamic_note='Nota do Copilot', accent=PURPLE)
    p.kpi(3, 'CONTAS PARA REVISÃO', 'Contas para revisão', dynamic_note='Nota da taxa de revisão', fill='#FFF7EA', accent=AMBER)
    p.chart_panel('products', 'Distribuição por produto', 'Quatro produtos · cada barra conta atribuições', 264, 442, 552, 450)
    p.bar('product-bars', 'DimProduto', 'Produto', 'Licenças atribuídas', 282, 535, 512, 326)
    p.chart_panel('units', 'Onde estão as licenças', 'Top 10 unidades por atribuições · os cartões incluem todas as unidades', 836, 442, 724, 450)
    p.bar('unit-bars', 'DimOrganizacao', 'Unidade', 'Top 10 unidades', 854, 535, 682, 326, fill=TEAL,
          extra_tooltips=['Contas na base', 'Copilot', 'Taxa de revisão'])
    note(p, 'overview-note', 'EXPLORE  ·  Clique em uma unidade do ranking para filtrar a página. Use Unidades para consultar a lista completa.')
    p.finish()

    p = Page(1, 'Unidades', 'Compare unidades de tamanhos diferentes e abra apenas as subunidades que deseja analisar.')
    p.kpi(0, 'UNIDADES NO RECORTE', 'Unidades no recorte', note='Lista completa na tabela abaixo')
    p.kpi(1, 'SUBUNIDADES NO RECORTE', 'Subunidades no recorte', note='Identificadas junto à unidade de origem', accent=TEAL)
    p.kpi(2, 'CONTAS NO RECORTE', 'Contas na base', note='Responde à seleção de uma unidade', accent=PURPLE)
    p.kpi(3, 'CONTAS PARA REVISÃO', 'Contas para revisão', dynamic_note='Nota da taxa de revisão', accent=AMBER)
    p.chart_panel('units', 'Compare as unidades', 'Clique em uma linha para abrir suas subunidades · cabeçalhos ordenam', 264, 442, 778, 450)
    data_table(p, 'units-table', [
        (column('DimOrganizacao', 'Unidade'), 'Unidade', 145), (measure('Contas exibidas'), 'Contas', 90),
        (measure('Licenças exibidas'), 'Licenças', 100), (measure('Copilot exibido'), '% Copilot', 110),
        (measure('Revisão exibida'), 'Revisão', 90), (measure('Taxa exibida'), '% revisão', 110),
    ], 282, 535, 742, 334, measure('Contas exibidas'))
    p.chart_panel('subunits', 'Subunidades da unidade', 'Detalhamento sob demanda · uma unidade por vez', 1062, 442, 498, 450)
    p.value('subunit-instruction', 'Orientação de subunidades', 1080, 530, 462, 45, 11, TEAL)
    data_table(p, 'subunits-table', [
        (column('DimOrganizacao', 'Subunidade'), 'Subunidade', 154),
        (measure('Contas da subunidade'), 'Contas', 85),
        (measure('Licenças da subunidade'), 'Licenças', 90),
        (measure('Revisão da subunidade'), 'Revisão', 85),
    ], 1080, 586, 462, 283, measure('Contas da subunidade'))
    note(p, 'units-note', 'LEITURA  ·  % revisão compara proporções; Revisão mostra o volume. Nomes iguais de subunidade não são agrupados entre unidades.')
    p.finish()

    p = Page(2, 'Produtos', 'Entenda as combinações de licenças e como elas se distribuem entre os vínculos e empresas.')
    for i, (title, mname, accent) in enumerate([
        ('M365 E5', 'E5', BLUE), ('M365 F3', 'F3', TEAL), ('COPILOT', 'Copilot', PURPLE), ('M365 F5 SECURITY', 'F5 Security', '#53738F')
    ]):
        p.kpi(i, title, mname, note='Contas com o produto atribuído', accent=accent)
    p.chart_panel('combinations', 'Combinações de produtos', 'Contas em cada combinação · clique para filtrar', 264, 442, 610, 450)
    p.bar('combination-bars', 'DimCombinacao', 'Produtos', 'Contas na base', 282, 535, 574, 326, fill=PURPLE,
          extra_tooltips=['Licenças atribuídas', 'Contas para revisão'])
    p.chart_panel('vinculos', 'Produtos por vínculo', 'Use Empresa no filtro acima para investigar a distribuição', 894, 442, 666, 450)
    data_table(p, 'vinculos-table', [
        (column('DimVinculo', 'Vínculo'), 'Vínculo', 155),
        (measure('E5'), 'E5', 72), (measure('F3'), 'F3', 66),
        (measure('Copilot'), 'Copilot', 82), (measure('F5 Security'), 'F5 Sec.', 81),
        (measure('Adoção de Copilot'), '% Copilot', 108),
    ], 912, 535, 630, 328, measure('Adoção de Copilot'), row_padding=15)
    p.panel('products-note', 264, 912, 1296, 34, '#E8EFF8', radius=8, border=False)
    p.value('combination-note', 'Nota da combinação', 278, 916, 1268, 25, 10, '#49637F')
    p.finish()

    p = Page(3, 'Revisão', 'Priorize pelo volume e pela proporção de contas; consulte o motivo antes de tomar uma decisão.')
    p.kpi(0, 'CONTAS PARA REVISÃO', 'Contas para revisão', dynamic_note='Nota da taxa de revisão', fill='#FFF7EA', accent=AMBER)
    p.kpi(1, 'INATIVAS COM LICENÇA', 'Inativas com licença', note='Situação funcional inativa', accent=AMBER)
    p.kpi(2, 'SITUAÇÃO NÃO INFORMADA', 'Não informadas com licença', note='Situação funcional a confirmar', accent=PURPLE)
    p.kpi(3, 'DESABILITADAS COM LICENÇA', 'Desabilitadas com licença', note='Os motivos podem coincidir', accent=TEAL)
    p.chart_panel('review-units', 'Onde começar a revisão', 'Top 10 por contas · passe o mouse para ver a taxa', 264, 442, 418, 450)
    p.bar('review-bars', 'DimOrganizacao', 'Unidade', 'Top 10 revisão', 282, 535, 382, 326, fill='#B68130',
          extra_tooltips=['Taxa de revisão', 'Contas na base'])
    p.chart_panel('review', 'Contas para conferência', 'Somente registros sinalizados · selecione unidade ou motivo para reduzir a lista', 702, 442, 858, 450)
    review = data_table(p, 'review-table', [
        (column('FatoContas', 'UPN'), 'Conta / UPN', 190),
        (column('FatoContas', 'Unidade'), 'Unidade', 110),
        (column('FatoContas', 'Subunidade'), 'Subunidade', 115),
        (column('FatoContas', 'Produtos'), 'Produtos', 145),
        (column('FatoContas', 'Motivo da revisão'), 'Motivo da revisão', 240),
    ], 720, 535, 822, 334, row_padding=10)
    review['visual']['objects']['values'][0]['properties'].update(wordWrap=literal(True), fontSize=literal(10))
    review['filterConfig'] = {'filters': [{
        'name': identifier('filter-revisar'), 'field': column('FatoContas', 'Revisar'), 'type': 'Categorical',
        'howCreated': 'User', 'isHiddenInViewMode': True,
        'filter': {'Version': 2, 'From': [{'Name': 'r', 'Entity': 'FatoContas', 'Type': 0}], 'Where': [{'Condition': {'In': {
            'Expressions': [{'Column': {'Expression': {'SourceRef': {'Source': 'r'}}, 'Property': 'Revisar'}}],
            'Values': [[{'Literal': {'Value': '1L'}}]],
        }}}]},
    }]}
    reason_slicer = next(data for key, data in p.visuals if key == 'filter-3')
    reason_slicer['filterConfig'] = review['filterConfig']
    note(p, 'review-note', 'CRITÉRIO  ·  Alertas cadastrais, sem medição de uso. A contagem total considera cada conta uma vez; os motivos podem coincidir.', warning=True)
    p.finish()


def build_report():
    build_visual_pages()

    write_json(PAGES / 'pages.json', {
        '$schema': 'https://developer.microsoft.com/json-schemas/fabric/item/report/definition/pagesMetadata/1.1.0/schema.json',
        'pageOrder': PAGE_IDS, 'activePageName': PAGE_IDS[0],
    })
    theme = {
        'name': 'Telemetria · Clareza', 'dataColors': [BLUE, TEAL, PURPLE, '#53738F', '#D19A43', '#68AAB0'],
        'background': WHITE, 'foreground': TEXT, 'tableAccent': TEAL, 'good': TEAL, 'neutral': '#D19A43', 'bad': '#C05D4B',
        'textClasses': {'title': {'fontFace': 'Segoe UI Semibold', 'fontSize': 15, 'color': NAVY},
                        'label': {'fontFace': 'Segoe UI', 'fontSize': 11, 'color': TEXT},
                        'callout': {'fontFace': 'Segoe UI Semibold', 'fontSize': 38, 'color': NAVY},
                        'header': {'fontFace': 'Segoe UI Semibold', 'fontSize': 12, 'color': NAVY}},
        'visualStyles': {'*': {'*': {'background': [{'show': False}], 'border': [{'show': False}],
                                     'visualHeader': [{'show': False}], 'title': [{'show': False}]}}},
    }
    write_json(REPORT / 'StaticResources/RegisteredResources/TelemetriaClareza.json', theme)
    rpath = REPORT / 'definition/report.json'
    report = json.loads(rpath.read_text(encoding='utf-8'))
    report['themeCollection']['customTheme'] = {'name': 'TelemetriaClareza', 'type': 'RegisteredResources',
        'reportVersionAtImport': {'visual': '2.7.0', 'report': '3.3.0', 'page': '2.1.0'}}
    report['resourcePackages'] = [p for p in report.get('resourcePackages', []) if p['name'] != 'RegisteredResources'] + [{
        'name': 'RegisteredResources', 'type': 'RegisteredResources', 'items': [{
            'name': 'TelemetriaClareza', 'path': 'TelemetriaClareza.json', 'type': 'CustomTheme'}],
    }]
    write_json(rpath, report)


if __name__ == '__main__':
    backup()
    build_model()
    build_report()
    print('Built four report pages, shared dimensions and separate account/license facts.')
