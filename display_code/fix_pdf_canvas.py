"""Correct Cairo's integer-point page-box truncation without scaling artwork."""
import sys
from pathlib import Path
import pymupdf

def fix(path,width_mm,height_mm):
    path=Path(path)
    with pymupdf.open(path) as doc:
        page=doc[0];rect=page.mediabox
        width=float(width_mm)*72/25.4;height=float(height_mm)*72/25.4
        assert 0 <= width-rect.width < 1 and 0 <= height-rect.height < 1
        # Only add the fractional-point canvas remainder. Never rescale content.
        page.set_mediabox(pymupdf.Rect(0,0,width,height))
        target=path.with_suffix('.fixed.pdf');doc.save(target)
    target.replace(path)
if __name__=='__main__':fix(sys.argv[1],sys.argv[2],sys.argv[3])
