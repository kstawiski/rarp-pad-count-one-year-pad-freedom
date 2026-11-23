"""Rebuild and verify all manuscript 1 displays from completed-window aggregate records."""
from pathlib import Path
import json
import os
import shutil
import subprocess
import sys
import tempfile

TASK = Path(__file__).resolve().parents[1]
PY = '/home/konrad/.venvs/konsta-research-py314/bin/python'
FONT_DIR = '/home/konrad/.cache/R/renv/library/OmicSelector-c9f55c96/linux-ubuntu-noble/R-4.5/x86_64-pc-linux-gnu/rmarkdown/rmd/h/bootstrap/css/fonts'


def _find_plugin() -> Path:
    base = Path('/home/konrad/.claude2/plugins/cache/konsta-research/konsta-research')
    candidates = sorted(p for p in base.iterdir() if p.is_dir() and (p / 'scripts/figure_geometry.py').is_file())
    if not candidates:
        raise FileNotFoundError(f'No konsta-research plugin found under {base}')
    return candidates[-1]


PLUGIN = _find_plugin()


def _prepare_env(tmpdir: Path) -> dict[str, str]:
    env = dict(os.environ)
    fc_check = subprocess.run(['fc-match', '-f', '%{family}', 'Open Sans'], capture_output=True, text=True, check=False)
    if fc_check.stdout.strip() != 'Open Sans' and Path(FONT_DIR).is_dir():
        fc_path = tmpdir / 'fonts.conf'
        fc_path.write_text(
            '<?xml version="1.0"?>\n<!DOCTYPE fontconfig SYSTEM "fonts.dtd">\n<fontconfig>\n'
            '  <include ignore_missing="yes">/etc/fonts/fonts.conf</include>\n'
            f'  <dir>{FONT_DIR}</dir>\n</fontconfig>\n',
            encoding='utf8',
        )
        env['FONTCONFIG_FILE'] = str(fc_path)
    return env


def run(args, log, env, append=False, check=True):
    (TASK / 'logs').mkdir(exist_ok=True)
    with (TASK / 'logs' / log).open('a' if append else 'w', encoding='utf8') as fh:
        proc = subprocess.run(args, cwd=TASK, env=env, stdout=fh, stderr=subprocess.STDOUT)
    if check and proc.returncode:
        raise SystemExit(f'{args[0]} failed with {proc.returncode}; see logs/{log}')
    return proc.returncode


def main():
    tmp_dir = Path(tempfile.mkdtemp(prefix='ms1-run-'))
    try:
        env = _prepare_env(tmp_dir)
        run([PY, '-B', 'scripts/extract_display_values.py'], 'EXTRACT.log', env)
        run([PY, '-B', 'scripts/tables.py'], 'TABLES.log', env)
        run([PY, '-B', 'scripts/supplement.py'], 'SUPPLEMENT.log', env)
        run(['Rscript', '--vanilla', 'scripts/figure1.R'], 'RENDER.log', env)
        run(['Rscript', '--vanilla', 'scripts/figure2.R'], 'RENDER.log', env, append=True)
        run(['Rscript', '--vanilla', 'scripts/figureS1.R'], 'RENDER.log', env, append=True)
        run([PY, '-B', 'scripts/verify_display_values.py'], 'VERIFY.log', env)
        run([PY, '-B', '-m', 'pytest', '-p', 'no:cacheprovider', '--basetemp', str(tmp_dir / 'pytest'), '-q', 'tests/test_verify_display_values.py'], 'TESTS.log', env)
        run([PY, '-B', str(PLUGIN / 'scripts/figure_integrity.py'), '--workspace', str(TASK), '--manifest', 'figure-manifest.csv', '--json'], 'FIGURE_INTEGRITY.json', env)
        run([PY, '-B', str(PLUGIN / 'scripts/figure_geometry.py'), '--svg', 'figures/Figure1.svg', '--svg', 'figures/Figure2.svg', '--svg', 'figures/FigureS1.svg', '--allowance', '0.0', '--json-out', 'logs/FIGURE_GEOMETRY.json', '--json'], 'GEOMETRY.stdout', env)
        run([PY, '-B', 'scripts/check_artifact_formats.py'], 'FORMAT_CHECKS.log', env)

        _write_output_hashes()

        result = json.loads((TASK / 'logs/VERIFY.json').read_text(encoding='utf8'))
        integ = json.loads((TASK / 'logs/FIGURE_INTEGRITY.json').read_text(encoding='utf8'))
        geom = json.loads((TASK / 'logs/FIGURE_GEOMETRY.json').read_text(encoding='utf8'))
        print(
            f"VERIFY={result['acceptance_status']} ({result['numeric_slots']} slots, {result['numeric_occurrences']} occurrences); "
            f"INTEGRITY={integ['passed']}; GEOMETRY={geom['status']}."
        )
        ok = result['acceptance_status'] == 'PASS' and integ['passed'] and geom['status'] == 'PASS'
        return 0 if ok else 3
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _write_output_hashes() -> None:
    import hashlib
    hashes = {}
    targets = ['REPORT.md', 'figure-manifest.csv']
    for rel in targets:
        p = TASK / rel
        if p.is_file():
            hashes[rel] = hashlib.sha256(p.read_bytes()).hexdigest()
    for folder in ('captions', 'data', 'figures', 'scripts', 'supplement', 'tables', 'tests'):
        d = TASK / folder
        if not d.is_dir():
            continue
        for p in sorted(d.iterdir()):
            if p.is_file() and '__pycache__' not in p.parts:
                rel = str(p.relative_to(TASK))
                hashes[rel] = hashlib.sha256(p.read_bytes()).hexdigest()
    (TASK / 'OUTPUT_HASHES.json').write_text(json.dumps(dict(sorted(hashes.items())), indent=2) + '\n', encoding='utf8')


if __name__ == '__main__':
    raise SystemExit(main())
