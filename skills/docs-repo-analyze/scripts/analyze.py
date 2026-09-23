#!/usr/bin/env python3
"""Map a repository into modules, extract its public API, and summarize each one."""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

# docs-engine carries the shared runtime and lands as a flat sibling of this
# skill, in an install and in a checkout alike. Saying so here, rather than
# letting the import fail, names what is missing when it is missing.
ENGINE = Path(__file__).resolve().parents[2] / "docs-engine"
if not (ENGINE / "scripts" / "lib" / "run" / "step.py").exists():
    raise SystemExit(
        "docs-skills: the docs-engine skill is missing. It ships alongside this one "
        "and carries the shared runtime; install it, or run from a checkout."
    )
sys.path.insert(0, str(ENGINE / "scripts"))

from lib.git import commit_select  # noqa: E402
from lib.git.api_surface import registry_hash  # noqa: E402
from lib.run import step  # noqa: E402
from lib.run.engine import LIB, PROMPTS, SCHEMAS  # noqa: E402
from lib.run.report import logger  # noqa: E402

log = logger("docs-repo-analyze")

# Language detection, module mapping, and the tree-sitter extractors live in
# the engine with the rest of the shared runtime, so they travel with it.
EXTRACTORS = ENGINE / "scripts" / "lib" / "ast"

SCHEMA = "docs-skills/registry/1"

# Mirrors `analyze.synthesis_budget` in lib/pipeline/config.py, for a direct
# invocation that reads no config file.
DEFAULT_SYNTHESIS_BUDGET = 240000

TREESITTER_LANGS = {"go", "javascript", "typescript"}


def slug(module):
    """Filesystem-safe module name. `pkg/scheduler` -> `pkg__scheduler`."""
    return module.replace("/", "__").replace("\\", "__") or "root"


def run_json(script, *args, cwd=None):
    """Run one docs-repo-analyze script and parse its stdout."""
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
    result = run_json(EXTRACTORS / "detect_language.py", "--repo", repo)
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


# build_module_map's label for source files sitting at the repository root.
ROOT_MODULE = "root"


def classify_kind(name, files):
    """Which doc types a module needs: cli, service, or library."""
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
    mapping = run_json(EXTRACTORS / "build_module_map.py", *args)
    if mapping.get("error"):
        raise RuntimeError(mapping["error"])

    modules = {}
    for name, entry in sorted((mapping.get("modules") or {}).items()):
        files = entry.get("files", [])
        path = entry.get("path") or name
        # build_module_map labels the repository root "root", which is a name
        # and not a directory: api_surface.walk_module tried `<repo>/root`,
        # found nothing there, and skipped it, so every public symbol at the
        # root was missing from the surface while the registry claimed the
        # module had files. walk_module takes a file as readily as a directory.
        paths = list(files) if path == ROOT_MODULE else [path]
        modules[name] = {
            "paths": paths,
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


def narrow(registry, paths):
    """Keep only the modules under `paths`.

    Targeting a large repository is what `--subject` was always meant to do:
    extract_api runs tree-sitter over every file of every module it is handed,
    which is where a whole-repository read spends its time.
    """
    wanted = [str(p).strip("/") for p in paths if str(p).strip("/")]
    if not wanted:
        return registry
    kept = {
        name: entry
        for name, entry in registry["modules"].items()
        if any(
            path == prefix or path.startswith(f"{prefix}/")
            for path in entry["paths"]
            for prefix in wanted
        )
    }
    if not kept:
        # Targeting that matches nothing is worse than reading whole: it would
        # hand the writer an empty surface and call it the public API.
        return registry
    narrowed = dict(registry)
    narrowed["modules"] = kept
    narrowed["module_count"] = len(kept)
    narrowed["registry_hash"] = registry_hash({n: e["paths"] for n, e in kept.items()})
    return narrowed


def narrow_subject(registry, subject):
    """Keep the modules whose name or paths answer to `subject`.

    `--subject` was declared, documented and passed on every topic run, and
    read by nothing: a topic run paid the whole-repository read the flag exists
    to avoid. extract_api runs tree-sitter over every file of every module it
    is handed, which is where that time goes.

    Matching is on the same word tokens `commit_select` scores against, so a
    subject narrows modules and commits by one vocabulary.
    """
    wanted = commit_select._words(subject)
    if not wanted:
        return registry
    kept = {}
    for name, entry in registry["modules"].items():
        haystack = " ".join([name, *entry.get("paths", [])]).lower()
        if any(word in haystack for word in wanted):
            kept[name] = entry
    if not kept:
        # Targeting that matches nothing is worse than reading whole: it would
        # hand the writer an empty surface and call it the public API.
        return registry
    narrowed = dict(registry)
    narrowed["modules"] = kept
    narrowed["module_count"] = len(kept)
    narrowed["registry_hash"] = registry_hash({n: e["paths"] for n, e in kept.items()})
    return narrowed


def registry_boundaries(registry):
    """The `{module: [prefix]}` view api_surface.load_registry expects."""
    return {name: entry["paths"] for name, entry in registry["modules"].items()}


# ------------------------------------------------------------- public api


def extract_api(repo, registry, out_dir):
    """Write `api/<slug>.json` per module for api_surface's --api-dir."""
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
                EXTRACTORS / "extract_public_api_treesitter.py",
                "--module",
                name,
                "--lang",
                language,
                "--files",
                *files,
            )
        except RuntimeError as exc:
            log(f"{name}: {exc}")
            continue
        if result.get("error"):
            log(f"{name}: {result['error']}")
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


