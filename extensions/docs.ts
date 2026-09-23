/**
 * Run a documentation chain from inside pi, as `/docs` or `/docs-sync`.
 *
 * Both scripts work from a shell and keep working from one. What neither can
 * do on its own is borrow the session's model: every step resolves a command
 * and spawns it, so a run started inside pi becomes pi, then bash, then
 * python, then a fresh `pi -p` per step, cold processes sharing none of the
 * session's context.
 */
import { spawn } from "node:child_process";
import { createServer, type Socket } from "node:net";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import {
  ModelRuntime,
  type ExtensionAPI,
  type ExtensionCommandContext,
  type ThemeColor,
} from "@earendil-works/pi-coding-agent";
import { Text } from "@earendil-works/pi-tui";

const HERE = dirname(fileURLToPath(import.meta.url));
const BUILD = join(HERE, "..", "skills", "docs", "scripts", "build.py");
const SYNC = join(HERE, "..", "skills", "docs-sync", "scripts", "sync.py");
const ASK = join(HERE, "..", "skills", "docs-engine", "scripts", "lib", "run", "ask.py");
const OUTPUT_ENTRY = "docs-output";
const ERROR_TAIL = 8000;

type OutputKind = "detail" | "error" | "warning" | "output" | "status";

interface OutputEntry {
  kind: OutputKind;
  text: string;
}

interface BuildResult {
  code: number;
  stderr: string;
}

interface OutputTheme {
  fg(color: ThemeColor, text: string): string;
}

/**
 * The two line shapes the chain emits, and nothing else is coloured.
 *
 * A step writes `docs-<step>: message`, carrying `error:` or `warning:` when
 * the message reports an outcome. docs-review writes one finding per line as
 * `<severity> <path>: <detail>`. Both severities are decided in Python, where
 * the run knows what happened, so nothing here reads a line for its mood.
 */
const STEP_LINE = /^(\s*)(docs-[a-z0-9-]+:)(?:\s+(error|warning|success):)?(.*)$/i;
const FINDING_LINE = /^(\s*)(error|warning|suggestion)\s+(\S+):\s+(.+)$/i;

/** A style finding opens its detail with the topic that produced it. */
const FINDING_TOPIC = /^([a-z][a-z0-9 -]{0,40}):\s+(.+)$/i;

const SEVERITY: Record<string, ThemeColor> = {
  error: "error",
  warning: "warning",
  suggestion: "muted",
  success: "success",
};

/**
 * One finding, opened out from its single machine-friendly line.
 *
 * The severity and the path share a colour so they read as one header, with
 * what the finding says muted underneath.
 */
function styleFinding(match: RegExpMatchArray, theme: OutputTheme): string {
  const [, indent, severity, doc, detail] = match;
  const color = SEVERITY[severity.toLowerCase()] ?? "text";
  const topic = detail.match(FINDING_TOPIC);
  return [
    indent + theme.fg(color, topic ? `${severity} - ${topic[1]}` : severity),
    theme.fg(color, doc),
    theme.fg("muted", topic ? topic[2] : detail),
  ].join("\n");
}

/**
 * One step line: the prefix in accent, the message in its severity.
 *
 * Colouring the message rather than the whole line keeps a long diagnostic
 * from becoming a solid bar, and keeps every step line looking like the same
 * kind of line whether or not it went wrong.
 */
function styleStep(match: RegExpMatchArray, theme: OutputTheme): string {
  const [, indent, prefix, severity, body] = match;
  const color = severity ? SEVERITY[severity.toLowerCase()] : undefined;
  const message = severity ? ` ${severity}:${body}` : body;
  return indent + theme.fg("accent", prefix) + theme.fg(color ?? "text", message);
}

/** Style each streamed line independently because one entry can mix outcomes. */
export function styleOutput(text: string, kind: OutputKind, theme: OutputTheme): string {
  if (kind === "detail") return theme.fg("muted", text);
  if (kind === "error") return theme.fg("error", text);
  if (kind === "warning") return theme.fg("warning", text);
  if (kind === "status") return theme.fg("accent", text);

  return text
    .split("\n")
    .map((line) => {
      const finding = line.match(FINDING_LINE);
      if (finding) return styleFinding(finding, theme);
      const step = line.match(STEP_LINE);
      if (step) return styleStep(step, theme);
      return theme.fg("text", line);
    })
    .join("\n");
}

