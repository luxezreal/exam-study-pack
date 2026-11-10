#!/usr/bin/env python3
"""Source-preserving exam PDF helpers. Requires PyMuPDF (import fitz)."""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import re
import sys
import tempfile

try:
    import fitz
except ImportError:
    raise SystemExit("PyMuPDF is required; use the available document runtime or install pymupdf in your chosen Python environment.")

ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")
VERSION = 1

class Invalid(ValueError):
    pass

def require(condition, message):
    if not condition:
        raise Invalid(message)

def load_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise Invalid(f"Cannot read JSON {path}: {exc}") from exc

def write_json(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix=".exam-pdf-", suffix=".tmp", delete=False) as stream:
            temp = Path(stream.name)
            stream.write(json.dumps(obj, ensure_ascii=False, indent=2) + "\n")
        temp.replace(path)
    finally:
        if temp is not None and temp.exists():
            temp.unlink()

def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def valid_id(value, context):
    require(isinstance(value, str) and ID_RE.fullmatch(value), f"{context}: use a nonempty ASCII id containing letters, digits, '.', '_' or '-' (no path separators)")

def plain_string(value, context, nonempty=False):
    require(isinstance(value, str), f"{context}: expected a string")
    if nonempty:
        require(bool(value.strip()), f"{context}: cannot be empty")

def open_pdf(path):
    try:
        doc = fitz.open(path)
        require(doc.is_pdf, f"Not a PDF: {path}")
        require(not doc.needs_pass, f"Password-protected PDF must be unlocked before use: {path}")
        return doc
    except (OSError, RuntimeError) as exc:
        raise Invalid(f"Cannot open PDF {path}: {exc}") from exc

def supported_geometry(page, context):
    # Clip coordinate conventions are deliberately narrow and explicit.
    require(page.rotation == 0, f"{context}: rotated pages are not supported for cropping (rotation={page.rotation}). Make a separate normalized derivative PDF and record its provenance; do not edit the original.")
    mb, cb = page.mediabox, page.cropbox
    same = all(abs(a - b) < 0.01 for a, b in zip(mb, cb))
    require(same and abs(mb.x0) < 0.01 and abs(mb.y0) < 0.01, f"{context}: a nondefault CropBox or nonzero page origin is not supported. Normalize a separate derivative first and select coordinates from that derivative.")