# ------------------------------------------------------------------- main


def dep_pairs(out_dir, registry):
    """Cross-module edges, deduplicated, from the module summaries.

    Runs after the summaries because that is where declared dependencies come
    from. Deterministic in itself: the same summaries always yield the same
    graph.
    """
    summaries = module_summaries(out_dir, registry)
    if not summaries:
        return {"pairs": [], "total_pairs": 0}

    summaries_path = Path(out_dir) / "summaries.json"
    summaries_path.write_text(json.dumps(summaries, indent=2) + "\n")
    try:
        pairs = run_json(
            EXTRACTORS / "build_dep_pairs.py",
            "--summaries",
            summaries_path,
            "--registry",
            Path(out_dir) / "registry.json",
        )
    except RuntimeError as exc:
        log(f"dependency pairs unavailable: {exc}")
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
        log(f"[{index}/{len(names)}] summarizing {name}")
        try:
            result, _ = step.run_step(prompt, payload, schema, llm_cmd, timeout)
        except (step.StepError, RuntimeError) as exc:
            failed.append({"module": name, "error": str(exc)})
            log(f"{name} failed: {exc}")
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


def module_summaries(out_dir, registry):
    """This run's module summaries, in a stable order.

    Reads the modules the current registry names rather than globbing the
    directory. A run whose boundaries have moved leaves summaries behind, and
    globbing picked them up: a guide could describe modules that no longer
    exist, attributed to a run that never saw them.
    """
    module_dir = Path(out_dir) / "modules"
    found = []
    for name in sorted(registry.get("modules") or {}):
        path = module_dir / f"{slug(name)}.json"
        if not path.is_file():
            continue
        try:
            found.append(json.loads(path.read_text()))
        except (OSError, json.JSONDecodeError) as exc:
            # One unreadable summary is one module missing from the guide, not
            # a reason to abandon the modules beside it.
            log(f"{name}: summary is not readable ({exc})", "warning")
    return found


def partition(summaries, budget):
    """Pack summaries into batches of at most `budget` characters.

    Deterministic: the input order decides the batches, and the caller hands
    them over sorted. A summary larger than the budget on its own still gets a
    batch, because refusing to place it would drop a module from the guide
    without saying so.
    """
    batches, current, used = [], [], 0
    for entry in summaries:
        size = len(json.dumps(entry))
        if current and used + size > budget:
            batches.append(current)
            current, used = [], 0
        current.append(entry)
        used += size
    if current:
        batches.append(current)
    return batches


def _record_failure(out_dir, command, summaries, exc, stage, batch=None):
    """What a failed synthesis leaves behind for whoever has to diagnose it.

    `$: no JSON object or array found in output` on its own says nothing about
    why. StepError carries the raw reply, and this is where it stops being
    thrown away.
    """
    record = {
        "stage": stage,
        "command": command,
        "modules": len(summaries),
        "input_chars": sum(len(json.dumps(entry)) for entry in summaries),
        "errors": list(getattr(exc, "errors", None) or [str(exc)]),
        "raw": getattr(exc, "raw", ""),
    }
    if batch is not None:
        record["batch"] = batch
    path = Path(out_dir) / "synthesis-error.json"
    path.write_text(json.dumps(record, indent=2) + "\n")
    log(f"synthesis failed at {stage}: {record['errors'][0]}", "error")
    log(f"{record['modules']} module(s), {record['input_chars']} chars; see {path.name}")
    return path


# The one field synthesis never reads, and the bulk of a summary's size. Shed
# deterministically when a batch reply has to be fallen back on.
SHED = ("public_api",)


