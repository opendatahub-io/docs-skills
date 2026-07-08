#!/usr/bin/env python3
"""Generate a concise HTML summary report for an eval run.

Shows the analysis, aggregate scores, and pairwise results on a single page.
Links to the full report.html for per-case details.

Usage:
    python3 eval/scripts/summary_report.py --run-id <id> [--baseline <id>] [--open]
"""

import argparse
import json
import os
import webbrowser
from datetime import datetime
from pathlib import Path

import yaml

RUNS_DIR = Path(os.environ.get("AGENT_EVAL_RUNS_DIR", "eval/runs"))

TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Eval Summary — {run_id}</title>
<style>
  :root {{
    --bg: #ffffff; --fg: #1a1a2e; --muted: #64748b; --border: #e2e8f0;
    --card-bg: #f8fafc; --accent: #2563eb; --green: #16a34a; --red: #dc2626;
    --amber: #d97706;
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{
      --bg: #0f172a; --fg: #e2e8f0; --muted: #94a3b8; --border: #334155;
      --card-bg: #1e293b; --accent: #60a5fa; --green: #4ade80; --red: #f87171;
      --amber: #fbbf24;
    }}
  }}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
    background: var(--bg); color: var(--fg); line-height: 1.6;
    padding: 2rem; max-width: 900px; margin: 0 auto; }}
  h1 {{ font-size: 1.5rem; margin-bottom: 0.25rem; }}
  .subtitle {{ color: var(--muted); font-size: 0.875rem; margin-bottom: 1.5rem; }}
  .card {{ background: var(--card-bg); border: 1px solid var(--border); border-radius: 8px;
    padding: 1.25rem; margin-bottom: 1rem; }}
  .card h2 {{ font-size: 1.1rem; margin-bottom: 0.75rem; }}
  .analysis {{ border-left: 3px solid var(--accent); padding-left: 1rem; }}
  .analysis p {{ margin-bottom: 0.75rem; }}
  .analysis ul {{ margin: 0.5rem 0 0.75rem 1.25rem; }}
  .analysis li {{ margin-bottom: 0.25rem; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 0.875rem; }}
  th, td {{ text-align: left; padding: 0.5rem 0.75rem; border-bottom: 1px solid var(--border); }}
  th {{ font-weight: 600; color: var(--muted); font-size: 0.75rem;
    text-transform: uppercase; letter-spacing: 0.05em; }}
  .pass {{ color: var(--green); font-weight: 600; }}
  .fail {{ color: var(--red); font-weight: 600; }}
  .neutral {{ color: var(--muted); }}
  .score {{ font-size: 1.25rem; font-weight: 700; }}
  .score-row td:nth-child(2) {{ font-size: 1.1rem; font-weight: 600; }}
  .pairwise-grid {{ display: grid; grid-template-columns: repeat(3, 1fr);
    gap: 0.75rem; text-align: center; }}
  .pairwise-box {{ background: var(--bg); border: 1px solid var(--border);
    border-radius: 6px; padding: 0.75rem; }}
  .pairwise-box .count {{ font-size: 1.5rem; font-weight: 700; }}
  .pairwise-box .label {{ font-size: 0.75rem; color: var(--muted); text-transform: uppercase; }}
  .metrics-grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 0.75rem; }}
  .metric {{ background: var(--bg); border: 1px solid var(--border);
    border-radius: 6px; padding: 0.75rem; text-align: center; }}
  .metric .value {{ font-size: 1.25rem; font-weight: 700; }}
  .metric .label {{ font-size: 0.75rem; color: var(--muted); }}
  .link {{ color: var(--accent); text-decoration: none; }}
  .link:hover {{ text-decoration: underline; }}
  .footer {{ text-align: center; margin-top: 2rem; color: var(--muted); font-size: 0.8rem; }}
</style>
</head>
<body>

<h1>Eval Summary — {run_id}</h1>
<p class="subtitle">{subtitle}</p>

{analysis_html}

<div class="card">
<h2>Quality Dimensions</h2>
<table>
<tr><th>Dimension</th><th>Judge</th><th>Score</th>{baseline_header}</tr>
{quality_rows}
</table>
</div>

<div class="card">
<h2>Structural Checks</h2>
<table>
<tr><th>Check</th><th>Result</th>{baseline_header}</tr>
{check_rows}
</table>
</div>

