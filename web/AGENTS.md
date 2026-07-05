# AGENTS.md (CLAUDE.md)

This file provides guidance to Claude Code (claude.ai/code) and other AI agents when working with code in this repository.  

## Project Overview

ShelfAlign is a full-stack TypeScript monorepo for library shelf analysis, book-spine OCR, and shelf order verification.

### Project Structure

- Backoffice: React admin app for shelf scan review and library operations.
- Backend: NestJS API for authentication, upload, organization, provider, and library operations.
- Database: Prisma database schema that is shared between all services  
- Schema: Zod schema definition that is shared between all services. Contains DTOs for request(body) and response  

### Project Tech Stack

All versions are managed in [pnpm-workspace.yaml](pnpm-workspace.yaml). Versions written below may differ from actual project settings. Refer to [pnpm-workspace.yaml](pnpm-workspace.yaml), [package.json](package.json) as source of truth  

Node version is 24. Version may differ from actual project settings, refer to [.node-version](.node-version) as source of truth

- Backoffice: React 19, Vite 7, Tanstack Router, Tanstack Query, Tailwind CSS 4
- Backend: Nest.js 11, Express  
- Database: Prisma 6  
- Schema: Zod 4  

Zod 4 is quite recently released, check [official zod documents](https://zod.dev/) for API references and be careful not to use deprecated schemas

## Important notes

- Run lint whenever a user request is finished. Run `pnpm --filter (scope) lint --fix` to fix lint errors.  
- Run type check whenever a user request is finished. Run `pnpm --filter (scope) check-types` to check type errors.
- Install packages and run commands with pnpm only. npm and yarn is not used and will break node_modules directory  
- Use shadcn if possible.
- If `components/ui/(component-name)` folder exist, assume (component-name) shadcn component is installed. When new component create `component/ui/(component-name).ts`, delete it and use `component/ui/(component-name)/index.ts`
- Import lucide-react icons with `Icon` suffix.
- use `useWatch` rather than `form.watch` or `control.watch` when using `react-hook-form`
- Before implementing new feature, always check if there is an existing implementation in other places that can be reused.
- For frontend code, split utility functions into `-lib/*.ts` files rather than putting them in the page or component files.
- Do not use spread operator(`...`) with undefined checking for partial updating database records with prisma. Prisma handles partial updates, skipping undefined fields.
- Read [docs/you-might-not-need-an-effect.md](docs/you-might-not-need-an-effect.md) and only use `useEffect` when necessary.
- Frontend apps should use database schemas from `@shelfalign/database/types` rather than `@shelfalign/database` directly to prevent bundling node-specific code into frontend bundles.
- Strongly prefer `useSuspenseQuery` over `useQuery` for data fetching in React components to leverage React Suspense for loading states.
- Prefer `useSuspense-` prefixed hooks over regular hooks if both are available.
- Use `@ParamId` decorator in NestJS for extracting ID parameters from route paths instead of manually parsing them from `@Param()`.

## Code Commit

- Always write commit messages in English, even if the codebase contains Korean comments or identifiers. This ensures that the commit history is accessible to all contributors, regardless of their native language.
- Follow the conventional commit format for commit messages. The format is: `<type>(<scope>): <subject>`. For example: `feat(auth): add JWT authentication`.
- Run tests and linters before committing code to ensure code quality and prevent breaking changes from being merged into the main branch.

## Prisma Migrations

**Agents must NEVER apply migrations.** Only the human operator may apply changes to a database. The following commands are **forbidden** and are blocked at the tool layer by `.claude/hooks/block-prisma-db-mutate.py` (parses the bash AST via [bashlex](https://github.com/idank/bashlex) so it sees through pipelines, subshells, command substitutions, function bodies, etc.):

- `prisma migrate dev` — even with `--create-only`. Prisma applies any pending migrations on disk as a side-effect before generating the next one, so even "just generating" can mutate the database.
- `prisma migrate deploy`
- `prisma migrate reset`
- `prisma db push`
- The `pnpm --filter @shelfalign/database migrate` / `deploy` / `reset` wrappers and any direct invocation of `scripts/prepare.sh` with the above subcommands.

To generate migration SQL **without** applying it, use the read-only diff. The Prisma artifacts live in `packages/database/prisma/`, so run from that directory (or pass an explicit path):

```bash
cd packages/database
pnpm prisma migrate diff \
  --from-migrations ./prisma/migrations \
  --to-schema ./prisma/schema.prisma \
  --script
```

Pipe the output into `packages/database/prisma/migrations/<UTC-timestamp>_<snake_case_name>/migration.sql` (create the directory by hand). This produces the same SQL Prisma would have generated under `migrate dev`, but does not touch the database.

### Editing migration files

Hand-editing a migration file is permitted **only** if both:

1. The migration was authored by the same agent session that is editing it, AND
2. The migration has not yet been applied to any environment.

This is the supported way to fold backfill statements into a single migration (e.g. between an `ADD COLUMN` and a follow-up `ALTER COLUMN ... SET NOT NULL`).

Editing a migration that has been applied to any environment, or a migration authored by another contributor / earlier session, is **strictly prohibited** — applied migrations are immutable history. To change them, introduce a new migration on top.

### Hook prerequisites

The migration guard hook is run via `uv run --script` and uses PEP 723 inline metadata to declare its `bashlex` dependency, so no manual install is required — `uv` materialises the env on first invocation and caches it. If you don't have `uv` installed:

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh
# or
pip install --user uv
```

Without `uv` available, the Bash tool will fail with `uv: command not found` instead of silently allowing forbidden commands — the failure mode is fail-closed, by design.

## Worktrees

When working on multiple features or branches simultaneously, use Git worktrees to manage separate working directories for each branch. This allows you to switch between branches without having to stash changes or commit unfinished work. To create a new worktree for a branch, use the command `git worktree add ./.worktrees/(branch-name) (branch-name)`. This will create a new directory for the branch where you can make changes independently from the main working directory.
