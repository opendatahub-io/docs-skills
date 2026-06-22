# Completion Template

After all steps complete:

### Update workflow status

Set `status` to `completed`. Update `updated_at`. Write progress file.

### Print completion summary

```
PR Analysis Complete
================================
Repository:      <REPO_NAME>
PR:              #<PR_NUMBER> — <title>
Platform:        <github|gitlab>
Modules affected: <count>
Files changed:   <count>

Output:          <PR_BASE>/synthesis/PR-<PR_NUMBER>-ANALYSIS.md
Workflow:        <BASE_PATH>/workflow/understand-pr_<REPO_NAME>_<PR_NUMBER>.json
```

### Suggest next steps

- Read the analysis: `cat <PR_BASE>/synthesis/PR-<PR_NUMBER>-ANALYSIS.md`
- Query the codebase: `/docs-skills:query-code "your question" --repo <REPO_PATH>`
- Full codebase analysis: `/docs-skills:learn-code <REPO_PATH>`
