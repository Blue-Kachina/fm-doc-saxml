"""Work out what a build input contains: one export, several, or a split-catalog folder.

FileMaker 26 can Save a Copy as XML for several files at once. It writes either one
XML per file, or (with "separate catalogs") one folder per file holding one XML per
catalog (``split_catalogs="True"``). Either way it adds a ``Summary.xml`` manifest
(root ``FMPReport type="Summary"``). See ``multi_file_saxml.md``.

Only each XML's root element is read here, so scanning a folder of large exports is cheap.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree

from .version_detector import strip_namespace


@dataclass
class SolutionSource:
    """One FileMaker file to convert: a whole-file XML, or the catalog XMLs of a split export."""

    path: Path                     # the XML, or the folder holding its catalog fragments
    fmp_file_name: str = ""        # root ``File`` attribute, e.g. "FileA.fmp12" ("" for v1)
    file_uuid: str = ""
    fragments: list[Path] = field(default_factory=list)  # set for split-catalog exports

    @property
    def is_split(self) -> bool:
        return bool(self.fragments)

    @property
    def name(self) -> str:
        """FileMaker file name without extension, else the XML/folder name."""
        stem = _strip_fm_ext(self.fmp_file_name)
        return stem or (self.path.name if self.is_split else self.path.stem)


@dataclass
class ManifestEntry:
    fmp_file_name: str
    host: str = ""
    xml_path: str = ""             # path on the exporting machine; only its last segment is useful


@dataclass
class Manifest:
    path: Path
    created: str = ""
    entries: list[ManifestEntry] = field(default_factory=list)


@dataclass
class SkippedInput:
    path: Path
    reason: str


@dataclass
class InputScan:
    root: Path
    solutions: list[SolutionSource] = field(default_factory=list)
    manifest: Manifest | None = None
    skipped: list[SkippedInput] = field(default_factory=list)

    @property
    def is_batch(self) -> bool:
        return len(self.solutions) > 1


@dataclass
class _Root:
    tag: str
    attrs: dict[str, str]

    @property
    def is_fragment(self) -> bool:
        return self.tag == "FMSaveAsXML" and self.attrs.get("split_catalogs", "").lower() == "true"

    @property
    def is_manifest(self) -> bool:
        return self.tag == "FMPReport" and self.attrs.get("type", "").lower() == "summary"

    @property
    def is_solution(self) -> bool:
        # v1 and v2 exports share this root; an FMPReport is a DDR or a manifest, not SaXML
        return self.tag == "FMSaveAsXML" and not self.is_fragment

    @property
    def file_key(self) -> tuple[str, str]:
        return (self.attrs.get("File", "").casefold(), self.attrs.get("UUID", ""))


def sniff_root(path: Path) -> _Root | str:
    """The root element's tag and attributes, or a reason it can't be read."""
    try:
        for _event, elem in etree.iterparse(str(path), events=("start",)):
            return _Root(strip_namespace(elem.tag), {strip_namespace(k): v for k, v in elem.attrib.items()})
    except etree.XMLSyntaxError as exc:
        return f"not valid XML ({exc})"
    except OSError as exc:
        return f"could not be read ({exc})"
    return "empty file"


def scan_input(path: Path) -> InputScan:
    """Classify an input file or folder. Folders are read one level deep (see module docstring)."""
    scan = InputScan(root=path)
    if path.is_file():
        _add_file(scan, path, _FragmentGroups())
        return scan

    groups = _FragmentGroups()
    for xml in _xml_files(path):
        _add_file(scan, xml, groups)
    for sub in sorted((p for p in path.iterdir() if p.is_dir()), key=lambda p: p.name.casefold()):
        # A separate-catalogs folder holds fragments of exactly one file and nothing else
        roots = [(x, sniff_root(x)) for x in _xml_files(sub)]
        if not roots or not all(isinstance(r, _Root) and r.is_fragment for _, r in roots):
            continue
        sub_groups = _FragmentGroups()
        for x, r in roots:
            sub_groups.add(x, r)
        if len(sub_groups.by_key) == 1:
            scan.solutions.extend(sub_groups.solutions(sub))
    scan.solutions.extend(groups.solutions(path))
    scan.solutions.sort(key=lambda s: s.name.casefold())
    return scan


def manifest_mismatches(scan: InputScan) -> tuple[list[ManifestEntry], list[SolutionSource]]:
    """(manifest entries with no export found, exports the manifest doesn't list)."""
    if scan.manifest is None:
        return [], []
    matched: set[int] = set()
    missing = []
    for entry in scan.manifest.entries:
        names = {_strip_fm_ext(entry.fmp_file_name).casefold(), _last_segment(entry.xml_path).casefold()}
        names.discard("")
        hit = next(
            (i for i, s in enumerate(scan.solutions)
             if s.name.casefold() in names or _strip_fm_ext(s.path.name).casefold() in names
             or s.path.stem.casefold() in names),
            None,
        )
        if hit is None:
            missing.append(entry)
        else:
            matched.add(hit)
    extra = [s for i, s in enumerate(scan.solutions) if i not in matched]
    return missing, extra


# ---------------------------------------------------------------------------


class _FragmentGroups:
    """Catalog fragments grouped by the file they belong to."""

    def __init__(self) -> None:
        self.by_key: dict[tuple[str, str], tuple[_Root, list[Path]]] = {}

    def add(self, path: Path, root: _Root) -> None:
        self.by_key.setdefault(root.file_key, (root, []))[1].append(path)

    def solutions(self, folder: Path) -> list[SolutionSource]:
        out = []
        for root, paths in self.by_key.values():
            out.append(SolutionSource(
                # Fragments alone in their folder: the folder is the export. Loose ones
                # sitting beside other files are named after their FileMaker file.
                path=folder if len(self.by_key) == 1 and _only_fragments(folder, paths) else folder / _strip_fm_ext(root.attrs.get("File", "")),
                fmp_file_name=root.attrs.get("File", ""),
                file_uuid=root.attrs.get("UUID", ""),
                fragments=sorted(paths, key=lambda p: p.name.casefold()),
            ))
        return out


def _only_fragments(folder: Path, paths: list[Path]) -> bool:
    return {p.name for p in _xml_files(folder)} == {p.name for p in paths}


def _add_file(scan: InputScan, path: Path, groups: _FragmentGroups) -> None:
    root = sniff_root(path)
    if isinstance(root, str):
        scan.skipped.append(SkippedInput(path, root))
    elif root.is_manifest:
        if scan.manifest is None:
            scan.manifest = _read_manifest(path)
        else:
            scan.skipped.append(SkippedInput(path, "a second Summary.xml manifest"))
    elif root.is_fragment:
        groups.add(path, root)
    elif root.is_solution:
        scan.solutions.append(SolutionSource(
            path=path, fmp_file_name=root.attrs.get("File", ""), file_uuid=root.attrs.get("UUID", ""),
        ))
    else:
        scan.skipped.append(SkippedInput(path, f"not a FileMaker Save a Copy as XML export (root <{root.tag}>)"))


def _read_manifest(path: Path) -> Manifest:
    manifest = Manifest(path=path)
    try:
        root = etree.parse(str(path)).getroot()
    except etree.XMLSyntaxError:
        return manifest
    date, time = root.get("CreationDate", ""), root.get("CreationTime", "")
    manifest.created = f"{date} {time}".strip()
    for f in root:
        if not isinstance(f.tag, str) or strip_namespace(f.tag) != "File":
            continue
        xml = next((c for c in f if isinstance(c.tag, str) and strip_namespace(c.tag) == "XML"), None)
        manifest.entries.append(ManifestEntry(
            fmp_file_name=f.get("name", ""),
            host=f.get("path", ""),
            xml_path=xml.get("path", "") if xml is not None else "",
        ))
    return manifest


def _xml_files(folder: Path) -> list[Path]:
    return sorted(
        (p for p in folder.iterdir() if p.is_file() and p.suffix.lower() == ".xml"),
        key=lambda p: p.name.casefold(),
    )


def _strip_fm_ext(name: str) -> str:
    for ext in (".fmp12", ".fmp7"):
        if name.lower().endswith(ext):
            return name[: -len(ext)]
    return name


def _last_segment(path: str) -> str:
    """Last segment of a Windows or POSIX path from another machine, minus .xml."""
    seg = path.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
    return seg[:-4] if seg.lower().endswith(".xml") else seg
