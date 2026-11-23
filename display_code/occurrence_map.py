"""Bind every displayed numeric occurrence across figures, tables, S1-S9, and captions."""
from centre_labels import DEFAULT_MODE
from extract_display_values import NUM, build_all
from tables import bound_products as table_bound_products
from supplement import bound_products as supp_bound_products


def all_text_products(refs: dict | None = None, mode: str = DEFAULT_MODE) -> tuple[dict[str, str], dict[str, list[int]]]:
    if refs is None:
        _, _, _, refs = build_all()
    tb_b, _ = table_bound_products(refs, mode)
    sp_b = supp_bound_products(refs, mode)
    all_b = {}
    all_b.update(tb_b)
    all_b.update(sp_b)
    texts = {k: b.text for k, b in all_b.items()}
    bindings = {k: b.slots for k, b in all_b.items()}
    return texts, bindings


def expand(slots, p, refs=None, mode: str = DEFAULT_MODE):
    if refs is None:
        _, _, _, refs = build_all()
    texts, bindings = all_text_products(refs, mode)

    f1s = refs['fig1_slots']
    f2s = refs['fig2_slots']
    fS1s = refs['figS1_slots']

    byfile: dict[str, list[int]] = dict(bindings)
    byfile['figures/Figure1.svg'] = (
        f1s['A']
        + f1s['B_segs'] + f1s['B_right'] + f1s['B_header'] + f1s['B_axis']
        + f1s['C'] + f1s['C_header'] + f1s['C_axis']
        + f1s['D'] + f1s['D_header'] + f1s['D_axis']
    )
    byfile['figures/Figure2.svg'] = (
        f2s['A_header'] + f2s['A_rows'] + f2s['A_axis']
        + f2s['B_contours'] + f2s['B_x_axis'] + f2s['B_y_axis']
    )
    byfile['figures/FigureS1.svg'] = fS1s['top']

    rows = []
    for path, indices in byfile.items():
        if path in texts:
            actual = NUM.findall(texts[path])
            wanted = [slots[i]['value_as_displayed'] for i in indices]
            assert actual == wanted, (path, len(actual), len(wanted), actual[:10], wanted[:10])
        for ordinal, i in enumerate(indices):
            row = dict(slots[i])
            row.update(artifact_path=path, ordinal=ordinal, occurrence=ordinal, source_slot=i)
            # Maintain exact v6 columns in display_values.csv
            row.pop('ordinal', None)
            rows.append(row)
    return rows
