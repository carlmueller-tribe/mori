# Mori (森)

The cognitive environment for LLM agents.

Mori is a Python library for building governed LLM agent systems. It provides a lightweight native runtime, layered memory, reusable skill artifacts, a managed protocol registry, declarative permissions, context budget management, and vendor-neutral observability.

## Install

Clone the repo and install in editable mode:

```bash
git clone https://github.com/carlmueller-tribe/mori.git
cd mori
pip install -e .
```

With Anthropic support:

```bash
pip install -e ".[anthropic]"
```

## Quick Start

```python
from mori import Mori

agent = (
    Mori.builder()
    .model("anthropic", model="claude-sonnet-4-20250514")
    .tool(add, description="Add two numbers")
    .build()
)
result = await agent.run("What is 3 + 5?")
```
