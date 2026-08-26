# PyRepair Benchmark Results

Raw results: `benchmarks/results/20260826T140319Z-deepseek-v4-flash.jsonl`

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
| Average duration (seconds) | 17.09 |
| Prompt tokens | 158905 |
| Completion tokens | 16639 |
| Regressions | 0 |
| Policy rejections | 0 |

## Cases

| Case | Category | Status | Attempts | Seconds | Failure reason |
| --- | --- | --- | ---: | ---: | --- |
| case_01 | condition | success | 1 | 13.90 | - |
| case_02 | condition | success | 1 | 13.70 | - |
| case_03 | condition | success | 1 | 19.86 | - |
| case_04 | boundary | success | 1 | 14.15 | - |
| case_05 | boundary | success | 1 | 15.10 | - |
| case_06 | boundary | success | 1 | 12.52 | - |
| case_07 | exception | success | 1 | 22.44 | - |
| case_08 | exception | success | 1 | 13.24 | - |
| case_09 | exception | success | 1 | 22.84 | - |
| case_10 | state | success | 1 | 16.64 | - |
| case_11 | state | success | 1 | 14.36 | - |
| case_12 | state | success | 1 | 13.39 | - |
| case_13 | conversion | success | 1 | 17.97 | - |
| case_14 | conversion | success | 1 | 17.62 | - |
| case_15 | conversion | success | 1 | 28.66 | - |

## Failed cases

None.
