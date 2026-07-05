# /// script
# requires-python = ">=3.10"
# dependencies = ["bashlex>=0.18"]
# ///
"""PreToolUse hook for the Bash tool.

Reads the standard Claude Code hook JSON on stdin, extracts the command, and
emits a deny decision if the command would apply Prisma migrations or otherwise
mutate the database schema.

Why: `prisma migrate dev` (even with --create-only) auto-applies any pending
migrations on disk before generating the next one. `prisma migrate deploy`,
`prisma migrate reset`, and `prisma db push` apply changes outright. Agents
must never apply migrations — only the human operator may. The safe
alternative for generating SQL without applying is `prisma migrate diff
--script`.

Implementation: parse the command into a real bash AST via bashlex (a
battle-tested pure-Python bash parser used by Semgrep and other security
tooling) and walk every CommandNode anywhere in the tree — inside pipelines,
list separators, subshells, function bodies, for-loops, command
substitutions, and so on. For each CommandNode we strip leading
`VAR=val` assignments, peel off `sudo`/`env` wrappers and their options,
then check the surviving argv against the forbidden invocation patterns.

Dependency management: the PEP 723 inline metadata block above declares
bashlex as a dependency. The hook is invoked via `uv run --script ...`,
which transparently materialises an isolated environment with bashlex on
first use and reuses the cached environment thereafter. No system-wide
install is required.
"""

from __future__ import annotations

import json
import re
import sys
from typing import Iterable, Iterator

import bashlex
import bashlex.ast
import bashlex.errors


DENY_REASON = (
    "BLOCKED: Prisma DB-mutating command. "
    "`prisma migrate dev` (even with --create-only — Prisma applies any pending "
    "migrations on disk as a side-effect), `prisma migrate deploy`, "
    "`prisma migrate reset`, and `prisma db push` all change the database. "
    "Agents must never apply migrations; only the human operator may. "
    "To generate migration SQL without applying, see AGENTS.md → "
    "Prisma Migrations."
)

# Subcommand pairs that mutate the database when run via `prisma`.
PRISMA_MUTATE_PAIRS = {
    ("migrate", "dev"),
    ("migrate", "deploy"),
    ("migrate", "reset"),
    ("db", "push"),
}

# Script names exposed in @shelfalign/database/package.json that wrap a forbidden
# prisma subcommand. (`generate`, `studio`, `seed`, etc. are safe and omitted.)
FORBIDDEN_DATABASE_SCRIPTS = {"migrate", "deploy", "reset"}

# Wrappers that delegate to prisma after stripping their own arguments.
PREPARE_SH_BASENAMES = {"prepare.sh"}

# Short flags accepted by sudo / env that consume the next token as a value.
WRAPPER_SHORT_FLAGS_WITH_ARG = {
    "-u",  # sudo: user; env: unset var
    "-g",  # sudo: group
    "-p",  # sudo: prompt
    "-C",  # sudo: max fd; env: chdir
    "-r",  # sudo: role
    "-t",  # sudo: type
    "-T",  # sudo: timeout
    "-U",  # sudo: user
    "-h",  # sudo: host (over-skips on `-h` alone — acceptable trade-off)
    "-S",  # env: split string
    "-P",  # env: search path
    "-L",  # env: line buffered
    "-A",  # sudo: askpass
    "-B",  # sudo: bell
    "-D",  # sudo: chdir
}

# Long flags accepted by sudo / env that consume the next token as a value
# when written as `--flag value` (the `--flag=value` form is self-contained
# and detected separately). GNU `env` and Linux `sudo` long-option names
# from their man pages.
WRAPPER_LONG_FLAGS_WITH_ARG = {
    # sudo
    "--user",
    "--group",
    "--prompt",
    "--role",
    "--type",
    "--chdir",
    "--command-timeout",
    "--other-user",
    "--login-class",
    "--max-fd",
    "--host",
    "--askpass-program",
    "--bell",
    "--background-host",
    "--directory",
    # env
    "--unset",
    "--split-string",
    "--search-path",
    "--line-buffered",
}

