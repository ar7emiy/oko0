"""Read plain XLSX tables using the standard library; never execute formulas."""
from __future__ import annotations

import io
import posixpath
import re
import zipfile
from xml.etree import ElementTree as ET


def tables(raw: bytes):
    """Yield (sheet name, rows of strings), honoring sparse and shared cells.

    Formulas require cached values. Simple zero-padding formats preserve common
    identifier columns; otherwise use the stored value, never a Python float.
    """
    with zipfile.ZipFile(io.BytesIO(raw)) as book:
        shared = []
        if "xl/sharedStrings.xml" in book.namelist():
            shared = ["".join(t.text or "" for t in si.findall(".//{*}t"))
                      for si in ET.fromstring(book.read("xl/sharedStrings.xml"))]
        formats = []
        if "xl/styles.xml" in book.namelist():
            styles = ET.fromstring(book.read("xl/styles.xml"))
            custom = {f.get("numFmtId"): f.get("formatCode", "")
                      for f in styles.findall("{*}numFmts/{*}numFmt")}
            formats = [custom.get(x.get("numFmtId"), "")
                       for x in styles.findall("{*}cellXfs/{*}xf")]
        rels = {r.get("Id"): r for r in ET.fromstring(book.read("xl/_rels/workbook.xml.rels"))}
        for sheet in ET.fromstring(book.read("xl/workbook.xml")).findall("{*}sheets/{*}sheet"):
            rid = next((v for k, v in sheet.attrib.items() if k.endswith("}id")), None)
            rel = rels.get(rid)
            if rel is None or rel.get("TargetMode") == "External":
                raise ValueError("Workbook has a missing or external worksheet relationship")
            if not rel.get("Type", "").endswith("/worksheet"):
                continue
            target = rel.get("Target", "")
            path = posixpath.normpath(target.lstrip("/") if target.startswith("/") else "xl/" + target)
            if not path.startswith("xl/"):
                raise ValueError("Worksheet path is outside the workbook")
            rows = []
            for row in ET.fromstring(book.read(path)).findall("{*}sheetData/{*}row"):
                cells = {}
                for cell in row.findall("{*}c"):
                    ref = cell.get("r", "")
                    match = re.fullmatch(r"([A-Z]+)[0-9]+", ref)
                    if not match:
                        raise ValueError(f"Invalid cell reference: {ref}")
                    col = 0
                    for char in match[1]:
                        col = col * 26 + ord(char) - ord("A") + 1
                    if col > 16384:
                        raise ValueError("Worksheet exceeds Excel's column limit")
                    value = cell.find("{*}v")
                    text = value.text or "" if value is not None else ""
                    if cell.find("{*}f") is not None and value is None:
                        raise ValueError(f"{sheet.get('name')}!{ref}: formula has no saved value; recalculate and save in Excel")
                    kind = cell.get("t", "n")
                    if kind == "s":
                        text = shared[int(text)]
                    elif kind == "inlineStr":
                        text = "".join(t.text or "" for t in cell.findall("{*}is/.//{*}t"))
                    elif kind == "e":
                        raise ValueError(f"{sheet.get('name')}!{ref}: Excel error {text}")
                    elif kind == "n":
                        style = int(cell.get("s", "0"))
                        fmt = formats[style] if style < len(formats) else ""
                        if re.fullmatch("0+", fmt) and re.fullmatch(r"[0-9]+(?:\.0+)?", text):
                            text = text.split(".")[0].zfill(len(fmt))
                    cells[col - 1] = text
                if cells:
                    rows.append([cells.get(i, "") for i in range(max(cells) + 1)])
            yield sheet.get("name", "Sheet"), rows
