# PyRepair Benchmark Results

Raw results: `benchmarks/results/20260826T133842Z-deepseek-v4-flash.jsonl`

## Model coverage

| Model | Status |
| --- | --- |
| deepseek-v4-flash | Evaluated |
| deepseek-v4-pro | Not evaluated |

## Summary

| Metric | Value |
| --- | ---: |
| Cases | 15 |
| Success rate | 100.0% |
| First-attempt success rate | 100.0% |
| Average attempts | 1.00 |
| Average duration (seconds) | 16.39 |
| Prompt tokens | 151227 |
| Completion tokens | 15947 |
| Regressions | 0 |
| Policy rejections | 0 |

## Cases

| Case | Category | Status | Attempts | Seconds | Failure reason |
| --- | --- | --- | ---: | ---: | --- |
| case_01 | condition | success | 1 | 14.06 | - |
| case_02 | condition | success | 1 | 17.67 | - |
| case_03 | condition | success | 1 | 17.74 | - |
| case_04 | boundary | success | 1 | 15.65 | - |
| case_05 | boundary | success | 1 | 14.52 | - |
| case_06 | boundary | success | 1 | 13.98 | - |
| case_07 | exception | success | 1 | 14.50 | - |
| case_08 | exception | success | 1 | 15.62 | - |
| case_09 | exception | success | 1 | 21.17 | - |
| case_10 | state | success | 1 | 13.81 | - |
| case_11 | state | success | 1 | 11.97 | - |
| case_12 | state | success | 1 | 14.72 | - |
| case_13 | conversion | success | 1 | 15.42 | - |
| case_14 | conversion | success | 1 | 23.35 | - |
| case_15 | conversion | success | 1 | 21.60 | - |

## Failed cases

None.
