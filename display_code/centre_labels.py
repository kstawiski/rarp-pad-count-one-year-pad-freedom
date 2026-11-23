"""Centre name mapping for double-blind (masked) and unmasked (named) displays."""
import os

DEFAULT_MODE = os.environ.get('MS1_CENTRE_MODE', 'masked')

CENTRE_LABELS = {
    'masked': {
        'Bełchatów': 'Centre A (Poland)',
        'Salve Medica': 'Centre B (Poland)',
        "Brigham and Women's Hospital": 'Centre C (United States)',
    },
    'named': {
        'Bełchatów': 'Bełchatów Hospital, Poland',
        'Salve Medica': 'SalveMedica, Łódź, Poland',
        "Brigham and Women's Hospital": "Brigham and Women's Hospital, USA",
    },
}

CENTRE_ORDER = ['Bełchatów', 'Salve Medica', "Brigham and Women's Hospital"]


def centre_label(raw_key, mode=DEFAULT_MODE):
    if mode not in CENTRE_LABELS:
        raise ValueError(f'Unknown centre label mode: {mode!r}')
    return CENTRE_LABELS[mode][raw_key]
