"""Dipendenze KNIME: lettura dal .knwf e confronto con un Environment.

Un .knwf e' uno zip; ogni nodo (anche dentro metanodi/componenti) ha un settings.xml
in cui KNIME registra la feature e il bundle che forniscono il nodo, es.:

    <entry key="node-feature-symbolic-name" type="xstring" value="org.knime.features.base.feature.group"/>

Le estensioni installate in un Environment si ricavano dalla cartella features/
dell'installazione KNIME (es. features/org.knime.features.base_5.2.0.v202312011020).
"""

import re
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

_NS = "{http://www.knime.org/2008/09/XMLConfig}"
_FEATURE_GROUP = ".feature.group"
_FEATURE_DIR_RE = re.compile(r"^(?P<id>.+?)_(?P<version>\d+\.\d+\.\d+.*)$")


@dataclass(frozen=True)
class Dependency:
    feature_id: str  # sempre con suffisso ".feature.group"
    name: str = ""
    vendor: str = ""
    version: str = ""


class DependencyStatus(StrEnum):
    OK = "ok"
    MISSING = "missing"
    OUTDATED = "outdated"  # installata, ma piu' vecchia di quella con cui e' stato salvato il workflow


@dataclass(frozen=True)
class DependencyCheck:
    dependency: Dependency
    status: DependencyStatus
    installed_version: str | None = None


def normalize_feature_id(feature_id: str) -> str:
    return feature_id if feature_id.endswith(_FEATURE_GROUP) else feature_id + _FEATURE_GROUP


def _top_level_entries(xml_bytes: bytes) -> dict[str, str]:
    root = ET.fromstring(xml_bytes)
    entries = {}
    for el in root:
        if el.tag in (f"{_NS}entry", "entry"):
            entries[el.get("key", "")] = el.get("value", "")
    return entries


def extract_dependencies(knwf_path: str | Path) -> list[Dependency]:
    """Elenca le feature KNIME usate dai nodi del workflow (una per feature, versione piu' alta)."""
    found: dict[str, Dependency] = {}
    with zipfile.ZipFile(knwf_path) as zf:
        for name in zf.namelist():
            if not name.endswith("/settings.xml"):
                continue
            try:
                entries = _top_level_entries(zf.read(name))
            except ET.ParseError:
                continue
            feature_id = entries.get("node-feature-symbolic-name")
            if not feature_id:
                continue
            dep = Dependency(
                feature_id=normalize_feature_id(feature_id),
                name=entries.get("node-feature-name", ""),
                vendor=entries.get("node-feature-vendor", ""),
                version=entries.get("node-feature-version", ""),
            )
            prev = found.get(dep.feature_id)
            if prev is None or version_key(dep.version) > version_key(prev.version):
                found[dep.feature_id] = dep
    return sorted(found.values(), key=lambda d: d.feature_id)


def installed_features(knime_path: str | Path) -> dict[str, str]:
    """Feature installate in una installazione KNIME: {feature_id: versione}."""
    features_dir = Path(knime_path) / "features"
    result: dict[str, str] = {}
    if not features_dir.is_dir():
        return result
    for entry in features_dir.iterdir():
        m = _FEATURE_DIR_RE.match(entry.name)
        if not m:
            continue
        fid = normalize_feature_id(m["id"])
        if fid not in result or version_key(m["version"]) > version_key(result[fid]):
            result[fid] = m["version"]
    return result


def version_key(version: str) -> tuple[int, int, int]:
    """'5.2.0.v2023...' -> (5, 2, 0). Il qualifier viene ignorato."""
    parts = (version.split(".") + ["0", "0", "0"])[:3]
    return tuple(int(p) if p.isdigit() else 0 for p in parts)  # type: ignore[return-value]


def check_dependencies(
    required: list[Dependency], installed: dict[str, str]
) -> list[DependencyCheck]:
    checks = []
    for dep in required:
        have = installed.get(dep.feature_id)
        if have is None:
            status = DependencyStatus.MISSING
        elif dep.version and version_key(have) < version_key(dep.version):
            status = DependencyStatus.OUTDATED
        else:
            status = DependencyStatus.OK
        checks.append(DependencyCheck(dep, status, have))
    return checks
