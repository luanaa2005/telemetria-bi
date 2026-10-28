"""Read the product rows from the model's single Power Query catalog."""

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]


def read_product_catalog(root=ROOT):
    text = (root / 'telemetria.SemanticModel/definition/expressions.tmdl').read_text(encoding='utf-8-sig')
    catalog = text.split('expression CatalogoProdutos =', 1)[1]
    catalog = re.split(r'^expression ', catalog, maxsplit=1, flags=re.M)[0]
    m_string = r'"((?:[^"\n]|"")*)"'
    pattern = rf'^\s*\{{\s*{m_string}\s*,\s*{m_string}\s*,\s*(\d+)\s*\}},?\s*$'
    rows = [(source.replace('""', '"'), name.replace('""', '"'), int(order))
            for source, name, order in re.findall(pattern, catalog, re.M)]
    assert rows, 'CatalogoProdutos must contain product rows'
    for index, label in [(0, 'source column'), (1, 'display name'), (2, 'order')]:
        values = [row[index] for row in rows]
        assert all(values) and len(values) == len(set(values)), f'Empty or duplicate catalog {label}'
    return sorted(rows, key=lambda row: (row[2], row[1]))
