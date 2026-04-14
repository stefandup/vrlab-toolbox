---
alwaysApply: false
---

# NeuroKit2 Refactor Steps

## Relevant Files:

- src/mooi_toolbox/processing/check_plux_data.py
- scripts/loop_check_plux_data.py

## Brief problem statement
The current code works and already captures the scientific logic, but too many responsibilities are still mixed together: loading, validation, analysis, plotting, debug printing, and result assembly. That makes the pipeline harder to maintain, harder to extend, and less graceful when something is missing. The goal is not a rewrite, but a controlled refactor that keeps the science intact while making the code simpler, more modular, and more robust.

## Prioritized change list

### 1. Thin out `main()`
Make `main()` coordinate the pipeline only, not contain detailed logic.

### 2. Standardize return structures
EDA, ECG, target, and loading steps should return consistent successful result structures.
Do not create a custom "error result" class by default; failures should be raised as exceptions and handled by the CLI layer.

### 3. Keep only minimal required checks
Only check what prevents crashes or invalid interpretation.

### 4. Make graceful failure explicit
A missing stream or failed modality should raise a clear, narrow built-in exception where it occurs.
CLI scripts should catch only the exceptions they can handle and decide whether to skip a modality, skip a participant, stop the batch, or report a warning.
Lower-level processing functions should not silently swallow failures or return placeholder error values.

### 5. Separate plotting from processing
Processing should compute results. Plotting should be optional and separate.

### 6. Make ECG a first-class output
ECG should return structured participant results, not just side calculations.

### 7. Move assumptions into configuration
Centralize stream names, expected channels, interval labels, and output paths.

### 8. Replace debug-heavy printing with controlled reporting
Keep progress messages, warnings, and missing-data summaries distinct.

### 9. Tighten function boundaries
EDA functions should only do EDA, ECG only ECG, target only target parsing/summarization.

### 10. Add a final batch summary
Report what was processed, skipped, missing, or only partially successful.

## Suggested order
1. Thin out `main()`
2. Standardize returns
3. Minimize checks
4. Improve graceful failure
5. Split plotting
6. Finish ECG output
7. Centralize config
8. Improve reporting

## Exception-handling rule
Follow the "raise low, catch high" pattern:

- Processing, loading, interval, and parsing functions should fail fast with clear messages.
- Prefer built-in exceptions such as `FileNotFoundError`, `KeyError`, `ValueError`, or `TypeError` before adding project-specific exception classes.
- Catch exceptions in CLI scripts or other application-boundary code, where the caller can decide whether to warn, skip, continue, or exit.
- Catch the narrowest exception that the CLI can genuinely handle; avoid bare `except:` and avoid broad `except Exception` unless it is at a batch boundary with useful reporting.
- Do not use exceptions for routine branching where a normal `if` check is clearer.
- Preserve the original error context when converting an exception with `raise ... from error`.

Reference: Real Python, "exception handling | Python Best Practices" (accessed 2026-04-14): https://realpython.com/ref/best-practices/exception-handling/

## Refactor rule
Do not rewrite everything at once. Preserve working behaviour and improve one structural issue at a time.
