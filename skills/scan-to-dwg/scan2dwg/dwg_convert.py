"""Convert DXF -> DWG using ODA File Converter or AutoCAD accoreconsole."""
from __future__ import annotations
import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from .config import find_oda_converter, find_accoreconsole


def dxf_to_dwg_oda(dxf_path: str, dwg_path: str, version: str = "R2018") -> str:
    """Convert DXF to DWG using ODA File Converter CLI."""
    oda = find_oda_converter()
    if oda is None:
        raise RuntimeError("ODA File Converter not found.")
    in_path = Path(dxf_path).resolve()
    out_path = Path(dwg_path).resolve()
    in_dir = str(in_path.parent)
    out_dir = out_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)

    # ODA CLI:
    #   ODAFileConverter.exe <input_dir> <output_dir> <version> <type> <recurse>
    # It writes output with the same basename as the input.
    cmd = [oda, in_dir, str(out_dir), version, "DWG", "0"]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if proc.returncode != 0:
        raise RuntimeError(
            f"ODA conversion failed (rc={proc.returncode}): {proc.stderr}"
        )
    produced = out_dir / (in_path.stem + ".dwg")
    if produced != out_path:
        if out_path.exists():
            out_path.unlink()
        shutil.move(str(produced), str(out_path))
    if not out_path.exists():
        raise RuntimeError(
            f"ODA reported success but {out_path} was not produced."
        )
    return str(out_path)


def dxf_to_dwg(dxf_path: str, dwg_path: str, version: str = "R2018") -> str:
    """Top-level DXF->DWG dispatcher. Raises RuntimeError if no converter."""
    if find_oda_converter() is not None:
        return dxf_to_dwg_oda(dxf_path, dwg_path, version)
    if find_accoreconsole() is not None:
        # Minimal AutoCAD script-based conversion.
        return _dxf_to_dwg_accoreconsole(dxf_path, dwg_path)
    raise RuntimeError(
        "No DWG converter found.\n"
        "Install ODA File Converter (free) from https://www.opendesign.com "
        "and place ODAFileConverter.exe in C:\\Program Files\\ODA\\ODAFileConverter\\, "
        "or install AutoCAD."
    )


def _dxf_to_dwg_accoreconsole(dxf_path: str, dwg_path: str, version: str = "R2018") -> str:
    acc = find_accoreconsole()
    assert acc is not None
    in_path = Path(dxf_path).resolve()
    out_path = Path(dwg_path).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    script = (
        f'_.OPEN "{in_path}"\n'
        f'_.SAVEAS "{out_path}" {version}\n'
        '_.QUIT\n'
    )
    proc = subprocess.run(
        [acc, "/s", "-"], input=script, capture_output=True, text=True, timeout=180,
    )
    if proc.returncode != 0 or not out_path.exists():
        raise RuntimeError(
            f"accoreconsole conversion failed (rc={proc.returncode}): {proc.stderr}"
        )
    return str(out_path)