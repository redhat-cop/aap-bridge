# Contributing

Thank you for your interest in contributing to AAP Bridge!

## Code of Conduct

This project follows the [AAP Bridge Code of
Conduct](https://github.com/redhat-cop/aap-bridge/blob/main/CODE_OF_CONDUCT.md).
By participating, you are expected to uphold this code.

## How to Contribute

### Reporting Bugs

Before submitting a bug report:

1. **Search existing issues** to avoid duplicates
2. **Try the latest version** from the `main` branch
3. **Gather information**:
   - AAP Bridge version (`aap-bridge --version`)
   - Source/Target AAP versions
   - Error messages and logs (scrubbed of secrets!)

When opening an issue:

- Use a clear, descriptive title
- Describe steps to reproduce
- Include expected vs actual behavior
- Attach relevant logs

### Suggesting Features

Open an issue with:

- Clear description of the feature
- Use case / problem it solves
- Proposed implementation (if you have ideas)

### Pull Requests

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/amazing-feature`
3. Make your changes
4. Run tests and checks: `make check`
5. Commit your changes
6. Push to your fork: `git push origin feature/amazing-feature`
7. Open a Pull Request

## Development Setup

### Prerequisites

- Python 3.12 (required)
- **uv** (recommended) or **pip** with the stdlib `venv` module (`python3.12-venv` on Debian/Ubuntu)
- PostgreSQL (for integration tests)

### Setup

`make setup` creates `.venv`, installs dev dependencies, and seeds `.env`.
It prefers **uv** when installed; pass `USE_UV=0` to use **pip** instead.

```bash
# Clone your fork
git clone https://github.com/YOUR_USERNAME/aap-bridge.git
cd aap-bridge

make setup

# Interactive CLI usage only — make test/lint/etc. use .venv/bin directly
source .venv/bin/activate

```

### Running Tests

```bash
# All tests
make test

# Unit tests only (fast)
make test-unit

# With coverage
make test-cov

# Specific test file
.venv/bin/pytest tests/unit/test_exporter.py -v

```

### Ephemeral AAP integration testing

For end-to-end migration testing against real AAP instances (golden images, source/target
pairs, `make test-bridge`), see [Testing with Ephemeral AAP Instances](testing.md).
That workflow uses podman on the host and does not require a local Python install for the
AAP side of the stack.

### Code Quality

Before submitting:

```bash
# Format code
make format

# Run linter
make lint

# Type checking
make typecheck

# All checks
make check

```

## Code Style

### Python Style

- **Formatter**: `black` (line length: 100)
- **Linter**: `ruff`
- **Type checker**: `mypy`

### Naming Conventions

- `snake_case` for functions and variables
- `PascalCase` for classes
- `UPPER_CASE` for constants
- Descriptive names over abbreviations

### Documentation

- Docstrings for all public functions/classes
- Type hints for all function signatures
- Comments for complex logic

### Example

```python
async def import_resources(
    self,
    resources: list[dict[str, Any]],
    progress_callback: Callable[[int, int], None] | None = None,
) -> list[dict[str, Any]]:
    """Import resources to target AAP.

    Args:
        resources: List of resource dictionaries to import
        progress_callback: Optional callback for progress updates

    Returns:
        List of successfully imported resources

    Raises:
        APIError: If API request fails
    """
    ...

```

## Git Commit Messages

- Use present tense: "Add feature" not "Added feature"
- Use imperative mood: "Move cursor" not "Moves cursor"
- First line: 72 characters or less
- Reference issues: "Fix #123: Handle edge case"

### Good Examples

```text
Add bulk import support for hosts

Implement bulk host creation using AAP's /bulk/host_create endpoint.
This improves import performance by ~10x for large inventories.

Fixes #45

Fix rate limiting during export

- Add exponential backoff on 429 responses
- Respect Retry-After header
- Add configurable rate limit settings
```

## Adding New Features

### Adding a New Resource Type

See [Adding Resource Types](adding-resource-types.md) for the complete guide.

### Adding a New Command

1. Create command file in `src/aap_migration/cli/commands/`
2. Register in `src/aap_migration/cli/main.py`
3. Add tests in `tests/unit/cli/`
4. Document in `docs/user-guide/cli-reference.md`

## Testing Guidelines

### Unit Tests

- Test individual functions in isolation
- Mock external dependencies
- Fast execution (< 1 second per test)

### Integration Tests

- Test with real AAP instances (when available)
- Mark with `@pytest.mark.integration`
- Use fixtures for setup/teardown

### Test Coverage

Aim for high coverage but prioritize meaningful tests:

```bash
# Check coverage
make test-cov

# View HTML report
open htmlcov/index.html

```

## Release Process

1. Update version in `pyproject.toml`
2. Update `CHANGELOG.md`
3. Create a PR with version bump
4. After merge, tag the release: `git tag v0.2.0`
5. Push tags: `git push --tags`

## Getting Help

- Open an issue for questions
- Join discussions on GitHub
- Check existing documentation

## License

By contributing, you agree that your contributions will be licensed under the
GPL-3.0 License.