def manifest_data(path, ready=False):
    path = Path(path).resolve()
    obj = load_json(path)
    require(isinstance(obj, dict), "Manifest must be a JSON object")
    plain_string(obj.get("title"), "title", True)
    root_name = obj.get("source_root", ".")
    plain_string(root_name, "source_root")
    source_root = (path.parent / root_name).resolve()
    sources = obj.get("sources")
    require(isinstance(sources, dict) and bool(sources), "sources must be a nonempty object")
    docs, paths = {}, {}
    try:
        for sid, src in sources.items():
            valid_id(sid, "source id")
            require(isinstance(src, dict), f"sources.{sid}: expected an object")
            plain_string(src.get("path"), f"sources.{sid}.path", True)
            require(isinstance(src.get("role", "combined"), str) and src.get("role", "combined") in {"question", "answer", "combined"}, f"sources.{sid}.role: invalid role")
            if "label" in src:
                plain_string(src["label"], f"sources.{sid}.label", True)
            p = (source_root / src["path"]).resolve()
            require(p.is_file(), f"Source file does not exist: {p}")
            paths[sid] = p
            docs[sid] = open_pdf(p)
        units = obj.get("units")
        require(isinstance(units, list) and units, "units must be a nonempty array")
        by_id = {}
        for i, unit in enumerate(units):
            require(isinstance(unit, dict), f"units[{i}]: expected an object")
            uid = unit.get("id")
            valid_id(uid, f"units[{i}].id")
            require(uid not in by_id, f"Duplicate unit id: {uid}")
            by_id[uid] = unit
            plain_string(unit.get("label", uid), f"{uid}.label", True)
            plain_string(unit.get("title", unit.get("label", uid)), f"{uid}.title", True)
            for field in ("section", "notes"):
                if field in unit:
                    plain_string(unit[field], f"{uid}.{field}")
        for unit in units:
            uid = unit["id"]
            duplicate = unit.get("duplicate_of")
            if duplicate is not None:
                valid_id(duplicate, f"{uid}.duplicate_of")
                require(duplicate in by_id, f"{uid}: unknown duplicate target {duplicate}")
                require(duplicate != uid, f"{uid}: cannot duplicate itself")
                require(by_id[duplicate].get("duplicate_of") is None, f"{uid}: duplicate_of must directly reference a retained unit; chains/cycles are not allowed")
                plain_string(unit.get("dedup_reason"), f"{uid}.dedup_reason", True)
            for kind in ("question", "answer"):
                parts = unit.get(kind, [])
                require(isinstance(parts, list), f"{uid}.{kind}: expected an array")
                if kind == "question" and duplicate is None:
                    require(bool(parts), f"{uid}: retained unit needs at least one source question crop")
                for j, part in enumerate(parts):
                    context = f"{uid}.{kind}[{j}]"
                    require(isinstance(part, dict), f"{context}: expected an object")
                    sid = part.get("source")
                    require(isinstance(sid, str) and sid in docs, f"{context}: unknown source {sid}")
                    page_number = part.get("page")
                    require(type(page_number) is int and 1 <= page_number <= len(docs[sid]), f"{context}: page must be a 1-based physical page within source {sid}")
                    page = docs[sid][page_number - 1]
                    supported_geometry(page, context)
                    coords = part.get("rect")
                    require(isinstance(coords, list) and len(coords) == 4 and all(type(x) in (int, float) and math.isfinite(x) for x in coords), f"{context}: rect needs four finite PDF-point coordinates")
                    x0, y0, x1, y1 = coords
                    require(x0 < x1 and y0 < y1, f"{context}: rectangle must have positive width and height")
                    bounds = page.rect
                    require(x0 >= bounds.x0 and y0 >= bounds.y0 and x1 <= bounds.x1 and y1 <= bounds.y1, f"{context}: crop is outside page bounds {list(bounds)}")
            supplement = unit.get("supplement")
            if supplement is not None:
                plain_string(supplement, f"{uid}.supplement", True)
                sp = (path.parent / supplement).resolve()
                require(sp.is_file() and sp.suffix.lower() == ".tex", f"{uid}: supplement must point to an existing .tex fragment: {sp}")
            if ready and duplicate is None:
                require(bool(unit.get("answer")) or supplement is not None, f"{uid}: final output needs source answer crops or an existing LaTeX supplement")
        return {"path": path, "obj": obj, "sources": sources, "paths": paths, "docs": docs, "units": units, "retained": [u for u in units if u.get("duplicate_of") is None]}
    except Exception:
        for doc in docs.values():
            doc.close()
        raise

def close_data(data):
    for doc in data["docs"].values():
        doc.close()

def summary(data):
    kept = data["retained"]
    return {"title": data["obj"]["title"], "source_files": len(data["sources"]), "input_units": len(data["units"]), "retained_units": len(kept), "duplicate_units": len(data["units"]) - len(kept), "question_crops": sum(len(u.get("question", [])) for u in kept), "answer_crops": sum(len(u.get("answer", [])) for u in kept), "supplements": sum(u.get("supplement") is not None for u in kept), "unanswered_units": [u["id"] for u in kept if not u.get("answer") and not u.get("supplement")]}

def planned_parts(data):
    for unit in data["retained"]:
        for kind in ("question", "answer"):
            for n, part in enumerate(unit.get(kind, []), 1):
                yield {"unit": unit["id"], "kind": kind, "part": n, "source": part["source"], "page": part["page"], "rect": part["rect"], "asset": f"images/{unit['id']}-{kind}-{n:03}.png"}

