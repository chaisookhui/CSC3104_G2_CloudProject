<!-- pagebreak -->
## Appendix A. Latest Follow-up Results - 19 November 2026

This supplement extends the original November 14, 25-case baseline. The earlier PASS matrix is retained within its recorded scope; it does not mean every higher-rate follow-up met its SLO. All 64 planned follow-up units are COMPLETE, with no measurement pending. No application tests were rerun for this documentation update.

| Study | Completed evidence | Observed result |
|---|---|---|
| TC-18 F2/F3/F6 | 30 matched seed pairs; 60 policy replays | All correctness checks passed. Mean DC-FCFS party/Jain deltas: F2 -0.1/+0.009405; F3 +0.5/+0.028361; F6 0/0. |
| TC-24 CPU HPA | Two full cycles per target | All four passed scale-out, original 600s recovery and repeated scale-out. API held at four Ready replicas in worker-only tests. |
| TC-19 bursts | Three trials per peak 100/150/200 per second | All nine passed; all 27,900 offers accepted. Maximum admission 178.1/269.7/352.0s, within 600s. |
| TC-23 capacity | 21 trials; 19 valid delivery, two invalid delivery | Eight met the composite SLO. Fourteen workload PASS and seven INCONCLUSIVE outcomes remain separate from SLO status. |

### Observed API capacity - unchanged composite SLO
| API replicas | Highest observed pass | Passing / valid trials at that rate | First observed valid-delivery miss |
|---|---|---|---|
| 1 | 200/s | 3/3 | 250/s: two valid misses; one other attempt had invalid delivery |
| 2 | 250/s | 1/3 | 200/s: one miss among three valid trials |
| 4 | 250/s | 1/3 | 250/s: two misses among three valid trials |

These maxima describe observed trials, not stable or production capacity. All five completed 300/s attempts remain INCONCLUSIVE with unavailable accepted-ID reconciliation; acknowledgements are lower bounds. A P95 of 536ms at 250/s with four replicas still missed because 158 HTTP requests timed out. All unchanged SLO conditions must pass, not P95 alone.

Two invalid-delivery attempts are excluded from capacity inference: 374 pool drops at 300/s with one replica, and 4.08s launch lag in an extra 250/s one-replica trial. The original F1 parties-versus-Jain trade-off did not recur on mean paired effects. F3 nevertheless had a worse rate gap despite higher Jain. Missing sizes remain missing; Jain requires all four sizes, known outcomes and positive service. F6 fixture bookings are excluded. Burst success means terminal processing, including unavailable/expired parties, not thousands of booked seats.

The saved-data audit passed 1,046 checks with zero failures. Three historical interrupted attempts remain preserved and are not extra matched samples. Full analysis, counts, waits, denominators and raw paths: docs/FOLLOWUP_EVALUATION_RESULTS.md and output/validation/followup-20261119/report/RESULTS.md. Article table/paragraph and PNG/SVG figures are in that report folder.
