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

Follow [`.github/instructions/org/git-conventions.instructions.md`](.github/instructions/org/git-conventions.instructions.md): commit identity, attribution, branch names, commit messages, changelog and releases. Template owns that file and Renovate keeps it current; do not edit it here. Rules specific to this repository go in This Repository below and take precedence.

## This Repository

Replace this section when you create a repository from the template. Keep it short and factual.

- What it is, its stack, and where the code lives: <fill in>.
- Validate with: <the lint, test and build commands; CI runs the same>.
- Default branch: `main` <or the branch work starts from, such as `dev`>.
- Set the version with: <the project's tooling, if it has a version file>.
- Verify `origin/main` and any file or command named here exist before relying on them; report gaps instead of inventing them.