{pairwise_html}

<div class="card">
<h2>Run Metrics</h2>
<div class="metrics-grid">
{metrics_html}
</div>
</div>

<div class="footer">
<a class="link" href="report.html">Full report with per-case details →</a>
<br><br>
Generated {generated_at}
</div>

</body>
</html>"""


def _load_yaml(path):
    with open(path) as f:
        return yaml.safe_load(f)


def _load_json(path):
    with open(path) as f:
        return json.load(f)


def _score_class(value, threshold=None):
    if value is None:
        return "neutral"
    if isinstance(value, bool):
        return "pass" if value else "fail"
    if threshold and value < threshold:
        return "fail"
    return "pass"


def _fmt_score(value):
    if value is None:
        return '<span class="neutral">—</span>'
    if isinstance(value, bool):
        cls = "pass" if value else "fail"
        return f'<span class="{cls}">{"✓" if value else "✗"}</span>'
    if isinstance(value, float):
        if value <= 1.0:
            return f'{value:.0%}'
        return f'{value:.2f}'
    return str(value)


def _md_to_html(text):
    """Convert basic markdown to HTML — bold, paragraphs, lists."""
    import html
    import re
    text = html.escape(text)
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
    text = re.sub(r'__(.+?)__', r'<strong>\1</strong>', text)
    text = re.sub(r'\*(.+?)\*', r'<em>\1</em>', text)
    # Add line breaks after sentences for scannability
    text = re.sub(r'(\.) ([A-Z])', r'.\n\2', text)

    lines = text.split("\n")
    html_parts = []
    in_list = False
    paragraph = []

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("- "):
            if paragraph:
                html_parts.append(f'<p>{"<br>".join(paragraph)}</p>')
                paragraph = []
            if not in_list:
                html_parts.append("<ul>")
                in_list = True
            html_parts.append(f"<li>{stripped[2:]}</li>")
        else:
            if in_list:
                html_parts.append("</ul>")
                in_list = False
            if stripped:
                paragraph.append(stripped)
            elif paragraph:
                html_parts.append(f'<p>{"<br>".join(paragraph)}</p>')
                paragraph = []

    if in_list:
        html_parts.append("</ul>")
    if paragraph:
        html_parts.append(f'<p>{"<br>".join(paragraph)}</p>')

    return "\n".join(html_parts)


def _read_analysis(run_dir):
    path = run_dir / "analysis.md"
    if not path.exists():
        return ""
    text = path.read_text()
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            text = parts[2].strip()
    # Extract just the recommendation section
    sections = text.split("\n## ")
    recommendation = ""
    for s in sections:
        if s.startswith("Recommendation"):
            recommendation = s[len("Recommendation"):].strip()
            break
        if s.startswith("Judge Definitions"):
            continue
    return recommendation


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--baseline", default=None)
    parser.add_argument("--open", action="store_true")
    args = parser.parse_args()

    for name in [args.run_id, args.baseline]:
        if name and (".." in name or name.startswith("/")):
            parser.error(f"Invalid run ID: {name}")

    run_dir = RUNS_DIR / args.run_id
    summary = _load_yaml(run_dir / "summary.yaml")
    run_result = _load_json(run_dir / "run_result.json")

    baseline_summary = None
    if args.baseline:
        bl_dir = RUNS_DIR / args.baseline
        if (bl_dir / "summary.yaml").exists():
            baseline_summary = _load_yaml(bl_dir / "summary.yaml")

    # Subtitle
    model = run_result.get("model", "unknown")
    cases = run_result.get("num_cases", 0)
    subtitle = f"Model: {model} · {cases} cases"
    if args.baseline:
        subtitle += f" · Baseline: {args.baseline}"

    # Analysis
    rec = _read_analysis(run_dir)
    if rec:
        rec_html = _md_to_html(rec)
        analysis_html = f'<div class="card analysis"><h2>Recommendation</h2>{rec_html}</div>'
    else:
        analysis_html = ""

    # Quality dimensions
    quality_judges = [
        ("Is it good?", "doc_quality"),
        ("Does it match the ask?", "intent_alignment"),
        ("Does it match what a human wrote?", "reference_comparison"),
    ]
    baseline_header = "<th>Baseline</th><th>Delta</th>" if baseline_summary else ""
    quality_rows = ""
    for label, name in quality_judges:
        judges = summary.get("judges", {})
        score = judges.get(name, {}).get("mean")
        row = f'<tr class="score-row"><td>{label}</td><td>{name}</td><td>{_fmt_score(score)}</td>'
        if baseline_summary:
            bl_score = baseline_summary.get("judges", {}).get(name, {}).get("mean")
            delta = ""
            if score is not None and bl_score is not None:
                d = score - bl_score
                sign = "+" if d > 0 else ""
                color = "pass" if d >= 0 else "fail"
                delta = f'<span class="{color}">{sign}{d:.2f}</span>'
            row += f"<td>{_fmt_score(bl_score)}</td><td>{delta}</td>"
        row += "</tr>"
        quality_rows += row

    # Structural checks
    check_judges = ["files_exist", "step_results_valid", "pipeline_complete"]
    check_rows = ""
    for name in check_judges:
        judges = summary.get("judges", {})
        rate = judges.get(name, {}).get("pass_rate")
        cls = _score_class(rate, 1.0) if rate is not None else "neutral"
        row = f'<tr><td>{name}</td><td><span class="{cls}">{_fmt_score(rate)}</span></td>'
        if baseline_summary:
            bl_rate = baseline_summary.get("judges", {}).get(name, {}).get("pass_rate")
            bl_cls = _score_class(bl_rate, 1.0) if bl_rate is not None else "neutral"
            row += f'<td><span class="{bl_cls}">{_fmt_score(bl_rate)}</span></td><td></td>'
        row += "</tr>"
        check_rows += row

    # Pairwise
    pairwise_html = ""
    pw = summary.get("pairwise")
    if pw:
        wins_a = pw.get('wins_a', 0)
        ties = pw.get('ties', 0)
        wins_b = pw.get('wins_b', 0)
        run_a = pw.get('run_a', '')
        run_b = pw.get('run_b', '')
        pairwise_html = f"""
