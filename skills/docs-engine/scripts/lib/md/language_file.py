#!/usr/bin/env python3
"""Load and validate a per-language documentation convention file.

`languages/<lang>.md` carries two things. The YAML frontmatter holds values a
script executes or branches on: which reference generator to defer to, whether
doc comments may be written into source, which doc types apply to a library, a
service, or a CLI. The Markdown body below it is prose, and it reaches the
writer prompt verbatim.

Keeping the machine fields in frontmatter is what lets `docs-sync` decide
whether to shell out to pdoc or godoc with no model call at all. Recovering a
shell command from prose would put a model in the middle of a deterministic
step.

    from lib.md import language_file
    lang = language_file.load("languages/python.md")
    lang.doc_types("library")        # ['concept', 'task']
    lang.generator_command(out="site", package="mypkg")
    lang.body                        # what the prompt sees

Reading and quoting come from `docs_meta.parse`, so a language file and a
generated document behave identically on the way in.
"""

import argparse
import json
import sys
from pathlib import Path

# lib/md/ -> lib/ -> scripts/ is the import root; the skill directory above it
# carries the data trees, so both resolve without knowing the install path.
_SCRIPTS = Path(__file__).resolve().parents[2]
_ENGINE = _SCRIPTS.parent
sys.path.insert(0, str(_SCRIPTS))

from lib.md import docs_meta  # noqa: E402
from lib.run.step import validate  # noqa: E402

SCHEMA_PATH = _ENGINE / "schemas" / "language-file.json"
LANGUAGES_DIR = _ENGINE / "languages"

KINDS = ("library", "service", "cli")


class LanguageFileError(RuntimeError):
    """Raised for a missing file or frontmatter that fails the schema."""


class LanguageFile:
    """One `languages/<lang>.md`, split into machine fields and prose."""

    def __init__(self, path, front, body):
        self.path = Path(path)
        self.front = front
        self.body = body

    # -- identity ---------------------------------------------------------

    @property
    def language(self):
        return self.front["language"]

    @property
    def extensions(self):
        return list(self.front.get("extensions", []))

    def matches(self, filename):
        return Path(filename).suffix.lower() in {e.lower() for e in self.extensions}

    # -- machine fields ---------------------------------------------------

    def doc_types(self, kind):
        """Doc types to request for a module of this kind.

        Falls back to `library` for an unrecognised kind, which is the shape a
        module classifier reaches for when it cannot tell.
        """
        artifacts = self.front.get("artifacts", {})
        return list(artifacts.get(kind) or artifacts.get("library") or [])

    @property
    def generator(self):
        return self.front.get("reference_generator") or None

    def generator_command(self, **fields):
        """Render the native generator's command, or None when there is none.

        A language with a good reference generator gets its reference pages
        from that generator. This plugin writes purpose and getting-started,
        which no generator produces.
        """
        generator = self.generator
        if not generator or not generator.get("command"):
            return None
        try:
            return generator["command"].format(**fields)
        except KeyError as exc:
            raise LanguageFileError(
                f"{self.path}: generator command needs {exc} and it was not supplied"
            ) from exc

    @property
    def writes_doc_comments(self):
        """Whether the plugin may write doc comments into source.

        Default false. Writing godoc or docstrings into source means a pull
        request against code, which lands in a different review and risk class
        than a docs PR.
        """
        return bool((self.front.get("doc_comment") or {}).get("writable", False))

    @property
    def doc_comment_format(self):
        return (self.front.get("doc_comment") or {}).get("format")

    def as_dict(self):
        return {"path": str(self.path), "front": self.front, "body": self.body}


# ------------------------------------------------------------------- loading


def _schema():
    try:
        return json.loads(SCHEMA_PATH.read_text())
    except OSError as exc:
        raise LanguageFileError(f"cannot read {SCHEMA_PATH}: {exc}") from exc


def load(path, schema=None):
    """Read one language file. Raises LanguageFileError on a schema failure."""
    target = Path(path)
    try:
        text = target.read_text()
    except OSError as exc:
        raise LanguageFileError(f"cannot read {target}: {exc}") from exc

    front, body, had_front = docs_meta.parse(text)
    if not had_front:
        raise LanguageFileError(f"{target}: no YAML frontmatter")

    errors = validate(front, schema if schema is not None else _schema())
    if errors:
        detail = "\n".join(f"  {error}" for error in errors)
        raise LanguageFileError(f"{target}: frontmatter invalid\n{detail}")

    return LanguageFile(target, front, body.strip() + "\n")


def load_all(directory=None):
    """Load every language file in a directory, keyed by language name."""
    base = Path(directory) if directory else LANGUAGES_DIR
    schema = _schema()
    result = {}
    for path in sorted(base.glob("*.md")):
        lang = load(path, schema)
        result[lang.language] = lang
    return result


def for_language(name, directory=None):
    """Look a language up by name, then by file stem, then by extension."""
    catalogue = load_all(directory)
    if name in catalogue:
        return catalogue[name]
    probe = name.lower().lstrip(".")
    for lang in catalogue.values():
        if lang.path.stem == name or probe in {e.lstrip(".").lower() for e in lang.extensions}:
            return lang
    raise LanguageFileError(
        f"no language file for {name!r}. Have: {', '.join(sorted(catalogue)) or 'none'}"
    )


# ----------------------------------------------------------------------- cli


def main(argv=None):
    parser = argparse.ArgumentParser(description="Read and validate language files")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("validate", help="Check every language file. Exit 3 on error")
    p.add_argument("--dir", default=str(LANGUAGES_DIR))

    p = sub.add_parser("show", help="Print one language file as JSON")
    p.add_argument("language")
    p.add_argument("--dir", default=str(LANGUAGES_DIR))

    p = sub.add_parser("list", help="List available languages")
    p.add_argument("--dir", default=str(LANGUAGES_DIR))

    args = parser.parse_args(argv)
    base = Path(args.dir)

    if args.command == "validate":
        files = sorted(base.glob("*.md"))
        if not files:
            print(f"language-file: nothing to validate in {base}", file=sys.stderr)
            return 3
        failures = 0
        schema = _schema()
        for path in files:
            try:
                lang = load(path, schema)
            except LanguageFileError as exc:
                failures += 1
                print(f"FAIL  {exc}", file=sys.stderr)
            else:
                print(f"ok    {path.name} ({lang.language})")
        return 3 if failures else 0

    try:
        if args.command == "show":
            print(json.dumps(for_language(args.language, base).as_dict(), indent=2))
        else:
            for name, lang in sorted(load_all(base).items()):
                generator = (lang.generator or {}).get("tool", "none")
                print(f"{name:<12} {','.join(lang.extensions):<16} generator={generator}")
    except LanguageFileError as exc:
        print(f"language-file: {exc}", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
