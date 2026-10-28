"""Check source grain, report field references, layout bounds and native totals.

python scripts/validate_report.py [--native-results /path/to/native-results.json]
Native results are optional ADOMD query outputs from the open Desktop model.
"""

import argparse
import collections
import csv
import json
import pathlib
import re

from product_catalog import read_product_catalog

ROOT = pathlib.Path(__file__).resolve().parents[1]
CATALOG = read_product_catalog()
PRODUCTS = [source for source, name, order in CATALOG]
VINCULOS = {'autoridade': 'Autoridades', 'servidor': 'Servidores', 'terceirizado': 'Terceirizados', 'estagiario': 'Estagiários', 'nao_classificado': 'Não classificado'}


def reason(row):
    count = sum(int(row[p]) for p in PRODUCTS)
    situation = row['Situação funcional'].upper().strip()
    if count and situation == 'INATIVO':
        return 'Inativa com licença'
    if count and situation not in {'ATIVO', 'INATIVO'}:
        return 'Situação não informada com licença'
    if count and row['Conta'].lower().strip() == 'desabilitada':
        return 'Desabilitada com licença'
    if situation == 'ATIVO' and row['Conta'].lower().strip() == 'desabilitada':
        return 'Ativa, mas desabilitada'
    return None


def check(native_file=None):
    with (ROOT / 'data/fake-data.csv').open(encoding='utf-8-sig', newline='') as f:
        rows = list(csv.DictReader(f, delimiter=';'))
    assert rows, 'Source is empty'
    upns = [r['UPN'].strip().lower() for r in rows]
    assert all(upns), 'A source account has no UPN'
    assert len(set(upns)) == len(rows), 'A single job must contain one row per UPN'
    for row in rows:
        assert all(row[p] in {'0', '1'} for p in PRODUCTS), 'License flags must be 0 or 1'
        assert all(row[k].strip() for k in ['Unidade', 'Subunidade', 'Empresa', 'Qualidade']), 'Missing dimension key'

    schema = {}
    for path in (ROOT / 'telemetria.SemanticModel/definition/tables').glob('*.tmdl'):
        fields = set()
        for match in re.finditer(r"^\s*(?:column|measure)\s+(?:'((?:[^']|'')+)'|([^\s=]+))", path.read_text(encoding='utf-8-sig'), re.M):
            fields.add((match[1] or match[2]).replace("''", "'"))
        schema[path.stem] = fields
    model_refs = re.findall(r'^ref table (.+)$', (ROOT / 'telemetria.SemanticModel/definition/model.tmdl').read_text(encoding='utf-8-sig'), re.M)
    model_refs = [s.strip().strip("'") for s in model_refs]
    assert len(model_refs) == len(set(model_refs)), 'Duplicate model references'
    assert set(model_refs) == set(schema), 'Model references and table files differ'
    for table, column in re.findall(r'^\s*(?:fromColumn|toColumn): (\S+)\.(\S+)',
                                   (ROOT / 'telemetria.SemanticModel/definition/relationships.tmdl').read_text(encoding='utf-8-sig'), re.M):
        table, column = table.strip("'"), column.strip("'")
        assert column in schema[table], ('Invalid relationship', table, column)
    diagrams = json.loads((ROOT / 'telemetria.SemanticModel/diagramLayout.json').read_text(encoding='utf-8-sig'))
    assert all(node['nodeIndex'] in schema for diagram in diagrams['diagrams'] for node in diagram['nodes']), 'Stale diagram node'
    pages = ROOT / 'telemetria.Report/definition/pages'
    metadata = json.loads((pages / 'pages.json').read_text(encoding='utf-8-sig'))
    assert len(metadata['pageOrder']) == 4, 'Expected four pages'
    checked = 0
    for pid in metadata['pageOrder']:
        page = json.loads((pages / pid / 'page.json').read_text(encoding='utf-8-sig'))
        visuals = {}
        for path in (pages / pid / 'visuals').glob('*/visual.json'):
            d = json.loads(path.read_text(encoding='utf-8-sig'))
            visuals[d['name']] = d
            pos = d['position']
            assert pos['x'] >= 0 and pos['y'] >= 0, path
            assert pos['x'] + pos['width'] <= page['width'] + 0.1, path
            assert pos['y'] + pos['height'] <= page['height'] + 0.1, path
            for role in d.get('visual', {}).get('query', {}).get('queryState', {}).values():
                for projection in role.get('projections', []):
                    field = projection['field']
                    definition = field.get('Column', field.get('Measure'))
                    assert definition, ('Unexpected field type', path)
                    entity = definition['Expression']['SourceRef']['Entity']
                    assert definition['Property'] in schema[entity], (entity, definition['Property'], path)
                    assert definition['Property'] != 'Data da coleta', 'Collection date must not be a report filter'
            checked += 1
        for interaction in page.get('visualInteractions', []):
            assert interaction['source'] in visuals and interaction['target'] in visuals

    totals = {'Contas': len(rows), 'Licenciadas': sum(any(int(r[p]) for p in PRODUCTS) for r in rows),
              'Atribuicoes': sum(int(r[p]) for r in rows for p in PRODUCTS),
              'Revisao': sum(reason(r) is not None for r in rows)}
    if native_file:
        native = json.loads(pathlib.Path(native_file).read_text(encoding='utf-8-sig'))
        for key, expected in totals.items():
            assert native['totals'][0][key] == expected, (key, native['totals'], expected)
        assert native['totals'][0]['Cobertura'] == totals['Licenciadas'] / totals['Contas']
        assert native['review'] == sorted([{'UPN': r['UPN'].strip().lower(), 'Motivo': reason(r)} for r in rows if reason(r)], key=lambda r: r['UPN'])
        combinations = collections.defaultdict(list)
        for row in rows:
            combinations[(row['Unidade'], VINCULOS[row['Qualidade'].lower()], row['Empresa'])].append(row)
        assert len(native['groups']) == len(combinations), 'Missing or duplicate nonempty organization groups'
        for result in native['groups']:
            group = combinations[(result['Unidade'], result['Vinculo'], result['Empresa'])]
            expected = {'Contas': len(group), 'Licenciadas': sum(any(int(r[p]) for p in PRODUCTS) for r in group),
                        'Atribuicoes': sum(int(r[p]) for r in group for p in PRODUCTS), 'Revisao': sum(reason(r) is not None for r in group)}
            assert all(result[k] == v for k, v in expected.items()), (result, expected)
        for result in native['products']:
            group = [r for r in rows if r['Unidade'] == result['Unidade']]
            source = next(source for source, name, order in CATALOG if name == result['Produto'])
            count = sum(int(r[source]) for r in group)
            assert result['Atribuicoes'] == count and result['Licenciadas'] == count, result
            assert result['Contas'] == len(group), result
            assert abs(result['Cobertura'] - count / len(group)) < 1e-12, result
        assert native['empty'] == [{'Contas': 0, 'Licenciadas': 0, 'Atribuicoes': 0, 'Revisao': 0, 'Cobertura': None}]
        profiles = collections.defaultdict(list)
        units = collections.Counter()
        for row in rows:
            profile = ' · '.join(name for product, name, order in CATALOG if int(row[product])) or 'Sem licença'
            profiles[profile].append(row)
            units[row['Unidade']] += sum(int(row[p]) for p in PRODUCTS)
        assert len(native['profiles']) == len(profiles)
        for result in native['profiles']:
            group = profiles[result['Produtos']]
            assert result['Contas'] == len(group)
            assert result['Licencas'] == sum(int(r[p]) for r in group for p in PRODUCTS)
        top10 = sorted(units.items(), key=lambda item: (-item[1], item[0]))[:10]
        assert native['top10'] == [{'Unidade': u, 'Licencas': n} for u, n in top10]
        assert native['subunitsClosed'] == [], 'Subunits must stay closed without a unit selection'
        subunits = collections.defaultdict(list)
        for row in rows:
            if row['Unidade'] == 'Unidade 074':
                subunits[row['Subunidade']].append(row)
        assert len(native['subunitsOpen']) == len(subunits)
        for result in native['subunitsOpen']:
            group = subunits[result['Subunidade']]
            assert result['Contas'] == len(group)
            assert result['Licencas'] == sum(int(r[p]) for r in group for p in PRODUCTS)
        inactive = sum(reason(r) == 'Inativa com licença' for r in rows)
        assert native['reviewReason'][0]['Contas'] == inactive
        assert abs(native['reviewReason'][0]['Taxa'] - inactive / len(rows)) < 1e-12
        print(f'Native DAX: totals, {len(native["groups"])} organization/vinculo/company groups, {len(native["products"])} product/unit groups, review details and empty filters passed.')
        print('Product combinations, exact top 10, subunit selection and review rate denominator passed.')
    print(f'Source: {totals}. PBIR references and layout: {checked} visuals passed.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--native-results')
    check(parser.parse_args().native_results)
