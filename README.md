# Project name

> **New repository?** Create it with [Copier](https://copier.readthedocs.io), not GitHub's
> "Use this template" button, so it can receive Template updates:
>
> ```sh
> pipx run copier copy --trust gh:eurus-labs/Template my-project
> ```
>
> Then work through this list and delete this note:
>
> 1. Replace the title and the placeholder sections below.
> 2. Fill in **This Repository** at the end of [`AGENTS.md`](AGENTS.md): stack, validation commands,
>    default branch.
> 3. Add your build and test jobs to [`.github/workflows/ci.yml`](.github/workflows/ci.yml) and list
>    them in `verify`'s `needs`.
> 4. Check the copyright line in [`LICENSE`](LICENSE).
> 5. In the repository ruleset, require the checks `verify` and `commits / conventional-commits`.
>
> Template owns `.github/instructions/org/`, `.github/workflows/commits.yml` and `renovate.json`.
> Do not edit them here: Renovate opens a pull request with each Template release. Issue forms, the
> pull request template, `CONTRIBUTING.md` and `SECURITY.md` come from the organization's
> [.github](https://github.com/eurus-labs/.github) repository.

One sentence: what this project does, and for whom.

## Use

How to install and run it.

## Develop

The commands to run before opening a pull request: lint, test, build.

## License

[MIT](LICENSE)