# Prisma global flags that consume the next token (when written as
# `--flag value`; the `--flag=value` form is self-contained). All other
# `--flag`-prefixed tokens are treated as boolean globals (`--preview-feature`,
# `--help`, `--version`, `--no-color`, …) and consume only one position.
PRISMA_FLAGS_WITH_ARG = {
    "--schema",
    "--config",
}

# pnpm-level flags that consume the next token. `pnpm help` lists many more,
# but these are the ones an agent might realistically reach for; if a flag
# we miss takes a value, the worst case is a false positive (we BLOCK a
# safe command because we mistake the flag's value for the script name) —
# never a false negative on a forbidden invocation.
PNPM_FLAGS_WITH_ARG = {
    "--filter",
    "-F",
    "--filter-prod",
    "--test-pattern",
    "--changed-files-ignore-pattern",
    "--dir",
    "-C",
    "--prefix",
    "--reporter",
    "--loglevel",
    "--workspace-concurrency",
    "--registry",
    "--cafile",
    "--cert",
    "--key",
    "--http-proxy",
    "--https-proxy",
    "--no-proxy",
    "--shell-mode",
    "--package-import-method",
    "--store-dir",
    "--cache-dir",
    "--state-dir",
    "--virtual-store-dir",
    "--node-linker",
    "--shamefully-hoist",
}

ENV_VAR_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        sys.exit(0)

    command = (payload.get("tool_input") or {}).get("command")
    if not isinstance(command, str) or not command.strip():
        sys.exit(0)

    try:
        trees = bashlex.parse(command)
    except (bashlex.errors.ParsingError, NotImplementedError):
        # Malformed or unsupported syntax. The Bash tool will surface its own
        # error; we let the call through rather than guess at intent.
        sys.exit(0)

    for argv in iter_command_argvs(trees):
        if is_forbidden(argv):
            emit_deny()
            return

    sys.exit(0)


def iter_command_argvs(trees: Iterable[bashlex.ast.node]) -> Iterator[list[str]]:
    """Yield the (assignments-stripped) argv of every CommandNode in the AST.

    bashlex's CommandNode.parts contains a mix of AssignmentNode (leading
    `FOO=val` env-var assignments) and WordNode (actual command + args). We
    only return the WordNodes' words. Command substitutions inside argument
    words (e.g. `cmd $(prisma migrate dev)`) are recursed into so a
    forbidden invocation hidden inside `$(...)` or backticks is still caught.
    """
    for tree in trees:
        yield from _walk(tree)


def _walk(node: bashlex.ast.node) -> Iterator[list[str]]:
    kind = getattr(node, "kind", None)

    if kind == "command":
        argv: list[str] = []
        for part in getattr(node, "parts", []):
            part_kind = getattr(part, "kind", None)
            if part_kind == "word":
                argv.append(part.word)
                # Recurse into command substitutions embedded in this word
                # (`$(...)` / backticks). Each one gets its own command tree.
                for sub in getattr(part, "parts", []):
                    yield from _walk(sub)
            # AssignmentNode and other parts are deliberately ignored — they
            # don't change which command runs.
        if argv:
            yield argv
        return

    if kind == "commandsubstitution":
        # The substituted command is exposed via .command.
        sub = getattr(node, "command", None)
        if sub is not None:
            yield from _walk(sub)
        return

    # All other node kinds (list, pipeline, compound, function, for, while,
    # if, case, …) wrap their children in one of the well-known iterable
    # attributes. Walk every child generically.
    for attr in ("parts", "list", "commands", "body"):
        for child in getattr(node, attr, []) or []:
            yield from _walk(child)


def is_forbidden(argv: list[str]) -> bool:
    argv = strip_command_prefix(argv)
    if not argv:
        return False

    head = argv[0]
    head_base = basename(head)
    rest = argv[1:]

    if head_base == "prisma":
        return is_prisma_mutate(rest)

    if head_base == "pnpm":
        return is_forbidden_pnpm(rest)

    if head_base == "npx":
        return is_forbidden_npx(rest)

    if head_base == "npm":
        return is_forbidden_npm(rest)

    if head_base == "yarn":
        return is_forbidden_yarn(rest)

    if head_base in {"bash", "sh", "zsh"} and rest and is_prepare_sh(rest[0]):
        return contains_prisma_mutate(rest[1:])

    if is_prepare_sh(head):
        return contains_prisma_mutate(rest)

    return False