/** Read a socket to EOF. `ask.py` shuts down its write side when the prompt is sent. */
function readToEnd(connection: Socket): Promise<string> {
  return new Promise((done, fail) => {
    const chunks: Buffer[] = [];
    connection.on("data", (chunk) => chunks.push(chunk));
    connection.on("end", () => done(Buffer.concat(chunks).toString("utf-8")));
    connection.on("error", fail);
  });
}

/**
 * One model call, returning the text from its authoritative final message.
 * A step's reply is JSON that `extract_json` has to parse, so thinking content
 * and partial deltas are not part of the answer.
 */
async function answer(runtime: ModelRuntime, model: NonNullable<ExtensionCommandContext["model"]>, prompt: string): Promise<string> {
  const message = await runtime.completeSimple(model, {
    messages: [{ role: "user", content: [{ type: "text", text: prompt }] }],
  } as never);
  if (message.stopReason === "error" || message.stopReason === "aborted") {
    throw new Error(message.errorMessage ?? `the model call ${message.stopReason}`);
  }
  const text = message.content
    .filter((part): part is Extract<(typeof message.content)[number], { type: "text" }> => part.type === "text")
    .map((part) => part.text)
    .join("");
  if (!text.trim()) throw new Error(`the model returned no text (stop reason: ${message.stopReason})`);
  return text;
}

/**
 * Quote-aware split of a command line: `--topic "disconnected mirroring"`
 * becomes `["--topic", "disconnected mirroring"]`, not three argv entries
 * with the quote marks still attached. Only single and double quoting is
 * understood, which is all these commands need; this is not a shell.
 */
function splitArgs(input: string): string[] {
  const parts: string[] = [];
  const pattern = /"([^"]*)"|'([^']*)'|(\S+)/g;
  let match: RegExpExecArray | null;
  while ((match = pattern.exec(input)) !== null) {
    parts.push(match[1] ?? match[2] ?? match[3] ?? "");
  }
  return parts;
}

/**
 * Split a command line into the arguments a chain script expects.
 *
 * `bareSubject` names the flag a leading non-flag word becomes. `/docs` takes
 * `--topic`, so `/docs "kv cache tiering"` reads the way it is meant to be
 * typed. `/docs-sync` passes nothing here: it documents whatever the
 * repository holds, and every argument it takes is already a flag.
 */
export function buildArgs(input: string, repo: string, bareSubject?: string): string[] {
  const parts = splitArgs(input.trim());
  const args: string[] = ["--repo", repo];
  if (parts.length === 0) return args;
  if (bareSubject && !parts[0].startsWith("-")) {
    args.push(bareSubject, parts[0]);
    parts.shift();
  }
  return args.concat(parts);
}

/**
 * Single-quote `value` for a POSIX shell command line. `DOCS_LLM_CMD` is
 * built by string interpolation but consumed by Python's `shlex.split`, so
 * an install path containing a space would otherwise break into two argv
 * entries on every model call.
 */
