# Bug Fix Procedure

## Goal
Fix a failing test or broken code by reproducing the failure, isolating the root cause,
and applying the minimal change that makes the test pass.

## Steps

### 1. Reproduce
Read the failing test file to understand what is expected.
Run the test to confirm it fails and capture the exact error message.

### 2. Isolate Root Cause
Read the source file under test.
Trace the execution path that triggers the failure.
Identify the exact line or condition causing the error.

### 3. Apply Minimal Fix
Make the smallest possible change to fix the root cause.
Do not refactor unrelated code. Do not add features.
Change only what is necessary.

### 4. Verify
Run the failing test again — confirm it passes.
Run the full test suite — confirm no regressions were introduced.

## Constraints
- Never skip or comment out failing assertions.
- Never change the test to match broken behaviour.
- If the fix requires touching more than 3 files, stop and explain why before proceeding.