def render_part(data, record, dpi):
    page = data["docs"][record["source"]][record["page"] - 1]
    return page.get_pixmap(matrix=fitz.Matrix(dpi / 72, dpi / 72), clip=fitz.Rect(record["rect"]), alpha=False)

def protected_inputs(data):
    paths = {data["path"], *data["paths"].values()}
    for unit in data["units"]:
        if unit.get("supplement"):
            paths.add((data["path"].parent / unit["supplement"]).resolve())
    return paths

def protect_output(path, protected):
    resolved = Path(path).resolve()
    require(resolved not in protected, f"Refusing to overwrite an input or required resource: {resolved}")

def render_command(args):
    data = manifest_data(args.manifest, ready=True)
    try:
        require(72 <= args.dpi <= 600, "dpi must be between 72 and 600")
        build = Path(args.out).resolve()
        protected = protected_inputs(data)
        protect_output(build / "render.json", protected)
        for planned in planned_parts(data):
            protect_output(build / planned["asset"], protected)
        (build / "images").mkdir(parents=True, exist_ok=True)
        records = []
        for record in planned_parts(data):
            pix = render_part(data, record, args.dpi)
            pix.save(build / record["asset"])
            records.append({**record, "width": pix.width, "height": pix.height, "pixel_md5": pix.digest.hex()})
        meta = {"version": VERSION, "manifest": str(data["path"]), "manifest_sha256": sha256(data["path"]), "dpi": args.dpi, "sources": {sid: {"path": str(p), "sha256": sha256(p)} for sid, p in data["paths"].items()}, "summary": summary(data), "crops": records}
        write_json(build / "render.json", meta)
        return {"status": "rendered", "build": str(build), **summary(data)}
    finally:
        close_data(data)

def render_metadata(data, build):
    meta = load_json(build / "render.json")
    require(meta.get("version") == VERSION, "Unsupported render.json version; rerun render")
    require(meta.get("manifest_sha256") == sha256(data["path"]), "Manifest changed after rendering; rerun render before tex/verify")
    dpi = meta.get("dpi")
    require(type(dpi) in (int, float) and 72 <= dpi <= 600, "Invalid render dpi")
    planned = list(planned_parts(data))
    stored = meta.get("crops")
    require(isinstance(stored, list) and len(stored) == len(planned), "render.json crop count does not match manifest")
    for want, got in zip(planned, stored):
        require(all(want[k] == got.get(k) for k in want), f"render.json changed crop identity: {want['asset']}")
        require((build / want["asset"]).is_file(), f"Missing rendered image: {want['asset']}")
        pix = fitz.Pixmap(build / want["asset"])
        require((pix.width, pix.height, pix.digest.hex()) == (got.get("width"), got.get("height"), got.get("pixel_md5")), f"Rendered asset changed: {want['asset']}; rerun render")
    for sid, path in data["paths"].items():
        require(meta.get("sources", {}).get(sid, {}).get("sha256") == sha256(path), f"Source {sid} changed after rendering; rerun render")
    return meta

ESC = {"\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#", "_": r"\_", "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}", "^": r"\textasciicircum{}"}
SYMBOLS = {"→": r"\ensuremath{\to}", "ε": r"\ensuremath{\varepsilon}", "∅": r"\ensuremath{\varnothing}", "≤": r"\ensuremath{\le}", "≥": r"\ensuremath{\ge}", "≠": r"\ensuremath{\ne}", "α": r"\ensuremath{\alpha}", "β": r"\ensuremath{\beta}", "π": r"\ensuremath{\pi}"}

def tex_escape(text, symbols=True):
    return "".join(SYMBOLS[c] if symbols and c in SYMBOLS else ESC.get(c, c) for c in str(text))

def tex_heading(text):
    return r"\texorpdfstring{" + tex_escape(text) + "}{" + tex_escape(text, False) + "}"