def reconcile(batch, returned):
    """The batch's modules, as the model compacted them where it did.

    The prompt asks for every module back and no others. A prompt instruction
    is a request; this is the guarantee. A module the reply dropped falls back
    to its own summary minus `public_api`, because losing it would delete a
    module from the guide silently, and a module the reply invented is a claim
    about code nothing analyzed.
    """
    wanted = {entry["module"]: entry for entry in batch}
    kept, seen = [], set()
    for entry in returned or []:
        name = entry.get("module")
        if name not in wanted or name in seen:
            continue
        seen.add(name)
        kept.append(entry)
    missing = [name for name in wanted if name not in seen]
    for name in missing:
        kept.append({k: v for k, v in wanted[name].items() if k not in SHED})
    invented = len([e for e in returned or [] if e.get("module") not in wanted])
    return kept, missing, invented


def compact(summaries, out_dir, llm_cmd, timeout, budget):
    """Reduce a large summary set until it fits one call.

    Returns the summaries to synthesize from, or None when a batch failed. A
    set that already fits comes back untouched, so a small repository makes
    exactly the one call it always did.
    """
    batches = partition(summaries, budget)
    if len(batches) < 2:
        return summaries

    log(f"{len(summaries)} summaries over the {budget} char budget; {len(batches)} batches")
    prompt = (PROMPTS / "synthesize-batch.md").read_text()
    schema = json.loads((SCHEMAS / "synthesize-batch-out.json").read_text())
    compacted = []
    for index, batch in enumerate(batches, start=1):
        log(f"[{index}/{len(batches)}] compacting {len(batch)} module(s)")
        try:
            result, _ = step.run_step(prompt, {"modules": batch}, schema, llm_cmd, timeout)
        except (step.StepError, RuntimeError) as exc:
            _record_failure(out_dir, llm_cmd, batch, exc, "batch", batch=index)
            return None
        kept, missing, invented = reconcile(batch, result.get("modules"))
        if missing:
            log(f"batch {index} returned no record for {len(missing)} module(s); kept theirs")
        if invented:
            log(f"batch {index} returned {invented} module(s) nothing analyzed; dropped", "warning")
        compacted.extend(kept)
    return compacted


def synthesize(
    registry, out_dir, llm_cmd, timeout, budget=DEFAULT_SYNTHESIS_BUDGET, narrowed=False
):
    """The onboarding guide, over every module summary and the dependency graph.

    One call sees the shape the dependency pairs make, which is what an
    onboarding guide is about. Where the summaries are too large for one call,
    they are compacted in batches first and the final call reads those.
    """
    out_dir = Path(out_dir)
    if narrowed:
        # A guide built from three of fifty modules describes a repository
        # nobody has. `--modules` is for iterating on one module's summary.
        log(
            "--modules narrowed this run, so the guide would describe part of "
            "the repository as the whole of it; skipping synthesis",
            "warning",
        )
        return None

    summaries = module_summaries(out_dir, registry)
    if not summaries:
        log("no module summaries to synthesize")
        return None

    reduced = compact(summaries, out_dir, llm_cmd, timeout, budget)
    if reduced is None:
        return None

    pairs_path = out_dir / "dep-pairs.json"
    pairs = {}
    if pairs_path.exists():
        try:
            pairs = json.loads(pairs_path.read_text())
        except json.JSONDecodeError as exc:
            log(f"dep-pairs.json is not readable ({exc}); synthesizing without it", "warning")

    payload = {
        "language": registry["language"],
        "module_count": registry["module_count"],
        "config_files": registry.get("config_files", []),
        "modules": reduced,
        "dependencies": pairs.get("pairs") or pairs.get("dependencies") or [],
    }
    prompt = (PROMPTS / "synthesize-modules.md").read_text()
    schema = json.loads((SCHEMAS / "synthesize-out.json").read_text())
    log("synthesizing onboarding guide")
    try:
        result, _ = step.run_step(prompt, payload, schema, llm_cmd, timeout)
    except (step.StepError, RuntimeError) as exc:
        _record_failure(out_dir, llm_cmd, reduced, exc, "synthesis")
        return None

    from lib.md import render  # local import: only the model path needs it

    target = out_dir / "ONBOARDING.md"
    target.write_text(render.document(result))
    return target


# ------------------------------------------------------------------- main