<div class="card">
<h2>Pairwise Comparison — {run_a} vs {run_b}</h2>
<div class="pairwise-grid">
  <div class="pairwise-box">
    <div class="count" style="color:var(--green)">{wins_a}</div>
    <div class="label">A wins</div>
  </div>
  <div class="pairwise-box">
    <div class="count" style="color:var(--muted)">{ties}</div>
    <div class="label">Ties</div>
  </div>
  <div class="pairwise-box">
    <div class="count" style="color:var(--red)">{wins_b}</div>
    <div class="label">B wins</div>
  </div>
</div>
</div>"""

    # Run metrics
    cost = run_result.get("cost_usd", 0)
    turns = run_result.get("num_turns", 0)
    wall = run_result.get("wall_clock_s", 0)
    rm = summary.get("run_metrics", {})
    cpt = rm.get("cost_per_turn_usd", 0)
    cache = rm.get("cache_hit_rate", 0)
    cost_per_case = cost / cases if cases else 0

    wall_h = wall / 3600

    metrics_html = f"""
<div class="metric">
  <div class="value">${cost:.0f}</div>
  <div class="label">Total cost</div>
</div>
<div class="metric">
  <div class="value">${cost_per_case:.0f}</div>
  <div class="label">Cost / case</div>
</div>
<div class="metric">
  <div class="value">{wall_h:.1f}h</div>
  <div class="label">Wall clock</div>
</div>
<div class="metric">
  <div class="value">{turns:,}</div>
  <div class="label">Turns</div>
</div>
<div class="metric">
  <div class="value">${cpt:.3f}</div>
  <div class="label">Cost / turn</div>
</div>
<div class="metric">
  <div class="value">{cache:.0%}</div>
  <div class="label">Cache hit rate</div>
</div>"""

    generated_at = datetime.now(tz=None).strftime("%Y-%m-%d %H:%M")

    html = TEMPLATE.format(
        run_id=args.run_id,
        subtitle=subtitle,
        analysis_html=analysis_html,
        baseline_header=baseline_header,
        quality_rows=quality_rows,
        check_rows=check_rows,
        pairwise_html=pairwise_html,
        metrics_html=metrics_html,
        generated_at=generated_at,
    )

    out_path = run_dir / "summary.html"
    out_path.write_text(html)
    print(f"SUMMARY: {out_path}")

    if args.open:
        webbrowser.open(f"file://{out_path.resolve()}")


if __name__ == "__main__":
    main()