def tex_path(path):
    value = Path(path).as_posix()
    require(not any(c in value for c in "{}%\\\n\r"), f"TeX path contains unsupported braces, percent sign, backslash or newline: {value}")
    return r"\detokenize{" + value + "}"

PREAMBLE = r"""% !TEX program = xelatex
\documentclass[UTF8,11pt,a4paper,oneside,openany,fontset=fandol]{ctexbook}
\usepackage[margin=2cm,headheight=15pt]{geometry}
\usepackage{amsmath,amssymb,graphicx,booktabs,longtable,tabularx,array,multirow,enumitem,listings,xcolor,needspace}
\usepackage{tikz,forest}
\usetikzlibrary{arrows.meta,automata,positioning,calc}
\usepackage[most]{tcolorbox}
\usepackage{fancyhdr,hyperref}
\definecolor{ink}{HTML}{173D50}
\definecolor{answer}{HTML}{17604E}
\hypersetup{colorlinks=true,linkcolor=ink,urlcolor=ink}
\setcounter{tocdepth}{1}
\setlength{\parindent}{2em}\setlength{\parskip}{4pt}\setlength{\emergencystretch}{3em}
\setlist{nosep,topsep=5pt,leftmargin=2em}\renewcommand{\arraystretch}{1.2}
\pagestyle{fancy}\fancyhf{}\fancyhead[L]{\small 原题与随题答案}\fancyhead[R]{\small 源图 / 补充解答}\fancyfoot[C]{\thepage}
\raggedbottom
\newlength{\sourceimagewidth}
\newcommand{\suppnote}[1]{\begin{tcolorbox}[breakable,colback=green!3,colframe=answer,title=LaTeX补充或勘误,fonttitle=\bfseries]#1\end{tcolorbox}}
\lstset{basicstyle=\small\ttfamily,columns=fullflexible,keepspaces=true,breaklines=true,frame=single,showstringspaces=false}
"""

