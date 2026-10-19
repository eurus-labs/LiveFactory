# AGENTS.md — Instructions for AI Agents and Harnesses

This file defines how to work in this repository. Keep it under 120 lines.
Keep product requirements and architecture in task-specific documents, not here.
Write repository documentation in English; converse in the user's language.

## Response Style

- Answer the current question directly; lead with the main conclusion.
- Scale depth to the question, complexity, and risk. Do not turn a simple answer into a post-mortem.
- Explain mechanisms and causal reasoning in plain language; define jargon when it helps.
- State assumptions and distinguish verified facts, inferences, and proposals.
- Support implementation claims with relevant code locations, logs, or test evidence. State what remains unverified.
- Quantify when measurements exist; never invent numbers or imply precision without evidence.
- Offer judgments and recommendations with reasons, rather than merely listing information.

## Start Each Task

1. Read this file and any instructions scoped to the files you will touch.
2. Identify the requested outcome and any decisions already approved in the
   conversation. Do not restart discovery for settled decisions.
3. Discover the specification, design, and plan relevant to the current task.
   Start with user-provided references and `docs/`, then search by feature,
   component, or affected code. Check scope, approval status, and superseding
   decisions before applying a document; do not pick it only for its date.
   If no applicable document exists, state that and plan at the task's scale.
4. Inspect the actual files, interfaces, dependencies, tests, and working-tree
   changes relevant to the task before proposing edits.
5. Distinguish implemented behavior, approved requirements, and proposals.
   A document describing a command or component does not prove it exists.

## Interpret References Correctly

- Documents may reference other repositories or proposed interfaces. Verify ownership and availability before using them.
- Do not assume an external runtime, command, or configuration exists here.
- Before implementing an integration, verify its interface and resolve where the new code belongs. Do not silently copy or modify another repository; when working in one, read its instructions.
- Surface material conflicts between code, documents, and current user decisions. Do not silently convert an assumption into a requirement.

## Preserve the User's Reasoning Ownership

Use Problem → Design → Predict → Build → Validate → Learn.

- Let the user own problem framing, initial design, trade-offs, and technical decisions. Critique their reasoning after they have expressed it.
- Ask targeted questions only for unresolved decisions that affect the work and need the user's judgment. Reuse answers already given; do not turn each step into a questionnaire.
- Before a meaningful implementation, elicit failure predictions if they have not been stated, then add overlooked risks. If the user has none, state the risks with how you will handle them and proceed.
- Implement authorized work, including routine code, tests, and documentation.
- Report validation evidence; leave final product acceptance to the user.
- After a meaningful experiment, compare predictions with outcomes and record the lesson.

## Apply Feature-Centered Rings (FCR)

- Identify the central feature and its minimum value; work on the nearest component blocking it, and widen scope only for an actual blocker (say which one it removes).
- When work is too difficult, split it, reduce scope, or change the approach. Verify the complete feature after integration.

## Plan and Implement

- Scale the plan to the task. Use the existing approved plan when applicable; a small edit needs a short stated approach, not a new architecture document.
- Preserve unrelated local changes. Avoid destructive replacements without explicit authorization; prefer isolated, reviewable changes.
- Reuse verified capabilities before adding new abstractions or dependencies.
- Keep responsibilities and interfaces clear. If delegating, give the goal, inputs, output contract, allowed scope, and acceptance checks; review returned artifacts rather than trusting completion summaries.
- Keep requirements, assumptions, decisions, and observed results distinct in the PR description (and `docs/` for lasting design). Do not rely on conversation memory as the only record.

## Validate and Report

- Use tests appropriate to the change. For features and bug fixes, include failure cases and relevant integration behavior, not only happy paths.
- Run the affected user flow when feasible. Unit tests alone do not establish that the integrated application works.
- Do not claim commands, tests, or live runs succeeded without observing them. State what was checked, what failed, and what remains unverified.
- Keep credentials out of code, documents, logs, and test fixtures. Use test doubles for tests that would otherwise call external services or model providers.
- Update affected documentation when behavior or a decision changes.
- Do not commit or publish merely because a plan lists a future Git step.

## Branches and Commits — Read Before Every Git Command

- Commit as the human author you are working for, never as an AI or tool identity: their name and GitHub no-reply address (`<id>+<login>@users.noreply.github.com`) for both author and committer, never a private email. Take it from the user, or from the latest commits on the default branch whose author email is a no-reply address (`git log origin/main --format='%an <%ae>'`); never from the committer field. Ask if it is unclear.
- Never persist `user.name` or `user.email` with `git config`. The environment may hold another identity (a global config, or preset `GIT_AUTHOR_*` variables that win over `-c user.email`).
- Set the identity as environment variables at the start of every command that writes a commit (commit, merge, cherry-pick, revert, amend, each `rebase` and `rebase --continue`): `GIT_AUTHOR_NAME='<name>' GIT_AUTHOR_EMAIL='<no-reply>' GIT_COMMITTER_NAME='<name>' GIT_COMMITTER_EMAIL='<no-reply>' git commit ...`. Shell state does not carry over between tool calls.
- Before every push, `git log origin/main..HEAD --format='%an <%ae> | %cn <%ce>' | sort -u` must print one line, with the author's no-reply identity on both sides; if not, recommit before pushing.
- Never add AI/tool attribution, co-author/session trailers, generated-by footers, or AI session links to commits, PRs, comments, or documents. Some tools append a footer on their own: read back each PR body or comment you post and remove it. CI fails a pull request that carries one.
- Never push to `claude/*`; never put `codex` or `claude` in branch names or PR titles.
- Name work branches `<type>/<area>-<outcome>` in lowercase kebab-case, with `<type>` one of `feat`, `fix`, `docs`, `refactor`, `test`, `build`, `ci`, `chore`. The name must say what the branch changes (for example `fix/graph-dangling-lanes`), never a vague word, a bare ticket number, or a date. No session suffixes or tool prefixes.
- Start work from the latest default branch (`origin/main` unless This Repository names another): fetch, then branch from it. If it advances, fetch and rebase before pushing. Rebasing your own unmerged branch and pushing with `--force-with-lease` is expected; never rewrite the default branch or someone else's branch.
- Never amend or rewrite a commit that is on the default branch or in a merged PR; create a new commit instead.
- Follow Conventional Commits 1.0.0: lowercase type/scope, imperative subject, at most 72 characters, no trailing period; wrap the body at 72 columns and explain why. CI checks the PR title, every commit subject, and that each commit's author and committer use the same no-reply address.
- Breaking changes require both `!` and a `BREAKING CHANGE:` footer.
- Update `CHANGELOG.md` (Keep a Changelog, under the upcoming version) before every PR; keep entries user-facing and summary-only. Parallel PRs conflict there: keep both entries under one version heading, and bump the version once.
- Release by tagging the default branch with the version (for example `1.2.0`) and publishing a GitHub release; the tag is the version of record. If you cannot create the tag or release, hand the user the tag, the target SHA and the release notes, and stop.

## This Repository

Replace this section when you create a repository from the template. Keep it short and factual.

- What it is, its stack, and where the code lives: <fill in>.
- Validate with: <the lint, test and build commands; CI runs the same>.
- Default branch: `main` <or the branch work starts from, such as `dev`>.
- Set the version with: <the project's tooling, if it has a version file>.
- Verify `origin/main` and any file or command named here exist before relying on them; report gaps instead of inventing them.
