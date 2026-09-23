/**
 * Lint what pi writes, in the same turn it was written.
 */
import { execFile } from "node:child_process";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";
import {
  type EditToolInput,
  type ExtensionAPI,
  isEditToolResult,
  isWriteToolResult,
  type ToolResultEvent,
  type WriteToolInput,
} from "@earendil-works/pi-coding-agent";

const execFileAsync = promisify(execFile);

const CHECK = join(
  dirname(fileURLToPath(import.meta.url)),
  "..",
  "skills",
  "docs-engine",
  "scripts",
  "lib",
  "vale",
  "check.py",
);

const MAX_BUFFER = 32 * 1024 * 1024;

const LINTABLE = /\.(md|markdown)$/i;

/** A hunk header, whose `+` side counts lines in the file as it now stands. */
const HUNK = /^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@/gm;

export interface LintTarget {
  path: string;
  /** The lines to report on. `null` means the whole file. */
  ranges: Array<[number, number]> | null;
}

/** The new-file line ranges a unified patch touches. */
export function patchRanges(patch: string): Array<[number, number]> {
  const ranges: Array<[number, number]> = [];
  for (const hunk of patch.matchAll(HUNK)) {
    const start = Number(hunk[1]);
    if (!Number.isInteger(start)) {
      continue;
    }
    const count = hunk[2] === undefined ? 1 : Number(hunk[2]);
    // A hunk that only deletes lands no lines of its own. Anchor it to the line
    // the deletion left behind and let check.py widen that to its block.
    ranges.push(
      count > 0 ? [start, start + count - 1] : [Math.max(start, 1), Math.max(start, 1)],
    );
  }
  return ranges;
}

/**
 * What to lint after a tool ran, or nothing when the tool wrote no prose.
 *
 * Narrowed through pi's own guards rather than by reading a key off an untyped
 * bag. The failure this avoids is silent: a gate that matched on a name pi no
 * longer uses would simply never fire, and nothing would say so.
 */
export function lintTarget(event: ToolResultEvent): LintTarget | null {
  if (event.isError) {
    return null;
  }

  if (isWriteToolResult(event)) {
    const { path } = event.input as WriteToolInput;
    // A write replaces the file, so every line in it is this turn's work.
    return typeof path === "string" && LINTABLE.test(path) ? { path, ranges: null } : null;
  }

  if (isEditToolResult(event)) {
    const { path } = event.input as EditToolInput;
    if (typeof path !== "string" || !LINTABLE.test(path)) {
      return null;
    }
    // An edit answers for the lines it changed. Reporting the rest of the page
    // hands back violations in paragraphs the model never opened, and it will
    // go and fix them. Without a patch there is no scope to claim, and a whole
    // file is the safe reading.
    const ranges = event.details?.patch ? patchRanges(event.details.patch) : [];
    return { path, ranges: ranges.length > 0 ? ranges : null };
  }

  return null;
}

export default function (pi: ExtensionAPI) {
  pi.on("tool_result", async (event, ctx) => {
    const target = lintTarget(event);
    if (!target) {
      return;
    }

    const args = [
      CHECK,
      resolve(ctx.cwd, target.path),
      "--level",
      process.env.DOCS_VALE_LEVEL ?? "error",
    ];
    if (process.env.DOCS_VALE_CONFIG) {
      args.push("--config", process.env.DOCS_VALE_CONFIG);
    }
    for (const [start, end] of target.ranges ?? []) {
      args.push("--range", `${start}-${end}`);
    }
    // A rule with one right answer carries it. Applying those here costs a
    // string splice; relaying them would cost a turn. Set DOCS_VALE_FIX=0
    // to keep the gate read-only.
    if (process.env.DOCS_VALE_FIX !== "0") {
      args.push("--fix");
    }

    let report = "";
    try {
      const { stdout } = await execFileAsync("python3", args, { maxBuffer: MAX_BUFFER });
      // Exit 0 is usually silence. With --fix it can still carry the list of
      // replacements applied, and the model has to hear about those: the file
      // on disk no longer matches the copy it believes it just wrote.
      report = stdout?.trimEnd() ?? "";
      if (!report) {
        return;
      }
      return { content: [...event.content, { type: "text" as const, text: report }] };
    } catch (error) {
      const failure = error as { code?: number | string; stdout?: string };
      // Exit 1 carries the alerts. Anything else means Vale could not run, and a
      // gate that reports its own problems trains people to switch it off.
      if (failure.code === "ERR_CHILD_PROCESS_STDIO_MAXBUFFER") {
        report = [
          failure.stdout?.trimEnd(),
          `The report ran past ${MAX_BUFFER} bytes and was cut off. Run check.py on this file to see the rest.`,
        ]
          .filter(Boolean)
          .join("\n");
      } else if (failure.code === 1 && failure.stdout) {
        report = failure.stdout.trimEnd();
      } else {
        return;
      }
    }

    return { content: [...event.content, { type: "text" as const, text: report }] };
  });
}