def tex_command(args):
    data = manifest_data(args.manifest, ready=True)
    try:
        build, target = Path(args.build).resolve(), Path(args.out).resolve()
        require(math.isfinite(args.max_upscale) and args.max_upscale > 0, "--max-upscale must be a positive finite number")
        tex_path(target)
        meta = render_metadata(data, build)
        require(target.suffix.lower() == ".tex", "--out for tex must have a .tex extension")
        protected = protected_inputs(data) | {build / "render.json"} | {(build / r["asset"]).resolve() for r in meta["crops"]}
        protect_output(target, protected)
        target.parent.mkdir(parents=True, exist_ok=True)
        records = {(r["unit"], r["kind"], r["part"]): r for r in meta["crops"]}
        lines = [PREAMBLE, r"\hypersetup{pdftitle={" + tex_escape(data["obj"]["title"], False) + r"}}", r"\begin{document}", r"\hypersetup{pageanchor=false}", r"\begin{titlepage}\vspace*{1.5cm}", r"{\Huge\bfseries " + tex_escape(data["obj"]["title"]) + r"}\par\vspace{1cm}", r"原题与已有答案采用源PDF裁图。补充解答和勘误另行标记，不替换原图。", r"\par\vspace{.5cm}保留" + str(len(data["retained"])) + r"道题或完整题组；独立编号问题按清单逐题配答。", r"\vfill 来源采用PDF物理页码；去重记录见附录。\end{titlepage}", r"\frontmatter\hypersetup{pageanchor=true}\tableofcontents\mainmatter"]
        current_section = None
        for index, unit in enumerate(data["retained"]):
            group = unit.get("section", "试题与随题答案") or "试题与随题答案"
            if group != current_section:
                lines.append(r"\chapter{" + tex_heading(group) + "}")
                current_section = group
            elif index:
                lines.append(r"\clearpage")
            uid = unit["id"]
            title = unit.get("label", uid) + " · " + unit.get("title", unit.get("label", uid))
            lines += [r"\section{" + tex_heading(title) + "}", r"\label{unit:" + uid + "}", r"\noindent{\small\bfseries\color{ink}题目原文 / \texttt{[" + tex_escape(uid) + r"]}}\par"]
            if unit.get("notes"):
                lines.append(r"{\footnotesize\color{gray}编排说明：" + tex_escape(unit["notes"]) + r"}\par")
            for kind in ("question", "answer"):
                if kind == "answer":
                    lines += [r"\par\medskip\needspace{5\baselineskip}", r"\noindent{\large\bfseries\color{answer}本题答案 / \texttt{[" + tex_escape(uid) + r"]}}\par"]
                    if not unit.get("answer"):
                        lines.append(r"{\small 未提供源答案，以下为LaTeX补写答案。}\par")
                    else:
                        lines.append(r"{\small 原答案截图；必要补充或更正紧随其后。}\par")
                for n, part in enumerate(unit.get(kind, []), 1):
                    record = records[(uid, kind, n)]
                    label = data["sources"][part["source"]].get("label", part["source"])
                    source_width = (part["rect"][2] - part["rect"][0]) * args.max_upscale
                    lines += [r"\par\smallskip\noindent{\footnotesize\color{gray}" + tex_escape(label) + " · PDF第" + str(part["page"]) + r"页}\par\nopagebreak", r"\begingroup\setlength{\sourceimagewidth}{" + f"{source_width:.5f}" + r"bp}\ifdim\sourceimagewidth>\linewidth\setlength{\sourceimagewidth}{\linewidth}\fi", r"\noindent\includegraphics[width=\sourceimagewidth,height=.78\textheight,keepaspectratio]{" + tex_path(build / record["asset"]) + r"}\par\endgroup"]
            if unit.get("supplement"):
                sp = (data["path"].parent / unit["supplement"]).resolve()
                lines += [r"\par\medskip\needspace{5\baselineskip}", r"{\small\color{answer}以下为LaTeX补充解答或勘误。}\par", r"\input{" + tex_path(sp) + "}"]
        lines += [r"\appendix\chapter{去重记录与来源索引}", r"\section{去重记录}"]
        duplicate_units = [u for u in data["units"] if u.get("duplicate_of") is not None]
        if duplicate_units:
            lines.append(r"\begin{longtable}{p{3cm}p{3cm}p{8cm}}\toprule 删除位置&保留位置&合并依据\\\midrule\endhead")
            for u in duplicate_units:
                lines.append(tex_escape(u.get("label", u["id"])) + " & " + r"\hyperref[unit:" + u["duplicate_of"] + "]{" + tex_escape(u["duplicate_of"]) + "} & " + tex_escape(u["dedup_reason"]) + r"\\")
            lines.append(r"\bottomrule\end{longtable}")
        else:
            lines.append("本清单没有删除重复题。")
        lines += [r"\section{源PDF索引}", r"\begin{longtable}{p{3cm}p{11cm}}\toprule 标记&文件\\\midrule\endhead"]
        for sid, src in data["sources"].items():
            lines.append(tex_escape(sid) + " & " + tex_escape(src["path"]) + r"\\")
        lines += [r"\bottomrule\end{longtable}", r"\end{document}"]
        target.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return {"status": "tex-written", "tex": str(target), "note": "Compile with XeLaTeX/latexmk from the TeX file's directory; no TeX installation was attempted.", **summary(data)}
    finally:
        close_data(data)

def sequence_contains(sequence, wanted):
    i = 0
    for x in sequence:
        if i < len(wanted) and x == wanted[i]:
            i += 1
    return i == len(wanted)

