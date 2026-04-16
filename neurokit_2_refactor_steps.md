---
alwaysApply: false
---

# NeuroKit2 Refactor Steps

## Relevant Files:

- src/mooi_toolbox/processing/check_plux_data.py
- src/mooi_toolbox/processing/vr_intervals.py
- scripts/loop_check_plux_data.py

## Brief problem statement
The current code works and already captures the scientific logic, but too many responsibilities are still mixed together: loading, validation, analysis, plotting, debug printing, and result assembly. That makes the pipeline harder to maintain, harder to extend, and less graceful when something is missing. The goal is not a rewrite, but a controlled refactor that keeps the science intact while making the code simpler, more modular, and more robust.

## Prioritized change list

### 1. Stabilize VR interval extraction
Start with `src/mooi_toolbox/processing/vr_intervals.py`, because interval errors currently affect downstream EDA, ECG, and target processing.
Make missing configured streams, columns, or events fail with clear built-in exceptions instead of implicit `KeyError` / `IndexError` tracebacks.
Add an explicit baseline fallback for cases where marker event `10` is missing: use `RaiseSafetyPlatform` minus 300 seconds as the baseline start, preferably configured in `pyproject.toml` rather than hard-coded in the processing function.

### 2. Thin out `main()`
Make `main()` coordinate the pipeline only, not contain detailed logic.

### 3. Standardize return structures
EDA, ECG, target, and loading steps should return consistent successful result structures.
Do not create a custom "error result" class by default; failures should be raised as exceptions and handled by the CLI layer.

### 4. Keep only minimal required checks
Only check what prevents crashes or invalid interpretation.

### 5. Make graceful failure explicit
A missing stream or failed modality should raise a clear, narrow built-in exception where it occurs.
CLI scripts should catch only the exceptions they can handle and decide whether to skip a modality, skip a participant, stop the batch, or report a warning.
Lower-level processing functions should not silently swallow failures or return placeholder error values.

### 6. Separate plotting from processing
Processing should compute results. Plotting should be optional and separate.

### 7. Make ECG a first-class output
ECG should return structured participant results, not just side calculations.

### 8. Move assumptions into configuration
Centralize stream names, expected channels, interval labels, and output paths.

### 9. Replace debug-heavy printing with controlled logging
After the VR interval error handling is stable, replace debug-heavy `print()` calls with standard-library `logging`.
Keep progress messages, warnings, and missing-data summaries distinct.

### 10. Tighten function boundaries
EDA functions should only do EDA, ECG only ECG, target only target parsing/summarization.

### 11. Add a final batch summary
Report what was processed, skipped, missing, or only partially successful.

## Suggested order
1. Add focused error checks in `vr_intervals.py`
2. Add the missing marker `10` fallback using `RaiseSafetyPlatform - 300 seconds`
3. Introduce logging best practices after the error-handling path is clear
4. Thin out `main()` by delegating interval creation and stream loading
5. Standardize returns
6. Minimize checks
7. Improve graceful failure at CLI / batch boundaries
8. Split plotting
9. Finish ECG output
10. Centralize config
11. Improve reporting

## Exception-handling rule
Follow the "raise low, catch high" pattern:

- Processing, loading, interval, and parsing functions should fail fast with clear messages.
- Prefer built-in exceptions such as `FileNotFoundError`, `KeyError`, `ValueError`, or `TypeError` before adding project-specific exception classes.
- Catch exceptions in CLI scripts or other application-boundary code, where the caller can decide whether to warn, skip, continue, or exit.
- Catch the narrowest exception that the CLI can genuinely handle; avoid bare `except:` and avoid broad `except Exception` unless it is at a batch boundary with useful reporting.
- Do not use exceptions for routine branching where a normal `if` check is clearer.
- Preserve the original error context when converting an exception with `raise ... from error`.

For `vr_intervals.py`, apply this rule first:

- `get_event_time()` should raise a clear `KeyError` when the requested column is missing.
- `get_event_time()` should raise a clear `ValueError` when the requested event is absent or appears in an unusable way.
- `create_intervals()` should raise a clear `KeyError` when the interval configuration names an unknown stream or malformed interval definition.
- `slice_data_frame()` should validate only what prevents slicing from making sense, such as malformed `(start, end)` interval values.
- Do not catch these inside `vr_intervals.py`; let `check_plux_data.py` or `scripts/loop_check_plux_data.py` decide whether to skip, warn, or stop.

## VR interval fallback TODO
Implement this after the initial `vr_intervals.py` error checks:

- Extend the baseline interval config in `pyproject.toml` with a `start_fallback` rule.
- Use the normal configured start event first: `VR_markers.Markers == 10`.
- If that event is absent and a fallback is configured, resolve `VR_trial_events.VR_trial == "RaiseSafetyPlatform"` and apply `offset_seconds = -300`.
- Log that the fallback was used once logging is in place, because it changes interval interpretation but is still an expected recovery path.
- If both the primary event and fallback event are missing, raise a clear `ValueError`.

Suggested config shape:

```toml
[tool.mooi_toolbox.vr_intervals.baseline]
start = { stream = "VR_markers", column = "Markers", event = 10 }
start_fallback = { stream = "VR_trial_events", column = "VR_trial", event = "RaiseSafetyPlatform", offset_seconds = -300 }
end = { stream = "VR_trial_events", column = "VR_trial", event = "RaiseSafetyPlatform" }
```

## Logging rule
Apply this after the interval error-handling work:

- Use the standard-library `logging` package instead of production `print()` calls.
- Create a module-level logger in processing modules with `logger = logging.getLogger(__name__)`.
- Configure logging once at the application boundary, such as a CLI entry point or `if __name__ == "__main__":` block.
- Do not call `logging.basicConfig()` or add handlers at import time inside reusable processing modules.
- Use levels consistently: `debug` for noisy diagnostics, `info` for normal progress, `warning` for expected but recovered issues, `error` for failures, and `critical` for unrecoverable failures.
- Use `logger.exception()` only inside `except` blocks where the traceback is useful.

Reference: Real Python, "exception handling | Python Best Practices" (accessed 2026-04-14): https://realpython.com/ref/best-practices/exception-handling/
Reference: Real Python, "Python's raise: Effectively Raising Exceptions in Your Code" (accessed 2026-04-14): https://realpython.com/python-raise-exception/
Reference: Real Python, "logging | Python Best Practices" (accessed 2026-04-14): https://realpython.com/ref/best-practices/logging/

## Refactor rule
Do not rewrite everything at once. Preserve working behaviour and improve one structural issue at a time.
