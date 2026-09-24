"""languages.yaml is reference, and reference drifts unless something checks it.

Nothing reads the file, which is what let it claim `.pyi` support the walker
never had, list an excluded directory the live set omitted, and say nothing at
all about `yaml`. It stays useful only while the set of languages it describes
is the set the code actually maps.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
_ENGINE = REPO_ROOT / "skills" / "docs-engine" / "scripts"
if str(_ENGINE) not in sys.path:
    sys.path.insert(0, str(_ENGINE))

yaml = pytest.importorskip("yaml")

from lib.ast import build_module_map, detect_language, exclusions  # noqa: E402

REFERENCE = _ENGINE / "lib" / "ast" / "languages.yaml"


def reference():
    return yaml.safe_load(REFERENCE.read_text())


def test_it_describes_every_language_the_walker_maps():
    assert sorted(reference()["languages"]) == sorted(build_module_map.LANG_EXTENSIONS)


def test_it_describes_every_language_detection_accepts():
    described = set(reference()["languages"])
    assert set(detect_language.SOURCE_EXTENSIONS.values()) <= described


def test_it_keeps_no_second_copy_of_what_the_code_holds():
    """Every field here that also lived in code had drifted from it: the
    extensions, the config filenames, and the exclusion lists."""
    data = reference()
    assert "excluded_dirs" not in data
    assert "excluded_files" not in data
    for name, entry in data["languages"].items():
        assert "extensions" not in entry, name
        assert "config_files" not in entry, name


def test_every_described_language_can_actually_be_walked():
    for name in reference()["languages"]:
        assert build_module_map.LANG_EXTENSIONS[name], name
        assert name in build_module_map.CONFIG_FILES, name


def test_the_editor_directories_are_excluded_together():
    """.cursor sat in the reference list and never in the live one."""
    assert {".claude", ".cursor", ".idea", ".vscode"} <= exclusions.EXCLUDED_DIRS