def basename(path: str) -> str:
    """Final path component, so `/usr/local/bin/prisma` matches `prisma`."""
    return path.rsplit("/", 1)[-1]


def strip_command_prefix(argv: list[str]) -> list[str]:
    """Drop leading `VAR=val` assignments and `sudo`/`env` wrappers (with
    options).

    bashlex already separates explicit AssignmentNodes from the argv, but a
    user-quoted token like `'FOO=val'` may arrive as a regular WordNode that
    bashlex did not classify as an assignment — we strip those here too.
    """
    out = list(argv)
    while out:
        first = out[0]
        first_base = basename(first)
        if ENV_VAR_RE.match(first):
            out.pop(0)
            continue
        if first_base in {"sudo", "env"}:
            out.pop(0)
            _consume_wrapper_options(out)
            continue
        break
    return out


def _consume_wrapper_options(argv: list[str]) -> None:
    """Pop tokens in place until the wrapped command is at index 0."""
    while argv:
        token = argv[0]
        if ENV_VAR_RE.match(token):
            argv.pop(0)
            continue
        if token == "--":
            argv.pop(0)
            return
        if token.startswith("--"):
            if "=" in token:
                argv.pop(0)  # self-contained `--foo=bar`
            elif token in WRAPPER_LONG_FLAGS_WITH_ARG and len(argv) >= 2:
                argv.pop(0)
                argv.pop(0)
            else:
                argv.pop(0)  # boolean long flag (or unknown — best-effort)
            continue
        if token.startswith("-") and token != "-":
            if token in WRAPPER_SHORT_FLAGS_WITH_ARG and len(argv) >= 2:
                argv.pop(0)
                argv.pop(0)
            else:
                argv.pop(0)
            continue
        return


def is_prisma_mutate(args: list[str]) -> bool:
    """Check whether `prisma <args...>` is a mutating invocation."""
    sub = strip_global_flags(args)
    if len(sub) < 2:
        return False
    return (sub[0], sub[1]) in PRISMA_MUTATE_PAIRS


def strip_global_flags(tokens: list[str]) -> list[str]:
    """Drop top-level flags (e.g. `prisma --schema X migrate dev`).

    Distinguishes flags-with-arg from boolean flags so that
    `prisma --preview-feature migrate dev` correctly leaves `migrate dev`
    behind, and `prisma --schema X migrate dev` consumes `X` along with
    the flag.
    """
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if not token.startswith("-") or token == "-":
            break
        if "=" in token:
            i += 1
            continue
        if token in PRISMA_FLAGS_WITH_ARG and i + 1 < len(tokens):
            i += 2
            continue
        # Boolean flag (or unknown — best-effort one-token skip; unknown long
        # flags that take a value would be a false negative, but Prisma's CLI
        # surface is small enough that PRISMA_FLAGS_WITH_ARG is exhaustive
        # for the value-bearing globals we need to handle).
        i += 1
    return tokens[i:]


def contains_prisma_mutate(tokens: list[str]) -> bool:
    """Find `prisma <mutate>` anywhere in tokens (used for prepare.sh)."""
    for i, token in enumerate(tokens):
        if basename(token) == "prisma" and is_prisma_mutate(tokens[i + 1 :]):
            return True
    return False


def is_prepare_sh(token: str) -> bool:
    return basename(token) in PREPARE_SH_BASENAMES


