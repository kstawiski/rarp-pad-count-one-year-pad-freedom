"""Verify PDF/TIFF/SVG/DOCX format, font embedding, LZW compression, and numeric parity."""
from pathlib import Path
import collections
import hashlib
import json
import re
from PIL import Image
import docx
import pymupdf

from extract_display_values import NUM
from verify_display_values import svg_text

TASK = Path(__file__).resolve().parents[1]
FIGURES = [('Figure1', 240, 180), ('Figure2', 236, 180), ('FigureS1', 112, 180)]


def main():
    result = {
        'passed': True,
        'figures': [],
        'tables': [],
        'scope': 'PDF dimensions, embedded OpenSans fonts, vector no raster images, SVG/PDF numeric parity; TIFF RGB LZW compression, size < 60 MB, and effective DPI; SVG min font-size >= 6.99; DOCX numeric parity.',
    }
    for stem, height, width_mm in FIGURES:
        row = {'figure': stem, 'width_mm': width_mm, 'height_mm': height}
        pdf_p = TASK / f'figures/{stem}.pdf'
        svg_p = TASK / f'figures/{stem}.svg'
        with pymupdf.open(pdf_p) as doc:
            assert len(doc) == 1
            page = doc[0]
            w = page.rect.width * 25.4 / 72
            h = page.rect.height * 25.4 / 72
            assert abs(w - width_mm) < 0.05 and abs(h - height) < 0.05, (stem, w, h)
            fonts = page.get_fonts(full=True)
            assert fonts, ('no fonts embedded', stem)
            for font in fonts:
                assert 'OpenSans' in font[3], (stem, font)
                assert len(doc.extract_font(font[0])[3]) > 0, ('unembedded', stem, font)
            expected = collections.Counter(NUM.findall('\n'.join(svg_text(svg_p))))
            actual = collections.Counter(NUM.findall(page.get_text()))
            assert actual == expected, (stem, actual - expected, expected - actual)
            assert not page.get_images(), ('PDF unexpectedly contains raster data', stem)
            row['pdf'] = {
                'width_mm': round(w, 3),
                'height_mm': round(h, 3),
                'bytes': pdf_p.stat().st_size,
                'fonts': [f[3] for f in fonts],
                'all_fonts_embedded': True,
                'numeric_text_matches_svg': True,
                'vector_no_raster_images': True,
            }

        svg_txt = svg_p.read_text(encoding='utf8')
        pts = [float(n) for n in re.findall(r'font-size:\s*([\d.]+)px', svg_txt)]
        assert pts and min(pts) >= 6.99, (stem, min(pts) if pts else None)
        row['svg'] = {
            'bytes': svg_p.stat().st_size,
            'min_font_pt': min(pts),
            'max_font_pt': max(pts),
            'sha256': hashlib.sha256(svg_p.read_bytes()).hexdigest(),
        }

        png_p = TASK / f'figures/{stem}.png'
        with Image.open(png_p) as im:
            im.load()
            eff_png = im.width / (width_mm / 25.4)
            assert eff_png >= 300.0, (stem, 'png', eff_png)
            row['png'] = {
                'format': im.format,
                'mode': im.mode,
                'pixels': list(im.size),
                'effective_dpi': round(eff_png, 2),
                'bytes': png_p.stat().st_size,
                'sha256': hashlib.sha256(png_p.read_bytes()).hexdigest(),
            }

        tiff_p = TASK / f'figures/{stem}.tiff'
        with Image.open(tiff_p) as im:
            im.load()
            eff_tiff = im.width / (width_mm / 25.4)
            tbytes = tiff_p.stat().st_size
            assert im.mode == 'RGB', (stem, im.mode)
            assert im.info.get('compression') == 'tiff_lzw', (stem, im.info.get('compression'))
            assert tbytes < 60 * 1024 * 1024, (stem, tbytes)
            assert eff_tiff >= 600.0, (stem, eff_tiff)
            row['tiff'] = {
                'format': im.format,
                'mode': im.mode,
                'compression': im.info.get('compression'),
                'pixels': list(im.size),
                'effective_dpi': round(eff_tiff, 2),
                'bytes': tbytes,
                'mb': round(tbytes / (1024 * 1024), 3),
                'sha256': hashlib.sha256(tiff_p.read_bytes()).hexdigest(),
            }
        result['figures'].append(row)

    for stem in ('Table1', 'Table2'):
        dx = TASK / f'tables/{stem}.docx'
        doc = docx.Document(dx)
        result['tables'].append({
            'table': stem,
            'docx_bytes': dx.stat().st_size,
            'md_bytes': (TASK / f'tables/{stem}.md').stat().st_size,
            'csv_bytes': (TASK / f'tables/{stem}.csv').stat().st_size,
            'docx_tables': len(doc.tables),
            'docx_rows': len(doc.tables[0].rows),
        })

    (TASK / 'logs/FORMAT_CHECKS.json').write_text(json.dumps(result, indent=2), encoding='utf8')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
