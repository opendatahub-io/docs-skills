"""The lint-and-repair loop both writers run over a draft."""

from lib.run.engine import PROMPTS
from lib.vale import check

REPAIR_PROMPT = PROMPTS / "repair-prose.md"


def lint_document(target, config, level="error", timeout=120, log=None):
    """Alerts at or above `level` in `target`, or `None` when checking is off.

    `None` and `[]` mean different things and both callers care. `[]` is a
    document that passed. `None` is a document nobody looked at, either because
    no config was given or because Vale could not run, and a caller must not
    record that as clean.
    """
    if not config:
        return None
    try:
        alerts = check.run(config, [target], timeout=timeout, level=level)
    except check.ValeError as exc:
        if log:
            log(f"prose check skipped: {exc}", "warning")
        return None
    return [alert for alert in alerts if check.at_or_above(alert.severity, level)]


def repair_request(result, path, alerts, level):
    """The repair call: the draft and the alerts, and no evidence at all.

    Resending the write prompt meant resending its payload with it, which for
    one writer is the published excerpts and the symbol list and for the other
    is the language reference and the module map. None of that decides whether
    a sentence hedges, and the draft in front of the model is already grounded.

    `result` is the model's own last reply rather than the file on disk, so a
    replacement `apply_fixes` already made is not reflected in it. That costs
    nothing: the reply comes back, gets written, and the free fixer applies it
    again before the next lint.
    """
    return REPAIR_PROMPT.read_text(), {
        "document": result,
        "alerts": check.format_alerts(str(path), alerts, level),
    }
