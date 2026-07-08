"""Reference comparison judge for eval harness.

Compares pipeline-generated AsciiDoc against human-written gold-standard
reference files. Uses the Anthropic API (via Vertex) to score on coverage,
structure, technical accuracy, and scope alignment.

Called by score.py as an external code judge:
    module: eval.scripts.reference_judge
    function: judge

Cases without reference/ directories are skipped (returns None).
"""

import json
import os
from pathlib import Path

DATASET_DIR = Path("eval/cases")

PROMPT_TEMPLATE = """You are comparing AI-generated documentation against \
human-written gold-standard documentation for the same JIRA ticket. \
Both sets of AsciiDoc files document the same feature.

Score on 4 dimensions (each 1-5):

1. **Coverage** — does the AI output cover the same topics as the reference? \
Missing topics = low score.
   Extra relevant topics are acceptable but not a bonus.
2. **Structure** — similar module types (concept/procedure/reference), assembly grouping,
   modular docs compliance. Different but valid structures score 3+.
3. **Technical accuracy** — same commands, flags, API fields, config parameters as the reference.
   Fabricated details not in the reference = low score.
4. **Scope alignment** — similar number of modules and depth. 2x+ the reference module count
   (over-scoping) or less than half (under-scoping) = low score.

Return a single composite score (1-5) as the weighted average:
- Coverage: 30%
- Technical accuracy: 30%
- Structure: 20%
- Scope alignment: 20%

## Reference documentation (human-written gold standard)

{reference_content}

## AI-generated documentation (pipeline output)

{pipeline_content}
"""


def _read_adoc_files(directory):
    """Read all .adoc files from a directory, return formatted text."""
    parts = []
    dir_path = Path(directory)
    if not dir_path.exists():
        return ""
    for f in sorted(dir_path.rglob("*.adoc")):
        rel = f.relative_to(dir_path)
        parts.append(f"### {rel}\n\n{f.read_text()}\n")
    return "\n".join(parts)


def _find_case_id(outputs):
    """Extract the case ID from the outputs record."""
    case_dir = outputs.get("case_dir", "")
    if case_dir:
        return Path(case_dir).name
    return None


def _call_llm(prompt, model=None):
    """Call the Anthropic API via Vertex to score the comparison."""
    import anthropic

    if os.environ.get("ANTHROPIC_VERTEX_PROJECT_ID"):
        client = anthropic.AnthropicVertex(
            project_id=os.environ["ANTHROPIC_VERTEX_PROJECT_ID"],
            region=os.environ.get("CLOUD_ML_REGION", "us-east5"),
        )
    elif os.environ.get("GOOGLE_CLOUD_PROJECT"):
        client = anthropic.AnthropicVertex(
            project_id=os.environ["GOOGLE_CLOUD_PROJECT"],
            region=os.environ.get("CLOUD_ML_REGION", "us-east5"),
        )
    else:
        client = anthropic.Anthropic()

    model = model or os.environ.get("EVAL_JUDGE_MODEL", "claude-opus-4-6")

    response = client.messages.create(
        model=model,
        max_tokens=1024,
        system=(
            "You are a documentation quality judge. "
            'Respond with JSON: {"score": <1-5 number>, "rationale": "<explanation>"}'
        ),
        messages=[{"role": "user", "content": prompt}],
    )

    text = response.content[0].text
    try:
        data = json.loads(text)
        return data.get("score", 3), data.get("rationale", "")
    except json.JSONDecodeError:
        import re

        score_match = re.search(r'"score"\s*:\s*(\d)', text)
        if score_match:
            return int(score_match.group(1)), text[:200]
        return 3, f"Could not parse response: {text[:200]}"


def judge(outputs=None, **arguments):
    """Score pipeline output against reference documentation.

    Returns (score, rationale) or (None, reason) if no reference exists.
    """
    outputs = outputs or {}
    case_id = _find_case_id(outputs)
    if not case_id:
        return (None, "Could not determine case ID")

    ref_dir = DATASET_DIR / case_id / "reference"
    if not ref_dir.exists():
        return (None, f"No reference directory for {case_id} — skipping")

    reference_content = _read_adoc_files(ref_dir)
    if not reference_content:
        return (None, f"No .adoc files in {ref_dir}")

    files = outputs.get("files", {})
    pipeline_files = {
        k: v for k, v in files.items() if k.startswith(".output/writing/") and k.endswith(".adoc")
    }

    if not pipeline_files:
        return (1, "No AsciiDoc output from pipeline to compare")

    pipeline_content = "\n".join(
        f"### {path}\n\n{content}\n" for path, content in sorted(pipeline_files.items())
    )

    prompt = PROMPT_TEMPLATE.format(
        reference_content=reference_content,
        pipeline_content=pipeline_content,
    )

    model = arguments.get("model", None)
    try:
        return _call_llm(prompt, model)
    except Exception as e:
        return (None, f"LLM call failed: {e}")
