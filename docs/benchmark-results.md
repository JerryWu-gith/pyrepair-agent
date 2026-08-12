# PyRepair Benchmark Results

Raw results: `benchmarks/results/20260812T074237Z-deepseek-v4-flash.jsonl`

## Model coverage

| Model | Status |
| --- | --- |
| deepseek-v4-flash | Evaluated |
| deepseek-v4-pro | Not evaluated |

## Summary

| Metric | Value |
| --- | ---: |
| Cases | 15 |
| Success rate | 86.7% |
| First-attempt success rate | 80.0% |
| Average attempts | 0.93 |
| Average duration (seconds) | 17.50 |
| Prompt tokens | 109134 |
| Completion tokens | 16741 |
| Regressions | 0 |
| Policy rejections | 0 |

## Interpretation

This is the end-to-end PyRepair success rate, not a standalone model-accuracy score. A case counts as successful only when failure parsing, repair generation, patch policy, independent review, target verification, and full-suite regression verification all complete successfully.

`case_05` and `case_08` stopped before any LLM call because pytest 9 emitted a summary line without the older ` - ExceptionType: detail` suffix expected by the current parser. Both failures remain in the raw data and metrics. DeepSeek V4 Pro was not evaluated.

## Cases

| Case | Category | Status | Attempts | Seconds | Failure reason |
| --- | --- | --- | ---: | ---: | --- |
| case_01 | condition | success | 1 | 16.00 | - |
| case_02 | condition | success | 1 | 17.93 | - |
| case_03 | condition | success | 1 | 25.33 | - |
| case_04 | boundary | success | 1 | 13.88 | - |
| case_05 | boundary | failed | 0 | 2.84 | unparseable_pytest_output |
| case_06 | boundary | success | 1 | 16.26 | - |
| case_07 | exception | success | 1 | 21.52 | - |
| case_08 | exception | failed | 0 | 2.86 | unparseable_pytest_output |
| case_09 | exception | success | 1 | 15.65 | - |
| case_10 | state | success | 2 | 20.58 | - |
| case_11 | state | success | 1 | 13.53 | - |
| case_12 | state | success | 1 | 18.74 | - |
| case_13 | conversion | success | 1 | 25.86 | - |
| case_14 | conversion | success | 1 | 20.77 | - |
| case_15 | conversion | success | 1 | 30.78 | - |

## Failed cases

- `case_05`: `unparseable_pytest_output`
- `case_08`: `unparseable_pytest_output`
