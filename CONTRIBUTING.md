# Contributing to Scientific Dataset Catalog

Thank you for your interest in contributing to the Scientific Dataset Catalog! This project helps researchers manage scientific datasets, their relationships, and metadata across research workflows.

## Quick Navigation

- 🐛 **[Reporting Bugs](#reporting-bugs)** - Found an issue? Start here
- 💻 **[Code Contributions](#code-contributions)** - Want to submit code changes?
- 📋 **[Code Standards](#code-standards)** - Style and testing guidelines
- 🔄 **[Pull Request Process](#pull-request-process)** - Step-by-step PR workflow
- 🔒 **[Security & Conduct](#security--conduct)** - Important policies
- ❓ **[Getting Help](#getting-help)** - Where to ask questions

---

## Reporting Bugs

Found a bug? We appreciate your help in improving the project!

### Before Submitting a Bug Report

- **Search existing issues** to see if the bug has already been reported
- **Try the latest version** to see if the issue has been fixed
- **Gather information** about your environment (Python version, operating system)

### What is a Bug?

A bug is when the software doesn't work as documented or expected. Examples:
- Functions that raise unexpected errors
- Incorrect data returned from API calls
- Installation or setup issues
- Documentation that doesn't match the actual behavior

**Not bugs:** Feature requests, questions about usage, or requests for new functionality should be submitted as regular GitHub issues with appropriate labels.

### How to Submit a Bug Report

When creating a bug report, please include:

1. **Clear title** - Briefly describe the issue
2. **Python and package versions** - Run `python --version` and `pip show catalog-client`
3. **Operating system** - Windows, macOS, Linux distribution
4. **Steps to reproduce** - Minimal code example that demonstrates the issue
5. **Expected behavior** - What you expected to happen
6. **Actual behavior** - What actually happened, including full error messages
7. **Additional context** - Screenshots, logs, or other relevant information

### Example Bug Report

`````markdown
**Title:** CatalogClient.datasets.list() fails with SSL error on macOS

**Environment:**
- Python: 3.12.1
- catalog-client: 0.1.0
- OS: macOS 14.2

**Steps to reproduce:**
```python
from catalog_client import CatalogClient
with CatalogClient(base_url="https://example.com", api_token="test") as client:
    client.datasets.list()
```

**Expected:** Returns list of datasets
**Actual:** Raises SSLError: certificate verify failed
**Full error:** [paste complete traceback]
`````

---

## Code Contributions

Want to contribute code? Great! Here's how to get set up and submit your changes.

### Prerequisites

Before you start, make sure you have:
- **Python 3.12 or higher** - Run `python --version` to check
- **Git** - For version control
- **uv** - Python package manager ([installation guide](https://docs.astral.sh/uv/getting-started/installation/))

### Quick Setup for Small Fixes

This is the minimal setup for external contributors making small bug fixes or improvements:

1. **Fork and clone the repository**
   ```bash
   # Fork the repo on GitHub, then clone your fork
   git clone https://github.com/YOUR-USERNAME/dataset-catalog.git
   cd dataset-catalog/dataset-catalog-client
   ```

2. **Install dependencies**
   ```bash
   # Install the package with development dependencies
   uv sync --group dev
   ```

3. **Verify setup works**
   ```bash
   # Run tests to make sure everything is working
   uv run pytest
   ```

4. **Make your changes**
   - Create a new branch: `git checkout -b fix-issue-123`
   - Make your code changes
   - Add or update tests as needed

5. **Test your changes**
   ```bash
   # Run tests to make sure your changes work
   uv run pytest

   # Format and check code style
   uv run ruff format .
   uv run ruff check .
   ```

6. **Submit a pull request**
   - Push to your fork: `git push origin fix-issue-123`
   - Create a pull request on GitHub

### Development Workflow

#### Branch Naming Conventions

Use descriptive branch names that indicate the type of change:
- `feature/add-collection-filtering` - New features
- `bugfix/fix-ssl-error` - Bug fixes
- `docs/update-readme` - Documentation changes
- `test/add-lineage-tests` - Test improvements

#### Running Tests

```bash
# Run all tests
uv run pytest

# Run specific test file
uv run pytest tests/client/test_datasets.py

# Run with verbose output
uv run pytest -v

# Run tests and show coverage
uv run pytest --cov=catalog_client
```

#### Code Formatting

We use `ruff` for code formatting and linting. Run these before submitting:

```bash
# Format code
uv run ruff format .

# Check for style issues
uv run ruff check .

# Fix auto-fixable issues
uv run ruff check --fix .
```

#### Testing Against Live API (Optional)

For integration testing, you can test against a live catalog instance:

1. Set up environment variables:
   ```bash
   export CATALOG_BASE_URL="https://your-catalog-instance.com"
   export CATALOG_API_TOKEN="your-api-token"
   ```

2. Run integration tests:
   ```bash
   # Run examples to verify they work
   uv run jupyter execute examples/quickstart.ipynb
   ```

#### Local Development Tips

- **Work in the `dataset-catalog-client/` directory** - This is where the Python package lives
- **Check existing tests** - Look at `tests/` for examples of how to test similar functionality
- **Use examples/** - The `examples/` directory contains working code you can reference
- **Keep changes focused** - Smaller, focused changes are easier to review and merge

---

## Code Standards

### Style Guidelines

We use automated tools to handle code formatting, so you don't need to worry about manual style requirements:

- **Formatting:** We use `ruff` for code formatting - run `uv run ruff format .`
- **Linting:** We use `ruff` for linting - run `uv run ruff check .`
- **Import sorting:** Handled automatically by ruff
- **Line length:** Follows ruff defaults (we ignore E501 in our config)

Just run the formatting and linting commands, and the tools will handle the rest!

### Testing Requirements

When contributing code, please:

- **Add tests for new functionality** - If you're adding a new feature, include tests that verify it works
- **Ensure existing tests pass** - Run `uv run pytest` to make sure you didn't break anything
- **Focus on testing public API behavior** - Test the functionality users will interact with, not internal implementation details
- **Use mocking for external services** - Follow examples in existing test files for how to mock HTTP calls and external dependencies

### Documentation

For code contributions:

- **Update docstrings** - Add or update docstrings for new public methods and classes
- **Update examples** - If you're adding new features, consider adding examples to the `examples/` directory
- **Focus on code clarity** - Write clear, readable code rather than extensive comments

---

## Pull Request Process

Ready to submit your changes? Here's the step-by-step process:

### Step-by-Step Workflow

1. **Fork the repository**
   - Click "Fork" on the GitHub repository page
   - Clone your fork locally

2. **Create a feature branch**
   ```bash
   git checkout -b feature/your-feature-name
   # or
   git checkout -b bugfix/fix-description
   ```

3. **Make your changes and test locally**
   ```bash
   # Make your code changes
   # Run tests
   uv run pytest
   # Format code
   uv run ruff format .
   uv run ruff check .
   ```

4. **Push to your fork**
   ```bash
   git push origin feature/your-feature-name
   ```

5. **Create a pull request**
   - Go to the original repository on GitHub
   - Click "New Pull Request"
   - Select your branch and fill out the PR template

6. **Wait for review**
   - Our CI will automatically run tests and linting
   - A maintainer will review your changes
   - We may ask questions or request changes

### Pull Request Requirements

For your PR to be accepted, it must:

- **Have a clear description** - Explain what the change does and why it's needed
- **Reference related issues** - Link to any GitHub issues this addresses (e.g., "Fixes #123")
- **Pass all CI checks** - Tests and linting must pass
- **Have at least one approving review** - A maintainer must approve your changes

### What to Expect

- **Response time:** We typically respond to pull requests within a few business days
- **Automated testing:** Our CI system will automatically run tests and code quality checks
- **Code review:** A maintainer will review your code for correctness and fit with project goals
- **Questions and feedback:** We may ask questions or request changes - this is normal and helps ensure quality
- **Merge process:** Once approved, a maintainer will merge your PR (you don't need to handle the merge)

### After Your PR is Merged

- **Clean up your branch** - You can delete your feature branch after it's merged
- **Thank you!** - Your contribution helps make the project better for everyone

---

## Security & Conduct

### Security Issues

If you believe you have found a security issue, please **do not create a public GitHub issue**. Instead:

- **Contact us privately:** Send an email to [security@chanzuckerberg.com](mailto:security@chanzuckerberg.com)
- **Include details:** Provide a clear description of the issue and steps to reproduce it
- **Be patient:** We'll respond as quickly as possible and work with you to resolve the issue

For more information, see our [Security Policy](SECURITY.md).

### Code of Conduct

This project adheres to the Contributor Covenant [code of conduct](https://github.com/chanzuckerberg/.github/blob/master/CODE_OF_CONDUCT.md). By participating, you are expected to uphold this code.

Examples of behavior that contributes to a positive environment:
- Using welcoming and inclusive language
- Being respectful of differing viewpoints and experiences
- Gracefully accepting constructive criticism
- Focusing on what is best for the community

If you experience or witness unacceptable behavior, please contact [opensource@chanzuckerberg.com](mailto:opensource@chanzuckerberg.com).

---

## Getting Help

Need help getting started or have questions? Here's where to find answers:

### For Usage Questions

- **Check the documentation** - Start with [USAGE.md](dataset-catalog-client/USAGE.md) for comprehensive usage examples
- **Browse examples** - Look at the [examples/](dataset-catalog-client/examples/) directory for interactive Jupyter notebooks
- **Review the README** - The [client README](dataset-catalog-client/README.md) has quick start instructions

### For Bugs and Issues

- **Search existing issues** - Check [GitHub Issues](https://github.com/chanzuckerberg/dataset-catalog/issues) to see if someone else has reported the same problem
- **Create a new issue** - If you don't find an existing issue, [create a new one](https://github.com/chanzuckerberg/dataset-catalog/issues/new)

### For Security Concerns

- **Security issues** - Email [security@chanzuckerberg.com](mailto:security@chanzuckerberg.com) for security-related concerns
- **Don't create public issues** - Security issues should be reported privately

### For General Questions

- **GitHub Issues** - For project-related questions, feel free to [create a GitHub issue](https://github.com/chanzuckerberg/dataset-catalog/issues/new)
- **Code of Conduct issues** - Contact [opensource@chanzuckerberg.com](mailto:opensource@chanzuckerberg.com)

---

## Thank You!

Thank you for taking the time to contribute to the Scientific Dataset Catalog. Whether you're reporting bugs, submitting code, or improving documentation, your contributions help make this project better for the entire research community.

We appreciate your effort and look forward to collaborating with you! 🚀