def is_forbidden_pnpm(args: list[str]) -> bool:
    """Inspect args to `pnpm` and decide whether the invocation mutates."""
    targets, rest = parse_pnpm_flags(args)
    if not rest:
        return False

    head = rest[0]

    if head == "prisma":
        return is_prisma_mutate(rest[1:])

    # `pnpm exec <command...>` / `pnpm dlx <command...>` run an arbitrary
    # command in the package's context. Recurse into the wrapped command so
    # nested forms like `pnpm --filter @shelfalign/database exec bash
    # scripts/prepare.sh prisma migrate dev` are caught — the inner argv hits
    # the bash + prepare.sh case in is_forbidden's main dispatch.
    if head in {"exec", "dlx"} and len(rest) >= 2:
        return is_forbidden(rest[1:])

    if head == "run" and len(rest) >= 2:
        script = rest[1]
    else:
        script = head

    if script not in FORBIDDEN_DATABASE_SCRIPTS:
        return False

    return filter_includes_database_pkg(targets)


def filter_includes_database_pkg(targets: list[str]) -> bool:
    """Return True if any `pnpm --filter <selector>` resolves to a set that
    includes `@shelfalign/database`.

    pnpm's filter syntax (https://pnpm.io/filtering) supports more than the
    exact package name: trailing-dependent forms like `@shelfalign/database...`,
    leading-dependency forms like `...@shelfalign/database`, and directory-glob
    selectors like `{packages/database}` all expand to a list that includes
    the database package. A literal substring match catches every form an
    agent would realistically use; the only false positives are exclusion
    forms (`@shelfalign/database^...`, `...^@shelfalign/database`) which are rare and
    blocking them is the safer error.

    Multiple `--filter` flags compose as a UNION (pnpm docs:
    "the package will be included if it matches at least one of the
    selectors"), so any selector matching the database is enough to
    forbid the command.

    Empty `targets` means no `--filter` was given. In a workspace cwd of
    `packages/database` that resolves to the database package, so we treat
    unspecified as forbidden — same conservative stance taken earlier for
    bare `pnpm migrate`.
    """
    if not targets:
        return True
    return any(_selector_matches_database(t) for t in targets)


def _selector_matches_database(target: str) -> bool:
    selector = strip_quotes(target)
    return "@shelfalign/database" in selector or "packages/database" in selector


def parse_pnpm_flags(args: list[str]) -> tuple[list[str], list[str]]:
    """Walk past pnpm-level flags and return (filter targets, remaining args).

    Handles both `--flag value` and `--flag=value` forms. Flags known to take
    a separate value (PNPM_FLAGS_WITH_ARG) consume two tokens; all other
    `-`-prefixed tokens are treated as booleans and consume one.

    pnpm's documented behaviour for repeated `--filter` flags is union — a
    package is included if it matches *any* selector — so we collect every
    target into a list rather than overwriting on each one.
    """
    targets: list[str] = []
    i = 0
    while i < len(args):
        token = args[i]
        if token == "--":
            i += 1
            break
        # Self-contained `--flag=value` forms.
        if token.startswith("--filter="):
            targets.append(token[len("--filter=") :])
            i += 1
            continue
        if token.startswith("-F="):
            targets.append(token[len("-F=") :])
            i += 1
            continue
        if token.startswith("--") and "=" in token:
            i += 1
            continue
        # Separate-token forms.
        if token in {"--filter", "-F"}:
            if i + 1 < len(args):
                targets.append(args[i + 1])
            i += 2
            continue
        if token in PNPM_FLAGS_WITH_ARG and i + 1 < len(args):
            i += 2
            continue
        if token.startswith("-") and token != "-":
            i += 1
            continue
        break
    return targets, args[i:]


NPX_FLAGS_WITH_ARG = {
    "-p",
    "--package",
    "-c",
    "--call",
    "--prefix",
}

NPM_GLOBAL_FLAGS_WITH_ARG = {
    "--prefix",
    "--workspace",
    "-w",
    "--registry",
    "--cache",
}


def is_forbidden_npx(args: list[str]) -> bool:
    """`npx [flags...] <command> <command-args...>` runs an npm package's
    binary. Skip npx-level flags and recurse into the wrapped command so
    `npx prisma migrate dev` and `npx -y prisma migrate dev` are both caught.
    """
    rest = _strip_known_flags(args, NPX_FLAGS_WITH_ARG)
    if not rest:
        return False
    return is_forbidden(rest)