def verify_command(args):
    data = manifest_data(args.manifest, ready=True)
    try:
        build, pdf_path = Path(args.build).resolve(), Path(args.pdf).resolve()
        meta = render_metadata(data, build)
        expected = []
        for record in meta["crops"]:
            source = render_part(data, record, meta["dpi"])
            saved = fitz.Pixmap(build / record["asset"])
            require((source.width, source.height, source.digest) == (saved.width, saved.height, saved.digest), f"Source/asset pixel mismatch: {record['asset']}")
            require(source.digest.hex() == record.get("pixel_md5"), f"render.json pixel digest mismatch: {record['asset']}")
            expected.append(source.digest.hex())
        doc = open_pdf(pdf_path)
        actual, placements, texts = [], [], []
        try:
            for n, page in enumerate(doc, 1):
                texts.append(page.get_text())
                for im in page.get_image_info(hashes=True):
                    bbox = fitz.Rect(im["bbox"])
                    require(bbox.x0 >= -0.1 and bbox.y0 >= -0.1 and bbox.x1 <= page.rect.width + 0.1 and bbox.y1 <= page.rect.height + 0.1, f"Image outside final PDF page {n}: {list(bbox)}")
                    digest = im["digest"].hex()
                    actual.append(digest)
                    placements.append({"page": n, "bbox": list(bbox), "pixel_md5": digest})
            missing, extra = Counter(expected) - Counter(actual), Counter(actual) - Counter(expected)
            require(not missing, f"Final PDF is missing or changed {sum(missing.values())} source image frame(s)")
            if not args.allow_extra_images:
                require(not extra, f"Final PDF has {sum(extra.values())} extra image frame(s). Strict proof requires no extras; use --allow-extra-images only when they are intentional and inspect them separately.")
                require(actual == expected, "Source image order differs from the manifest's question→answer sequence")
            else:
                require(sequence_contains(actual, expected), "Source frames are not in manifest order within the final PDF")
            normalized = re.sub(r"\s+", "", "\n".join(texts))
            position = 0
            for u in data["retained"]:
                for prefix in ("题目原文/", "本题答案/"):
                    marker = prefix + "[" + u["id"] + "]"
                    require(normalized.count(marker) == 1, f"Expected one visible marker {marker!r}; verify a PDF generated by this helper, or inspect a custom layout separately")
                    found = normalized.find(marker, position)
                    require(found >= 0, f"Question/answer markers are out of order for {u['id']}")
                    position = found + len(marker)
            result = {"status": "passed" if not extra else "passed-source-subset", "pdf": str(pdf_path), "pdf_sha256": sha256(pdf_path), "pages": len(doc), **summary(data), "source_image_frames": len(expected), "final_image_frames": len(actual), "extra_image_frames": sum(extra.values()), "all_crop_pixels_match_sources": True, "all_pdf_images_accounted_for": not bool(extra), "source_frame_order_matches": True, "question_answer_marker_order_matches": True, "placements": placements}
            output = Path(args.report).resolve() if args.report else build / "verification.json"
            protected = protected_inputs(data) | {pdf_path, (build / "render.json").resolve()} | {(build / r["asset"]).resolve() for r in meta["crops"]}
            protect_output(output, protected)
            write_json(output, result)
            return {k: v for k, v in result.items() if k != "placements"} | {"report": str(output)}
        finally:
            doc.close()
    finally:
        close_data(data)

def parse_pages(spec, total):
    pages = set()
    for piece in spec.split(","):
        piece = piece.strip()
        require(bool(re.fullmatch(r"\d+(?:-\d+)?", piece)), f"Invalid --pages element: {piece}")
        limits = [int(x) for x in piece.split("-")]
        first, last = (limits[0], limits[0]) if len(limits) == 1 else limits
        require(1 <= first <= last <= total, f"--pages range outside 1..{total}: {piece}")
        pages.update(range(first, last + 1))
    return sorted(pages)

