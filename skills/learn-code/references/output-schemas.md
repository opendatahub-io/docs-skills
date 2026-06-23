# Output Schemas

JSON schemas for all output files produced by learn-code steps.

## Step 1 — Detection

### detection.json

```json
{
  "primary_language": "<from detect_language>",
  "language_counts": "<from detect_language>",
  "total_files": "<from detect_language>",
  "total_source_files": "<from detect_language>",
  "modules": "<from build_module_map>",
  "module_count": "<from build_module_map>",
  "config_files": "<list of config file names>",
  "config_contents": { "<filename>": "<truncated file content>" },
  "repo_root": "<absolute repo path>",
  "excluded_patterns": "<from build_module_map>"
}
```

### step-result.json (detection)

```json
{
  "schema_version": 1,
  "step": "detection",
  "target": "<repo-name>",
  "completed_at": "<current ISO 8601 UTC>",
  "primary_language": "<detected language>",
  "languages_detected": "<language_counts>",
  "module_count": "<number of modules>",
  "total_source_files": "<count>",
  "config_files_found": ["<list of config files>"]
}
```

## Step 2 — Module Registry

### step-result.json (module-registry)

```json
{
  "schema_version": 1,
  "step": "module-registry",
  "target": "<repo-name>",
  "completed_at": "<current ISO 8601 UTC>",
  "module_count": "<number of modules in registry>",
  "complexity_distribution": { "low": "<count>", "medium": "<count>", "high": "<count>" }
}
```

## Step 3 — Module Analysis

### api-only fallback entry

For modules in the `api-only` tier, generate directly without agent dispatch:

```json
{
  "module": "<module-name>",
  "language": "<primary_language>",
  "purpose": "<purpose from registry>",
  "public_api": [],
  "dependencies": "<likely_imports from registry>",
  "external_libs": [],
  "data_flow": "See source for details",
  "implicit_contracts": [],
  "gotchas": [],
  "onboarding_priority": "skim",
  "question_answer": "API-only analysis — not deeply analyzed",
  "analysis_depth": "api-only"
}
```

### Agent failure fallback entry

For modules where the agent failed or produced invalid JSON:

```json
{
  "module": "<module-name>",
  "language": "<primary_language>",
  "purpose": "Analysis failed — manual review needed",
  "public_api": [],
  "dependencies": [],
  "external_libs": [],
  "data_flow": "Unknown",
  "implicit_contracts": [],
  "gotchas": ["Automated analysis failed for this module"],
  "onboarding_priority": "read-second",
  "question_answer": "Analysis failed"
}
```

### step-result.json (module-analysis)

```json
{
  "schema_version": 1,
  "step": "module-analysis",
  "target": "<repo-name>",
  "completed_at": "<current ISO 8601 UTC>",
  "modules_analyzed": "<successful count>",
  "modules_failed": "<failed count>",
  "tiers": { "full": "<count>", "api_guided": "<count>", "api_only": "<count>" },
  "total_public_api_entries": "<sum of public_api array lengths>",
  "languages": ["<primary_language>"]
}
```

## Step 4 — Relationships

### Lightweight pair entry

For non-priority pairs, generate directly without agent dispatch:

```json
{
  "pair": ["<module_a>", "<module_b>"],
  "coupling_type": "interface-contract",
  "description": "<module_a> depends on <module_b> (lightweight analysis)",
  "shared_types": [],
  "implicit_assumptions": [],
  "risk": "See detailed analysis for core modules",
  "strength": "loose",
  "analysis_depth": "lightweight"
}
```

### Agent failure fallback entry

```json
{
  "pair": ["<module_a>", "<module_b>"],
  "coupling_type": "unknown",
  "description": "Analysis failed — manual review needed",
  "shared_types": [],
  "implicit_assumptions": [],
  "risk": "Unknown",
  "strength": "unknown"
}
```

### dependency-graph.json

```json
{
  "nodes": [
    {"id": "<module>", "purpose": "<purpose>", "priority": "<onboarding_priority>"}
  ],
  "edges": [
    {"from": "<module_a>", "to": "<module_b>", "strength": "<tight|loose|none>", "coupling_type": "<type>"}
  ]
}
```

### step-result.json (relationships)

```json
{
  "schema_version": 1,
  "step": "relationships",
  "target": "<repo-name>",
  "completed_at": "<current ISO 8601 UTC>",
  "pairs_analyzed": "<priority count>",
  "pairs_lightweight": "<lightweight count>",
  "pairs_failed": "<failed count>",
  "coupling_distribution": { "tight": "<count>", "loose": "<count>", "none": "<count>" }
}
```

## Step 5 — Synthesis

### step-result.json (synthesis)

```json
{
  "schema_version": 1,
  "step": "synthesis",
  "target": "<repo-name>",
  "completed_at": "<current ISO 8601 UTC>",
  "output_file": "ONBOARDING.md",
  "sections": ["<list of section names from ## headings>"],
  "context_size_bytes": "<from context builder>"
}
```

Scan ONBOARDING.md for level-2 headings (`## `) to determine sections.

## Progress File

Written to `${BASE_PATH}/workflow/learn-code_${REPO_NAME}.json`.

```json
{
  "workflow_type": "learn-code",
  "target": "<REPO_NAME>",
  "repo_path": "<absolute REPO_PATH>",
  "base_path": "<absolute BASE_PATH>",
  "status": "in_progress",
  "created_at": "<current ISO 8601 UTC>",
  "updated_at": "<current ISO 8601 UTC>",
  "options": {
    "exclude_patterns": ["<patterns>"]
  },
  "step_order": ["detection", "module-registry", "module-analysis", "relationships", "synthesis"],
  "steps": {
    "detection": { "status": "pending", "output": null, "result": null },
    "module-registry": { "status": "pending", "output": null, "result": null },
    "module-analysis": { "status": "pending", "output": null, "result": null },
    "relationships": { "status": "pending", "output": null, "result": null },
    "synthesis": { "status": "pending", "output": null, "result": null }
  }
}
```
