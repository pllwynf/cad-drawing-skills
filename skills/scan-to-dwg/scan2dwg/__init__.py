"""scan-to-dwg: convert scanned paper drawings to DWG/DXF.

Pipeline: PDF/image -> mask red -> grayscale -> deskew -> binarize
         -> classify (walls/axes/columns/openings/dims/text)
         -> vectorize -> OCR -> assemble DXF -> optional DWG conversion.
"""

__version__ = "0.1.0"