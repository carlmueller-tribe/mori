# Code Review Procedure

## Goal
Review one or more source files for correctness, style, and test coverage.
Summarise findings with severity labels so the author knows what to fix first.

## Steps

### 1. Read
Read each file requested. Note the language, framework, and apparent intent.

### 2. Check Style
Look for naming inconsistencies, overly long functions, dead code, and unclear
variable names. Flag each with severity LOW.

### 3. Check Logic
Look for off-by-one errors, missing null checks, unhandled error paths, and incorrect
assumptions. Flag each with severity MEDIUM or HIGH.

### 4. Check Test Coverage
Identify public functions or branches with no corresponding test.
Flag missing tests as severity MEDIUM.

### 5. Summarise
Produce a bulleted list of findings sorted HIGH → MEDIUM → LOW.
For each finding, state: file + line reference, severity, description,
and a one-sentence suggested fix.

## Constraints
- Do not rewrite the code — only comment on it.
- If the review covers more than 5 files, limit each file to at most 3 findings.