function shQuote(value: string): string {
  return `'${value.replace(/'/g, `'\\''`)}'`;
}

/** Forward complete lines as separate transcript messages and retain a final partial line. */
function lineForwarder(write: (text: string) => void) {
  let pending = "";
  return {
    push(chunk: Buffer) {
      pending += chunk.toString("utf-8");
      const lines = pending.split("\n");
      pending = lines.pop() ?? "";
      for (const line of lines) {
        if (line) write(line);
      }
    },
    flush() {
      if (pending) write(pending);
      pending = "";
    },
  };
}

/**
 * What distinguishes the two commands. Everything else about a run is the
 * same, down to the socket bridge, which is why they share one handler: the
 * only thing `/docs-sync` needs that `/docs` does not is a different script
 * on the end of the same pipe.
 */
interface Chain {
  /** The command as it is typed, without the slash. */
  name: string;
  /** The chain script this command spawns. */
  script: string;
  /** Its basename, for the messages that name what exited. */
  scriptName: string;
  description: string;
  /** The flag a leading bare word becomes, when the command takes one. */
  bareSubject?: string;
  /** Flags that make this a real run rather than a question about one. */
  subjectFlags: string[];
}

const CHAINS: Chain[] = [
  {
    name: "docs",
    script: BUILD,
    scriptName: "build.py",
    description: "Document a code repository, using this session's model",
    bareSubject: "--topic",
    // A run with neither is still a run: `/docs` with no topic documents
    // whatever the repository holds.
    subjectFlags: ["--topic"],
  },
  {
    name: "docs-sync",
    script: SYNC,
    scriptName: "sync.py",
    description: "Bring a repository's documentation back level with its code",
    subjectFlags: ["--bootstrap", "--since-watermark"],
  },
];

export default function (pi: ExtensionAPI) {
  // Command output belongs in the transcript, where it is scrollable and
  // durable, but not in model context. In particular, notifications are the
  // wrong primitive here: adjacent notifications replace one another in pi,
  // which makes a subprocess stream look as though it was swallowed.
  pi.registerEntryRenderer<OutputEntry>(OUTPUT_ENTRY, (entry, _options, theme) => {
    const output = entry.data;
    if (!output?.text) return undefined;
    return new Text(styleOutput(output.text, output.kind, theme), 1, 0);
  });

  for (const chain of CHAINS) registerChain(pi, chain);
}

function registerChain(pi: ExtensionAPI, chain: Chain) {
  pi.registerCommand(chain.name, {
    description: chain.description,
    handler: async (input: string, ctx: ExtensionCommandContext) => {
      // A transcript entry is drawn by the TUI and by nothing else, so in
      // `pi -p` the whole chain ran and said nothing. `json` and `rpc` keep
      // the entries, where they already arrive as `entry_appended` events
      // that a consumer parses; writing raw text into those would corrupt
      // the stream they are reading.
      const headless = ctx.mode !== "tui";
      const toStdout = ctx.mode === "print";
      const write = (text: string, kind: OutputKind = "output") => {
        if (!text) return;
        if (toStdout) {
          process.stdout.write(`${text}\n`);
          return;
        }
        pi.appendEntry<OutputEntry>(OUTPUT_ENTRY, { kind, text });
      };
      // An unattended run that cannot fail is an unattended run nobody can
      // gate on. In a session this stays untouched, or quitting pi later
      // would carry a failure out of a command the user has moved on from.
      const setExit = (code: number) => {
        if (headless && code !== 0) process.exitCode = code;
      };
      const fail = (text: string) => {
        write(text, "error");
        ctx.ui.notify(text, "error");
        setExit(2);
      };
      const repo = resolve(ctx.cwd);
      const args = buildArgs(input, repo, chain.bareSubject);

      const spawnBuild = (env: NodeJS.ProcessEnv) =>
        new Promise<BuildResult>((done) => {
          const child = spawn("python3", [chain.script, ...args], { cwd: repo, env });
          let errorTail = "";
          // A finding's continuation lines carry no severity of their own, so
          // they are muted until the next finding or the next step line.
          let inFinding = false;
          const stderr = lineForwarder((text) => {
            const startsFinding = FINDING_LINE.test(text);
            if (STEP_LINE.test(text)) inFinding = false;
            write(text, inFinding && !startsFinding ? "detail" : "output");
            if (startsFinding) inFinding = true;
            errorTail = `${errorTail}${text}\n`.slice(-ERROR_TAIL);
          });
          const stdout = lineForwarder((text) => write(text));

          child.stderr.on("data", (chunk: Buffer) => stderr.push(chunk));
          child.stdout.on("data", (chunk: Buffer) => stdout.push(chunk));
          child.on("close", (status) => {
            stderr.flush();
            stdout.flush();
            done({ code: status ?? 1, stderr: errorTail.trim() });
          });
          child.on("error", (error) => {
            fail(`${chain.name}: could not start ${chain.scriptName}: ${String(error)}`);
            done({ code: 2, stderr: String(error) });
          });
        });

      write(`${chain.name}: running ${chain.scriptName} ${input.trim()}`.trimEnd(), "status");
      ctx.ui.setStatus(chain.name, `${chain.name}: running`);

      // argparse can answer help, Vale can perform a sync-only invocation, and
      // the model table can be printed without a model. Handle those before
      // ModelRuntime/socket setup. When a ticket or topic accompanies
      // --sync-styles, build.py syncs first and then continues through the
      // documentation chain, so that invocation still needs the model bridge.
      const hasBuildSubject = chain.subjectFlags.some((flag) => args.includes(flag));
      const isStandalone =
        args.includes("--help") ||
        args.includes("-h") ||
        args.includes("--models") ||
        (args.includes("--sync-styles") && !hasBuildSubject);
      if (isStandalone) {
        const env = { ...process.env };
        if (args.includes("--models")) {
          // The table has to say what a run resolves, and a run sends every
          // step the config does not name to the session through this
          // command. Without it the table reported the built-in default for
          // steps that never reach it. No socket: nothing calls a model here.
          env.DOCS_LLM_CMD = `python3 ${shQuote(ASK)}`;
        }
        const result = await spawnBuild(env);
        if (result.code !== 0) {
          // Every line it wrote has already been relayed, so the summary
          // names the code and does not repeat the output under it.
          const summary = `${chain.name}: ${chain.scriptName} exited ${result.code}.`;
          write(summary, "error");
          ctx.ui.notify(summary, "error");
        }
        setExit(result.code);
        ctx.ui.setStatus(chain.name, undefined);
        return;
      }

      const model = ctx.model;
      if (!model) {
        fail(`${chain.name}: this session has no model selected.`);
        ctx.ui.setStatus(chain.name, undefined);
        return;
      }

      let dir: string | undefined;
      let runtime: ModelRuntime;
      try {
        dir = await mkdtemp(join(tmpdir(), "docs-skills-"));
        runtime = await ModelRuntime.create({ refreshOnCreate: false });
      } catch (error) {
        fail(`${chain.name}: could not start the model bridge: ${String(error)}`);
        ctx.ui.setStatus(chain.name, undefined);
        if (dir) await rm(dir, { recursive: true, force: true });
        return;
      }
      const socketPath = join(dir, "ask.sock");

      let calls = 0;
      // ask.py shuts down its write half after sending the prompt. Node's
      // default allowHalfOpen=false mirrors that EOF onto the server's write
      // half immediately, before the model can answer, so connection.end()
      // below silently has nowhere to send the reply.
      const server = createServer({ allowHalfOpen: true }, (connection) => {
        void (async () => {
          try {
            const prompt = await readToEnd(connection);
            calls += 1;
            write(`${chain.name}: model call ${calls}`, "status");
            ctx.ui.setStatus(chain.name, `${chain.name}: model call ${calls}`);
            connection.end(await answer(runtime, model, prompt));
          } catch (error) {
            // Closing with nothing is the right answer: `ask.py` reports an
            // empty reply as a failure, which `run_step` surfaces as a step
            // error rather than as unparseable JSON.
            fail(`${chain.name}: model call failed: ${String(error)}`);
            connection.end();
          }
        })();
      });

      try {
        // `listen`'s callback fires only on success, so without an `error`
        // listener a failed bind (the socket path colliding, or the
        // directory vanishing under it) hangs this command forever instead
        // of surfacing anything. The `try` starts before this await, so
        // that failure still reaches the `finally` below and cleans up the
        // temp directory and the server rather than leaking both.
        await new Promise<void>((ready, fail) => {
          server.once("error", fail);
          server.listen(socketPath, () => {
            server.removeListener("error", fail);
            ready();
          });
        });

        const result = await spawnBuild({
          ...process.env,
          DOCS_ASK_SOCKET: socketPath,
          DOCS_LLM_CMD: `python3 ${shQuote(ASK)}`,
        });

        // The chain's contract: 0 wrote documents, 1 nothing to do,
        // 2 a configuration error, 3 a step failed. docs-sync adds 5, every
        // write refused by the ownership contract. There is no 4: it carried
        // the ticket coverage gate, which went with the ticket.
        const said: Record<number, string> = {
          0: `${chain.name}: documents written.`,
          1: `${chain.name}: nothing to write.`,
          2: `${chain.name}: configuration error, see above.`,
          3: `${chain.name}: a step failed, see above.`,
          5: `${chain.name}: every write was refused by the ownership contract.`,
        };
        const summary = said[result.code] ?? `${chain.name}: ${chain.scriptName} exited ${result.code}.`;
        if (result.code === 0 || result.code === 1) {
          write(summary, "status");
        } else {
          // 5 opened no file it was not allowed to, which is the contract
          // working. Everything else here is a run that produced nothing.
          const kind = result.code === 5 ? "warning" : "error";
          write(result.stderr ? summary : `${summary} ${chain.scriptName} produced no output.`, kind);
          ctx.ui.notify(summary, kind);
        }
        // The chain's own code, so `pi -p` answers what the chain answered.
        setExit(result.code);
      } catch (error) {
        fail(`${chain.name}: could not start the model bridge: ${String(error)}`);
      } finally {
        ctx.ui.setStatus(chain.name, undefined);
        await new Promise<void>((closed) => server.close(() => closed()));
        await rm(dir, { recursive: true, force: true });
      }
    },
  });
}
