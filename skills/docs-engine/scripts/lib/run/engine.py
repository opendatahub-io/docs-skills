"""Where docs-engine keeps the assets every step reads.

A step script puts the engine's `scripts/` on `sys.path` and then imports these
names, so the layout is described once. Deriving it again per script is how the
paths drifted: two scripts disagreed about where `config/` lived.
"""

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
