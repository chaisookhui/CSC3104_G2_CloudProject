# Recorded policy comparison

Objective: equal opportunity to reserve a complete party across sizes 1-4 within each section.
Read rate equality alongside waits, overtakes and utilization. No policy is assumed superior.

| Seed / repeat | Policy | Status | Confirmations | Overtakes | Incremental venue utilization |
|---|---|---|---|---|---|
| 42 / 1 | demand-cycle | PASS | 26 | 16 | 0.857 |
| 42 / 1 | fcfs | PASS | 24 | 0 | 0.857 |
| 43 / 1 | demand-cycle | PASS | 28 | 15 | 0.929 |
| 43 / 1 | fcfs | PASS | 26 | 0 | 0.929 |

| Seed / repeat | Policy | Section | Rate gap | Jain index | Interpretable |
|---|---|---|---|---|---|
| 42 / 1 | demand-cycle | A | 0.000 | 1.000 | True |
| 42 / 1 | demand-cycle | B | 0.333 | 0.964 | True |
| 42 / 1 | demand-cycle | C | 1.000 | 0.643 | True |
| 42 / 1 | demand-cycle | D | 0.167 | 0.962 | True |
| 42 / 1 | fcfs | A | 0.000 | 1.000 | True |
| 42 / 1 | fcfs | B | 0.333 | 0.964 | True |
| 42 / 1 | fcfs | C | 0.167 | 0.964 | True |
| 42 / 1 | fcfs | D | 0.167 | 0.962 | True |
| 43 / 1 | demand-cycle | A | 0.000 | 1.000 | True |
| 43 / 1 | demand-cycle | B | 0.333 | 0.976 | True |
| 43 / 1 | demand-cycle | C | 1.000 | 0.643 | True |
| 43 / 1 | demand-cycle | D | 0.167 | 0.962 | True |
| 43 / 1 | fcfs | A | 0.000 | 1.000 | True |
| 43 / 1 | fcfs | B | 0.333 | 0.976 | True |
| 43 / 1 | fcfs | C | 0.167 | 0.964 | True |
| 43 / 1 | fcfs | D | 0.167 | 0.962 | True |

Independent seeds with interpretable paired sections: 2.
Mean paired reservation-gap difference (Demand-Cycle minus FCFS): 0.208.
Negative gap delta favours Demand-Cycle on rate equality. Positive Jain delta favours it. These are descriptive paired effects, not statistical significance; repeated seeds are not independent samples.

Inspect per-policy customers.csv and summary.json for group sample sizes, reservation/confirmation rates, median/P95 waits, unknown outcomes and physical inventory. A small gap can coexist with low service; zero-service groups receive no Jain score. This report provides descriptive evidence and does not establish statistical significance.
