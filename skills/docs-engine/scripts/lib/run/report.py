"""One vocabulary for what a step says on stderr.

Every line is `docs-<step>: message`, carrying `error:` or `warning:` when the
message reports an outcome. The pi extension colours by that severity rather
than reading a line for its mood, and a severity decided here is decided where
the run knows what happened.
"""

import sys

LEVELS = ("error", "warning", "success")


def logger(step):
    """A `log(message, level=None)` bound to one step's name."""

    def log(message, level=None):
        tag = f"{level}: " if level in LEVELS else ""
        print(f"{step}: {tag}{message}", file=sys.stderr)

    return log
