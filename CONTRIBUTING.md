# Contributing to Open Researcher

Thanks for your interest in contributing!

## Development Setup

```bash
git clone https://github.com/open-researcher/open-researcher.git
cd open-researcher
python -m venv .venv
source .venv/bin/activate
make dev
```

## Running Tests

```bash
make test
make test-cov
make package-check
```

## Code Style

We use [ruff](https://github.com/astral-sh/ruff) for linting and formatting:

```bash
make lint    # check
make format  # auto-fix
```

## Adding a New Agent Adapter

1. Create `src/open_researcher/agents/your_agent.py`
2. Implement the `AgentAdapter` interface (see `base.py`)
3. Add the `@register` decorator
4. Add tests in `tests/test_agents.py`
5. Update the agent table in `README.md`

## Pull Requests

- One feature per PR
- Include tests
- Run `make ci` before submitting
