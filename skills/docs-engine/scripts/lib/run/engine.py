"""Where docs-engine keeps the assets every step reads.

A step script puts the engine's `scripts/` on `sys.path` and then imports these
names, so the layout is described once. Deriving it again per script is how the
paths drifted: two scripts disagreed about where `config/` lived.
"""

import json
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[3]
LIB = ENGINE / "scripts" / "lib"

# Every generator skill is a flat sibling of docs-engine, in an install and in
# a checkout alike, so one parent reaches all of them and two reaches the
# package root that owns `styles/`.
SKILLS = ENGINE.parent
PACKAGE_ROOT = SKILLS.parent

PROMPTS = ENGINE / "prompts"
SCHEMAS = ENGINE / "schemas"
CONFIG = ENGINE / "config"
LANGUAGES = ENGINE / "languages"
TOPICS = ENGINE / "reference" / "style-topics.md"


def generator():
    """The stamp a written page carries in its frontmatter.

    Derived from `package.json` rather than repeated per writer. Three copies
    had already drifted to two different versions, and the value is how a
    reader tells which version wrote the page in front of them.
    """
    manifest = PACKAGE_ROOT / "package.json"
    try:
        version = json.loads(manifest.read_text())["version"]
    except (OSError, ValueError, KeyError):
        # An installed copy may not ship the manifest. A stamp that names the
        # package without a version beats one that names the wrong version.
        return "docs-skills"
    return f"docs-skills/{version}"


GENERATOR = generator()