def write_surface(repo, registry, out_dir):
    """This run's `api-surface.json`, from the API files just extracted.

    `docs-sources` was the only thing that ever wrote this, and it went with
    the ticket-driven chain. Both the planner and the writer ground on it, and its
    absence is silent: a writer with no surface grounds against nothing and
    every backticked symbol reports unverified.

    `--api-dir` matters for the same reason it mattered there. The walk
    fingerprints only the suffixes in `api_surface.NATIVE`, which is `.py`
    alone, so without it every non-Python repository produces an empty surface.
    """
    # `load_registry` reads the flat `{module: [prefix]}` view, not the full
    # registry. Handing it registry.json directly makes it iterate `file_count`
    # as though it were a path list.
    boundaries = out_dir / "registry-boundaries.json"
    boundaries.write_text(
        json.dumps(registry_boundaries(registry), indent=2, sort_keys=True) + "\n"
    )
    done = subprocess.run(
        [
            sys.executable,
            str(LIB / "git" / "api_surface.py"),
            "snapshot",
            "--repo",
            str(repo),
            "--registry",
            str(boundaries),
            "--api-dir",
            str(out_dir / "api"),
            "--out",
            str(out_dir / "api-surface.json"),
        ],
        capture_output=True,
        text=True,
    )
    if done.returncode not in (0, 1):
        log(f"api-surface exited {done.returncode}: {done.stderr.strip()[:200]}", "warning")
        return False
    return (out_dir / "api-surface.json").is_file()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Map a repository and extract its public API")
    parser.add_argument("--repo", required=True)
    parser.add_argument("--out", default=".docs-gen", help="Artifact directory")
    parser.add_argument("--lang", help="Override language detection")
    parser.add_argument("--exclude", nargs="*", default=[])
    parser.add_argument(
        "--paths",
        nargs="*",
        default=[],
        help="Only map modules under these directories. Narrows a large repository",
    )
    parser.add_argument(
        "--subject",
        help="Narrow a large repository to the modules a subject names",
    )
    parser.add_argument(
        "--llm-cmd",
        default=os.environ.get("DOCS_LLM_CMD"),
        help="Enables the summary and synthesis steps. Omit for the deterministic half",
    )
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument(
        "--synthesis-budget",
        type=int,
        default=DEFAULT_SYNTHESIS_BUDGET,
        help=(
            "Characters of module summaries per synthesis call. Over this, the "
            "summaries are compacted in batches first"
        ),
    )
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
        log(f"not a directory: {repo}", "error")
        return 2
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        language = args.lang or detect(repo)
        if not language:
            log("could not detect a language; nothing to analyze", "warning")
            return 1
        registry = narrow(build_registry(repo, language, args.exclude), args.paths)
        registry = narrow_subject(registry, args.subject or "")
    except RuntimeError as exc:
        # "Unsupported language" is a repository this tool cannot read, which
        # is nothing to do rather than a step that broke.
        if "nsupported language" in str(exc):
            log(f"{exc}; nothing to analyze", "warning")
            return 1
        log(f"{exc}", "error")
        return 2

    registry_path = out_dir / "registry.json"
    if args.skip_cached and registry_path.exists():
        existing = json.loads(registry_path.read_text())
        if existing.get("registry_hash") == registry["registry_hash"]:
            log(f"registry_hash unchanged, nothing to do ({registry['module_count']} modules)")
            return 1

    registry_path.write_text(json.dumps(registry, indent=2, sort_keys=True) + "\n")
    if not registry.get("module_count"):
        # A repository this tool cannot read is nothing to do, not a failure.
        # CI reads exit 3 as something broke, and nothing broke.
        log("no modules found; nothing to analyze", "warning")
        return 1
    extracted = extract_api(repo, registry, out_dir)
    wrote_surface = write_surface(repo, registry, out_dir)

    log(
        f"{registry['module_count']} modules, {extracted} API files, "
        f"{'surface written' if wrote_surface else 'no surface'}, "
        f"registry_hash {registry['registry_hash']}"
    )

    if not args.llm_cmd:
        log("no --llm-cmd, skipping summaries")
        return 0

    only = set(args.modules) if args.modules else None
    written, failed = summarize_modules(repo, registry, out_dir, args.llm_cmd, args.timeout, only)
    if not written and failed:
        log(f"every module summary failed ({len(failed)})", "error")
        return 3

    graph = dep_pairs(out_dir, registry)
    log(f"{graph.get('total_pairs', 0)} dependency pairs")

    target = synthesize(
        registry,
        out_dir,
        args.llm_cmd,
        args.timeout,
        budget=args.synthesis_budget,
        narrowed=only is not None,
    )
    if target is None and only is None:
        # A narrowed run declines to synthesize and says so; anything else
        # reaching here failed, and left synthesis-error.json behind.
        return 3

    log(f"{len(written)} summarized, {len(failed)} failed, wrote {target or 'no guide'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
