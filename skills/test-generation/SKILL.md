# Test Generation Procedure

## Goal
Write tests for untested code so that the test suite gains meaningful coverage.

## Steps

### 1. Identify Untested Cases
Read the source file.
List: public functions with no tests, branches not covered by existing tests,
and error paths not exercised.

### 2. Write Tests
For each identified case, write one or more test functions using pytest.
Each test must:
- Have a descriptive name: `test_<function>_<scenario>`
- Set up minimal inputs
- Assert a specific, observable output or side-effect

### 3. Verify
Run the new tests. Confirm they pass.
If a test fails, fix the source code or the test — never loosen the assertion.

## Constraints
- Do not modify the source file unless a genuine bug is found.
- Each test function must test exactly one behaviour.
- Use `pytest.mark.parametrize` where the same logic applies to multiple inputs.
