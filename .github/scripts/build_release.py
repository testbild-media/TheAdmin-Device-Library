from __future__ import annotations

import json
import os
import re
import shutil
import unicodedata
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / "device-assets"
METADATA = ASSETS / "library.json"
OUTPUT = ROOT / "release-output"
KINDS = {"ethernet", "sfp", "qsfp", "console", "power", "other"}
RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}


def slug(value: str) -> str:
    text = value.strip().lower()
    for source, replacement in (("ä", "ae"), ("æ", "ae"), ("ö", "oe"), ("œ", "oe"), ("ü", "ue"), ("ø", "o"), ("ß", "ss"), ("ð", "d"), ("þ", "th")):
        text = text.replace(source, replacement)
    text = "".join(char for char in unicodedata.normalize("NFD", text) if not unicodedata.combining(char))
    text = text.replace("+", "-plus")
    text = re.sub(r"[^a-z0-9_-]", "-", text)
    text = re.sub(r"-{2,}", "-", text)
    return re.sub(r"^[-_]+|[-_]+$", "", text)


def validate_device(folder: Path) -> None:
    manifest_path = folder / "device.json"
    svg_path = folder / "front.svg"
    if not manifest_path.is_file() or not svg_path.is_file():
        raise ValueError(f"{folder.relative_to(ASSETS)} must contain device.json and front.svg")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    if manifest.get("formatVersion") != 1:
        raise ValueError(f"{folder.relative_to(ASSETS)}: formatVersion must be 1")
    vendor = str(manifest.get("vendor", "")).strip()
    model = str(manifest.get("model", "")).strip()
    if not vendor or not model:
        raise ValueError(f"{folder.relative_to(ASSETS)}: vendor and model are required")
    if slug(vendor) in RESERVED or slug(model) in RESERVED or not slug(vendor) or not slug(model):
        raise ValueError(f"{folder.relative_to(ASSETS)}: vendor or model produces an invalid folder name")
    if folder.parent.name != slug(vendor) or folder.name != slug(model):
        raise ValueError(f"{folder.relative_to(ASSETS)} does not match manifest vendor/model")
    view_box = manifest.get("viewBox")
    if not isinstance(view_box, list) or len(view_box) != 4 or not all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in view_box):
        raise ValueError(f"{folder.relative_to(ASSETS)}: invalid manifest viewBox")
    root = ET.parse(svg_path).getroot()
    svg_view_box = [float(value) for value in re.split(r"[\s,]+", root.attrib.get("viewBox", "").strip()) if value]
    if len(svg_view_box) != 4 or any(abs(float(view_box[index]) - value) > 0.01 for index, value in enumerate(svg_view_box)):
        raise ValueError(f"{folder.relative_to(ASSETS)}: SVG and manifest viewBox differ")
    ids = [node.attrib["id"] for node in root.iter() if node.attrib.get("id")]
    ports = manifest.get("ports")
    if not isinstance(ports, list) or not ports:
        raise ValueError(f"{folder.relative_to(ASSETS)}: ports must not be empty")
    labels: set[str] = set()
    elements: set[str] = set()
    for index, port in enumerate(ports, 1):
        label = str(port.get("label", "")).strip() if isinstance(port, dict) else ""
        element = str(port.get("element", "")).strip() if isinstance(port, dict) else ""
        if not label or label in labels:
            raise ValueError(f"{folder.relative_to(ASSETS)}: invalid or duplicate label at port {index}")
        if port.get("kind") not in KINDS:
            raise ValueError(f"{folder.relative_to(ASSETS)}: invalid kind at port {index}")
        if not element or element in elements or ids.count(element) != 1:
            raise ValueError(f"{folder.relative_to(ASSETS)}: invalid, duplicate, or missing SVG element at port {index}")
        labels.add(label)
        elements.add(element)


def main() -> None:
    tag = os.environ.get("RELEASE_TAG", "")
    version = tag[1:] if tag.startswith("v") else tag
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?", version):
        raise ValueError("Release tag must use semantic versioning, for example v1.0.0")
    source_metadata = json.loads(METADATA.read_text(encoding="utf-8-sig"))
    name = str(source_metadata.get("name", "")).strip()
    author = str(source_metadata.get("author", source_metadata.get("autor", ""))).strip()
    if not name or not author:
        raise ValueError("library.json requires name and author")
    devices = sorted(path for path in ASSETS.glob("*/*") if path.is_dir())
    for device in devices:
        validate_device(device)
    if OUTPUT.exists():
        shutil.rmtree(OUTPUT)
    bundle = OUTPUT / "bundle"
    shutil.copytree(ASSETS, bundle / "device-assets", ignore=shutil.ignore_patterns("library.json", ".git", ".gitignore", "README.md"))
    metadata = {
        "name": name,
        "version": version,
        "updated": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "author": author,
        "deviceCount": len(devices),
    }
    (bundle / "device-assets" / "library.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    archive_base = OUTPUT / f"theadmin-device-library-{version}"
    zip_path = Path(shutil.make_archive(str(archive_base), "zip", bundle))
    adlib_path = zip_path.with_suffix(".adlib")
    zip_path.replace(adlib_path)
    output_file = os.environ.get("GITHUB_OUTPUT")
    if output_file:
        with open(output_file, "a", encoding="utf-8") as handle:
            handle.write(f"archive={adlib_path.relative_to(ROOT).as_posix()}\n")
    print(f"Created {adlib_path} with {len(devices)} devices")


if __name__ == "__main__":
    main()
