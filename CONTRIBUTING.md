# Contributing to AAP Bridge

Thanks for contributing!

This project follows the [AAP Bridge Code of Conduct](CODE_OF_CONDUCT.md).

## Full developer guide

The complete contributing guide — setup, tests, style, resource types, and
release process — lives in the docs:

- **In this repo:** [docs/developer-guide/contributing.md](docs/developer-guide/contributing.md)
- **Published:** [contributing guide](https://redhat-cop.github.io/aap-bridge/developer-guide/contributing/)

Please read that guide before opening a PR. The notes below are a short
checklist only.

## Quick start

```bash
make setup                 # creates .venv, installs deps, installs git hooks
source .venv/bin/activate  # only needed for interactive aap-bridge usage
make check                 # format + lint + typecheck + tests
```

`make setup` runs `pre-commit install`. Hooks run on commit (format, lint, unit
tests, gitleaks, and ansible-lint for integration Ansible). CI enforces the same
checks even if you skipped hook install — see the developer guide.

## Pull requests

1. Fork and branch from `main`.
2. Add tests for new behavior; update docs for API/CLI changes.
3. Run `make check` (and `make web-build` / `make web-test` / `make ansible-lint`
   when those areas change).
4. Open a PR with a clear description.

## Reporting bugs

Search existing issues first, then open a new one with a clear title, steps to
reproduce, expected vs actual behavior, and scrubbed logs.

## License

By contributing, you agree that your contributions will be licensed under the
GPL-3.0 License.