def inspect_command(args):
    require(not args.pages or args.out, "--pages requires --out for rendered inspection pages")
    require(72 <= args.dpi <= 300, "Inspection dpi must be between 72 and 300")
    results = []
    input_paths = {Path(p).resolve() for p in args.pdfs}
    if args.out:
        Path(args.out).mkdir(parents=True, exist_ok=True)
    for filename in args.pdfs:
        path = Path(filename).resolve()
        doc = open_pdf(path)
        try:
            rows, text_parts = [], []
            for n, page in enumerate(doc, 1):
                text = page.get_text()
                mb, cb = page.mediabox, page.cropbox
                supported = page.rotation == 0 and all(abs(a-b) < .01 for a,b in zip(mb,cb)) and abs(mb.x0) < .01 and abs(mb.y0) < .01
                rows.append({"page": n, "characters": len(text), "embedded_images": len(page.get_image_info()), "rotation": page.rotation, "page_rect": list(page.rect), "cropbox": list(cb), "mediabox": list(mb), "crop_geometry_supported": supported})
                text_parts.append(f"\n===== PDF physical page {n} =====\n{text}")
            result = {"path": str(path), "pages": len(doc), "characters": sum(r["characters"] for r in rows), "unsupported_crop_pages": [r["page"] for r in rows if not r["crop_geometry_supported"]]}
            if args.out:
                stem = re.sub(r"[^A-Za-z0-9._-]", "_", path.stem)[:50] or "source"
                key = stem + "-" + hashlib.sha256(str(path).encode()).hexdigest()[:8]
                folder = Path(args.out).resolve() / key
                folder.mkdir(parents=True, exist_ok=True)
                for planned in [folder / "pages.json", folder / "text.txt"]:
                    protect_output(planned, input_paths)
                write_json(folder / "pages.json", rows)
                (folder / "text.txt").write_text("\n".join(text_parts), encoding="utf-8")
                if args.pages:
                    for n in parse_pages(args.pages, len(doc)):
                        protect_output(folder / f"page-{n:04}.png", input_paths)
                        doc[n-1].get_pixmap(matrix=fitz.Matrix(args.dpi/72,args.dpi/72), alpha=False).save(folder / f"page-{n:04}.png")
                result["inspection_folder"] = str(folder)
            else:
                result["page_metadata"] = rows
            results.append(result)
        finally:
            doc.close()
    return {"status": "inspected", "sources": results, "note": "Extracted text is an index, not evidence that diagrams, scanned formulas or visible source content were read correctly."}

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("inspect", help="Inspect source geometry/text; optionally render selected physical pages")
    p.add_argument("pdfs", nargs="+"); p.add_argument("--out"); p.add_argument("--pages", help="e.g. 1,3-5; requires --out"); p.add_argument("--dpi", type=int, default=120)
    p = sub.add_parser("validate", help="Validate manifest geometry/dedup; --ready also requires answers")
    p.add_argument("manifest"); p.add_argument("--ready", action="store_true")
    p = sub.add_parser("render", help="Render source crops without modifying source PDFs")
    p.add_argument("manifest"); p.add_argument("--out", required=True); p.add_argument("--dpi", type=int, default=180)
    p = sub.add_parser("tex", help="Generate source-image question/answer LaTeX in manifest order")
    p.add_argument("manifest"); p.add_argument("--build", required=True); p.add_argument("--out", required=True); p.add_argument("--max-upscale", type=float, default=1.25, help="Maximum image enlargement relative to source PDF points (default: 1.25)")
    p = sub.add_parser("verify", help="Verify source pixels, PDF image multiset/order, and visible Q/A markers")
    p.add_argument("manifest"); p.add_argument("--build", required=True); p.add_argument("--pdf", required=True); p.add_argument("--report"); p.add_argument("--allow-extra-images", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "inspect": result = inspect_command(args)
        elif args.command == "render": result = render_command(args)
        elif args.command == "tex": result = tex_command(args)
        elif args.command == "verify": result = verify_command(args)
        else:
            data = manifest_data(args.manifest, ready=args.ready)
            try: result = {"status": "valid-ready" if args.ready else "valid-draft", **summary(data), "note": "This checks structure and crop geometry, not semantic deduplication, answer correctness, or whether crop boundaries omit visible content."}
            finally: close_data(data)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (Invalid, OSError, ValueError, RuntimeError) as exc:
        print(json.dumps({"status": "error", "message": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2

if __name__ == "__main__":
    sys.exit(main())