def is_forbidden_npm(args: list[str]) -> bool:
    """Inspect `npm [flags...] <subcommand> <args...>`.

    npm parses its own flags from anywhere in the command line — `npm run
    migrate -w teacher` and `npm -w teacher run migrate` are equivalent —
    so collect workspace selectors regardless of position before deciding.

    `npm exec [--] <command...>` recurses (matches npx semantics).
    `npm run|run-script <script>` BLOCKs when the script is one of the
    forbidden @shelfalign/database scripts AND the workspace selectors include
    the database (or are unset, since npm in `packages/database`
    resolves to the database package).
    """
    workspaces, cleaned = _extract_npm_workspaces(args)
    if not cleaned:
        return False

    head = cleaned[0]
    rest = cleaned[1:]

    if head == "exec":
        sub = rest
        if sub and sub[0] == "--":
            sub = sub[1:]
        sub = _strip_known_flags(sub, NPX_FLAGS_WITH_ARG)
        return is_forbidden(sub)

    if head in {"run", "run-script"} and rest:
        script = rest[0]
        if script in FORBIDDEN_DATABASE_SCRIPTS:
            return filter_includes_database_pkg(workspaces)

    return False


def is_forbidden_yarn(args: list[str]) -> bool:
    """yarn classic: `yarn [run] <script>`. yarn berry adds `yarn exec`
    and `yarn dlx` (similar to pnpm). Cover both.
    """
    if not args:
        return False

    head = args[0]
    rest = args[1:]

    if head in {"exec", "dlx"} and rest:
        return is_forbidden(rest)

    if head == "run" and len(rest) >= 1:
        script = rest[0]
    else:
        script = head

    if script in FORBIDDEN_DATABASE_SCRIPTS:
        # yarn doesn't have pnpm's --filter equivalent in the same form;
        # be conservative and treat as targeting the database (yarn run
        # without workspace flags resolves to package.json in cwd, which
        # for an agent in @shelfalign/database is the database package).
        return True

    return False


def _strip_known_flags(args: list[str], with_arg: set[str]) -> list[str]:
    i = 0
    while i < len(args):
        token = args[i]
        if token == "--":
            i += 1
            break
        if "=" in token and token.startswith("-"):
            i += 1
            continue
        if token in with_arg and i + 1 < len(args):
            i += 2
            continue
        if token.startswith("-") and token != "-":
            i += 1
            continue
        break
    return args[i:]


def _extract_npm_workspaces(
    args: list[str],
) -> tuple[list[str], list[str]]:
    """Scan every token, peeling off workspace selectors regardless of
    position. Returns (workspaces, args with workspace-flag tokens removed).

    npm accepts flags anywhere in the argv — `npm run migrate -w teacher`
    has the same meaning as `npm -w teacher run migrate`. Stopping at the
    first non-flag (as `parse_pnpm_flags` does for pnpm) misses post-
    subcommand workspace flags.

    Stops scanning at `--` so script arguments aren't mistakenly read as
    npm flags. Other npm flags (`--prefix`, `--registry`, etc.) are
    preserved in the cleaned output — only workspace flags are extracted.
    """
    workspaces: list[str] = []
    cleaned: list[str] = []
    i = 0
    while i < len(args):
        token = args[i]
        if token == "--":
            cleaned.extend(args[i:])
            break
        if token.startswith("--workspace="):
            workspaces.append(token[len("--workspace=") :])
            i += 1
            continue
        if token in {"--workspace", "-w"}:
            if i + 1 < len(args):
                workspaces.append(args[i + 1])
                i += 2
                continue
            i += 1
            continue
        if token == "--workspaces":
            workspaces.append("@shelfalign/database")  # wildcard implicates all
            i += 1
            continue
        cleaned.append(token)
        i += 1
    return workspaces, cleaned


def strip_quotes(value: str) -> str:
    """Defensive — bashlex usually strips shell quotes already."""
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def emit_deny() -> None:
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": DENY_REASON,
                }
            }
        )
    )


if __name__ == "__main__":
    main()
