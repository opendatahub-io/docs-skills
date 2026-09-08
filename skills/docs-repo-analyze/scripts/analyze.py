#!/usr/bin/env python3
"""Map a repository into modules, extract its public API, and summarize it.

`learn-code` with the agent layer removed. Detection, module mapping, API
extraction, and the dependency graph are deterministic and run here. The two
steps that need a model, per-module summaries and cross-module synthesis, go
through `lib/run/step.py` one at a time, so nothing depends on a harness
offering subagents.

    python3 analyze.py --repo /path/to/code --out .docs-gen

Writes into the artifact directory:

    registry.json          module -> paths, kind, language, plus registry_hash
    api/<slug>.json        public symbols per module, for api_surface --api-dir
    modules/<slug>.json    model summary per module        (needs --llm-cmd)
    dep-pairs.json         cross-module edges, from those summaries
    ONBOARDING.md          the synthesis                   (needs --llm-cmd)

Without `--llm-cmd` the deterministic half runs and the model steps are
skipped, which is enough for `api_surface.py` and the relevance engine.
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


def _find_engine():
    """Locate the docs-engine skill, which holds the generator's shared runtime.

    An installer copies each skill directory on its own and drops symlinks on
    the way, so a tree shared above the skills cannot be linked in and does not
    survive the copy. It does land every skill as a flat sibling, and that is
    what this walk uses: docs-engine sits two levels up from any generator
    skill's script, in an install and in a checkout alike.

    Nothing reads a plugin root from the environment, because no harness sets
    one.
    """
    here = Path(__file__).resolve()
    for base in (here.parent, *here.parents):
        if (base / "scripts" / "lib" / "run" / "step.py").exists():
            return base
        sibling = base / "docs-engine"
        if (sibling / "scripts" / "lib" / "run" / "step.py").exists():
            return sibling
    raise SystemExit(
        "docs-skills: cannot find the docs-engine skill. It ships alongside this "
        "one and carries the shared runtime; install it, or run from a checkout."
    )


ENGINE = _find_engine()
sys.path.insert(0, str(ENGINE / "scripts"))

PROMPTS = ENGINE / "prompts"
SCHEMAS = ENGINE / "schemas"
LANGUAGES = ENGINE / "languages"
CONFIG = ENGINE / "config"

from lib.git.api_surface import registry_hash  # noqa: E402
from lib.run import step  # noqa: E402

# The tree-sitter extractors are a sibling skill, reached the same way as
# the engine: flat siblings in an install, under skills/ in a checkout.
LEARN = ENGINE.parent / "learn-code" / "scripts"

SCHEMA = "docs-skills/registry/1"

TREESITTER_LANGS = {"go", "javascript", "typescript"}


def slug(module):
    """Filesystem-safe module name. `pkg/scheduler` -> `pkg__scheduler`."""
    return module.replace("/", "__").replace("\\", "__") or "root"


def run_json(script, *args, cwd=None):
    """Run one learn-code script and parse its stdout."""
    argv = [sys.executable, str(script), *[str(a) for a in args]]
    completed = subprocess.run(argv, capture_output=True, text=True, cwd=cwd)
    if completed.returncode != 0:
        raise RuntimeError(
            f"{Path(script).name} exited {completed.returncode}: "
            f"{(completed.stderr or '').strip()[:500]}"
        )
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{Path(script).name} produced no JSON: {exc}")


# --------------------------------------------------------------- registry


def detect(repo):
    result = run_json(LEARN / "detect_language.py", "--repo", repo)
    if result.get("error"):
        raise RuntimeError(result["error"])
    return result.get("primary_language") or result.get("language")


CLI_MARKERS = ("cmd/", "main.go", "__main__.py", "cli.py", "cli.go", "/bin/")
SERVICE_MARKERS = (
    "server",
    "handler",
    "router",
    "controller",
    "daemon",
    "worker",
    "api/",
)


def classify_kind(name, files):
    """Which doc types a module needs: cli, service, or library.

    Path and filename evidence only. The language file maps the answer to a
    doc type set, and an unrecognised answer falls back to `library`, so a
    wrong guess costs a page rather than a run.
    """
    haystack = [name.lower()] + [f.lower() for f in files]
    if any(marker in candidate for candidate in haystack for marker in CLI_MARKERS):
        return "cli"
    if any(marker in candidate for candidate in haystack for marker in SERVICE_MARKERS):
        return "service"
    return "library"


def build_registry(repo, language, excludes):
    """Module map plus kind, in the shape api_surface reads."""
    args = ["--repo", repo, "--lang", language]
    if excludes:
        args += ["--exclude", *excludes]
    mapping = run_json(LEARN / "build_module_map.py", *args)
    if mapping.get("error"):
        raise RuntimeError(mapping["error"])

    modules = {}
    for name, entry in sorted((mapping.get("modules") or {}).items()):
        files = entry.get("files", [])
        modules[name] = {
            "paths": [entry.get("path") or name],
            "files": files,
            "file_count": entry.get("file_count", 0),
            "total_lines": entry.get("total_lines", 0),
            "kind": classify_kind(name, files),
            "language": language,
        }

    boundaries = {name: entry["paths"] for name, entry in modules.items()}
    return {
        "schema": SCHEMA,
        "language": language,
        "repo": str(Path(repo).resolve()),
        "registry_hash": registry_hash(boundaries),
        "module_count": len(modules),
        "config_files": mapping.get("config_files", []),
        "modules": modules,
    }


def registry_boundaries(registry):
    """The `{module: [prefix]}` view api_surface.load_registry expects."""
    return {name: entry["paths"] for name, entry in registry["modules"].items()}


# ------------------------------------------------------------- public api


def extract_api(repo, registry, out_dir):
    """Write `api/<slug>.json` per module for api_surface's --api-dir.

    Python is fingerprinted natively by api_surface, so only the tree-sitter
    languages need extracting here. Symbol `file` fields come back as bare
    basenames, and the fingerprint layer matches on repository-relative paths,
    so they are rewritten against the module's own file list on the way out.
    """
    language = registry["language"]
    if language not in TREESITTER_LANGS:
        return 0

    api_dir = Path(out_dir) / "api"
    api_dir.mkdir(parents=True, exist_ok=True)
    written = 0

    for name, entry in registry["modules"].items():
        files = [str(Path(repo) / f) for f in entry["files"]]
        if not files:
            continue
        try:
            result = run_json(
                LEARN / "extract_public_api_treesitter.py",
                "--module",
                name,
                "--lang",
                language,
                "--files",
                *files,
            )
        except RuntimeError as exc:
            print(f"repo-analyze: {name}: {exc}", file=sys.stderr)
            continue
        if result.get("error"):
            print(f"repo-analyze: {name}: {result['error']}", file=sys.stderr)
            continue

        by_basename = {Path(f).name: f for f in entry["files"]}
        symbols = []
        for symbol in result.get("exports", []):
            record = dict(symbol)
            bare = record.get("file")
            if bare:
                record["file"] = by_basename.get(bare, bare)
            symbols.append(record)

        payload = {
            "module": name,
            "language": language,
            "public_api": symbols,
            "symbol_count": len(symbols),
        }
        (api_dir / f"{slug(name)}.json").write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n"
        )
        written += 1
    return written


def dep_pairs(out_dir):
    """Cross-module edges, deduplicated, from the module summaries.

    Runs after the summaries because that is where declared dependencies come
    from. Deterministic in itself: the same summaries always yield the same
    graph.
    """
    module_dir = Path(out_dir) / "modules"
    summaries = [json.loads(p.read_text()) for p in sorted(module_dir.glob("*.json"))]
    if not summaries:
        return {"pairs": [], "total_pairs": 0}

    summaries_path = Path(out_dir) / "summaries.json"
    summaries_path.write_text(json.dumps(summaries, indent=2) + "\n")
    try:
        pairs = run_json(
            LEARN / "build_dep_pairs.py",
            "--summaries",
            summaries_path,
            "--registry",
            Path(out_dir) / "registry.json",
        )
    except RuntimeError as exc:
        print(f"repo-analyze: dependency pairs unavailable: {exc}", file=sys.stderr)
        return {"pairs": [], "total_pairs": 0}
    (Path(out_dir) / "dep-pairs.json").write_text(
        json.dumps(pairs, indent=2, sort_keys=True) + "\n"
    )
    return pairs


# ----------------------------------------------------------- model steps


def summarize_modules(repo, registry, out_dir, llm_cmd, timeout, only=None):
    """One sequential model call per module. No fan-out, no subagents.

    Sequential is the default because a skill cannot assume its harness offers
    parallelism. `docs-sync --parallel N` shards this list when the harness
    does offer it.
    """
    module_dir = Path(out_dir) / "modules"
    module_dir.mkdir(parents=True, exist_ok=True)
    prompt = (PROMPTS / "analyze-module.md").read_text()
    schema = json.loads((SCHEMAS / "analyze-module-out.json").read_text())
    api_dir = Path(out_dir) / "api"

    written, failed = [], []
    names = [n for n in registry["modules"] if only is None or n in only]
    for index, name in enumerate(sorted(names), start=1):
        entry = registry["modules"][name]
        api_path = api_dir / f"{slug(name)}.json"
        symbols = []
        if api_path.exists():
            symbols = json.loads(api_path.read_text()).get("public_api", [])

        payload = {
            "module": name,
            "language": registry["language"],
            "kind": entry.get("kind", "library"),
            "paths": entry["paths"],
            "files": entry["files"][:200],
            "total_lines": entry.get("total_lines", 0),
            "public_api": symbols[:400],
            "source": read_sources(repo, entry["files"]),
        }
        print(
            f"repo-analyze: [{index}/{len(names)}] summarizing {name}",
            file=sys.stderr,
        )
        try:
            result, _ = step.run_step(prompt, payload, schema, llm_cmd, timeout)
        except (step.StepError, RuntimeError) as exc:
            failed.append({"module": name, "error": str(exc)})
            print(f"repo-analyze: {name} failed: {exc}", file=sys.stderr)
            continue
        result["module"] = name
        (module_dir / f"{slug(name)}.json").write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n"
        )
        written.append(name)
    return written, failed


def read_sources(repo, files, budget=60000):
    """Module source up to a character budget, largest files last."""
    chunks, used = [], 0
    for rel in files:
        path = Path(repo) / rel
        try:
            text = path.read_text(errors="replace")
        except OSError:
            continue
        if used + len(text) > budget:
            text = text[: max(0, budget - used)]
        if not text:
            break
        chunks.append({"file": rel, "content": text})
        used += len(text)
        if used >= budget:
            break
    return chunks


def synthesize(registry, out_dir, llm_cmd, timeout):
    """One call over every module summary and the dependency graph.

    The previous design fanned out a second time to analyze relationships pair
    by pair. One call over the whole dependency graph sees the shape the pairs
    make, which is what an onboarding guide is about.
    """
    module_dir = Path(out_dir) / "modules"
    summaries = []
    for path in sorted(module_dir.glob("*.json")):
        summaries.append(json.loads(path.read_text()))
    if not summaries:
        print("repo-analyze: no module summaries to synthesize", file=sys.stderr)
        return None

    pairs_path = Path(out_dir) / "dep-pairs.json"
    pairs = json.loads(pairs_path.read_text()) if pairs_path.exists() else {}

    payload = {
        "language": registry["language"],
        "module_count": registry["module_count"],
        "config_files": registry.get("config_files", []),
        "modules": summaries,
        "dependencies": pairs.get("pairs") or pairs.get("dependencies") or [],
    }
    prompt = (PROMPTS / "synthesize-modules.md").read_text()
    schema = json.loads((SCHEMAS / "synthesize-out.json").read_text())
    print("repo-analyze: synthesizing onboarding guide", file=sys.stderr)
    result, _ = step.run_step(prompt, payload, schema, llm_cmd, timeout)

    from lib.md import render  # local import: only the model path needs it

    target = Path(out_dir) / "ONBOARDING.md"
    target.write_text(render.document(result))
    return target


# ------------------------------------------------------------------- main


def main(argv=None):
    parser = argparse.ArgumentParser(description="Map and summarize a repository")
    parser.add_argument("--repo", required=True)
    parser.add_argument("--out", default=".docs-gen", help="Artifact directory")
    parser.add_argument("--lang", help="Override language detection")
    parser.add_argument("--exclude", nargs="*", default=[])
    parser.add_argument(
        "--llm-cmd",
        default=os.environ.get("DOCS_LLM_CMD"),
        help="Enables the summary and synthesis steps. Omit for the deterministic half",
    )
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument(
        "--modules", nargs="*", help="Summarize only these modules. Registry still full"
    )
    parser.add_argument(
        "--skip-cached",
        action="store_true",
        help="Skip everything when registry_hash matches the existing registry.json",
    )
    args = parser.parse_args(argv)

    repo = Path(args.repo).resolve()
    if not repo.is_dir():
        print(f"repo-analyze: not a directory: {repo}", file=sys.stderr)
        return 2
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        language = args.lang or detect(repo)
        if not language:
            print("repo-analyze: could not detect a language", file=sys.stderr)
            return 2
        registry = build_registry(repo, language, args.exclude)
    except RuntimeError as exc:
        print(f"repo-analyze: {exc}", file=sys.stderr)
        return 2

    registry_path = out_dir / "registry.json"
    if args.skip_cached and registry_path.exists():
        existing = json.loads(registry_path.read_text())
        if existing.get("registry_hash") == registry["registry_hash"]:
            print(
                f"repo-analyze: registry_hash unchanged, nothing to do "
                f"({registry['module_count']} modules)",
                file=sys.stderr,
            )
            return 1

    registry_path.write_text(json.dumps(registry, indent=2, sort_keys=True) + "\n")
    extracted = extract_api(repo, registry, out_dir)

    print(
        f"repo-analyze: {registry['module_count']} modules, {extracted} API files, "
        f"registry_hash {registry['registry_hash']}",
        file=sys.stderr,
    )

    if not args.llm_cmd:
        print("repo-analyze: no --llm-cmd, skipping summaries", file=sys.stderr)
        return 0

    only = set(args.modules) if args.modules else None
    written, failed = summarize_modules(repo, registry, out_dir, args.llm_cmd, args.timeout, only)
    if not written:
        print("repo-analyze: every module summary failed", file=sys.stderr)
        return 3

    graph = dep_pairs(out_dir)
    print(
        f"repo-analyze: {graph.get('total_pairs', 0)} dependency pairs",
        file=sys.stderr,
    )

    try:
        target = synthesize(registry, out_dir, args.llm_cmd, args.timeout)
    except (step.StepError, RuntimeError) as exc:
        print(f"repo-analyze: synthesis failed: {exc}", file=sys.stderr)
        return 3

    print(
        f"repo-analyze: {len(written)} summarized, {len(failed)} failed, wrote {target}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
