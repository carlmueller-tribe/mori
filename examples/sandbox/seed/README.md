# Sandbox seed project

A tiny project with a deliberate bug, used as the workload for the Mori coding
agent experiment.

- `fizzbuzz.py` — FizzBuzz implementation with a bug on multiples of 3
- `test_fizzbuzz.py` — pytest suite that fails until the bug is fixed

The container's entrypoint copies this directory to `/sandbox/project/` at the
start of every run so each experiment starts from the same state.
