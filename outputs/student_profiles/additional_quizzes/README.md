# Additional student quizzes

This is an append-only fictional population exercise. Existing students, answers, sessions, pending grades and reviews are preserved. Liam Morgan was added as a concept specialist in microglia, within Elena Morales's neurons-and-glia topic. Names in the normal interface have no profile or simulation labels; the fictional origin is documented here and in metadata.

The plan is six new normal quizzes per student, two per topic, with three questions per quiz. The production default and selection/grading rules are unchanged. Eligibility exhaustion and unresolved technical failures can shorten the plan.

| Student | New quizzes created | New graded answers | Record |
|---|---:|---:|---|
| Maya Chen | 5 / 6 | 13 | [Questions, answers, outcomes and metrics](Maya_Chen.md) |
| Noah Patel | 6 / 6 | 18 | [Questions, answers, outcomes and metrics](Noah_Patel.md) |
| Elena Morales | 6 / 6 | 18 | [Questions, answers, outcomes and metrics](Elena_Morales.md) |
| Liam Morgan | 6 / 6 | 18 | [Questions, answers, outcomes and metrics](Liam_Morgan.md) |

Maya had already mastered four of the five quiz-eligible AI Test facts. Her first new AI quiz assessed the remaining fact and ended; her second AI start reported that no eligible unmastered facts remained. Review mode was not enabled to fill the quota.

All 67 new submissions have grades; the three original pending grades remain unchanged. Contribution checks: 59 completed and 8 require technical review. Their errors and actual candidate decisions are retained in the student reports and audit ledger.

## Final All Topics metrics

| Student | Independent relationship coverage | Knowledge concentration (HHI) |
|---|---:|---:|
| Maya Chen | 13.9% | 0.136 |
| Noah Patel | 0.0% | Unavailable |
| Elena Morales | 4.4% | 0.388 |
| Liam Morgan | 1.3% | 0.5 |

Higher HHI indicates greater concentration in the existing reference-community calculation. It is not an overall ability score. Noah has no independent mastery, so HHI is unavailable. Liam's microglia facts form one connected mastered component, but cross a reference-community boundary; a connected specialty need not yield HHI = 1.


## Current independent relationship coverage

| Student | AI Test | LLM tuning | Neurons and glia |
|---|---:|---:|---:|
| Maya Chen | 41.7% (5 relationships) | 10.2% (9 relationships) | 13.8% (8 relationships) |
| Noah Patel | 0.0% (0 relationships) | 0.0% (0 relationships) | 0.0% (0 relationships) |
| Elena Morales | 0.0% (0 relationships) | 0.0% (0 relationships) | 12.1% (7 relationships) |
| Liam Morgan | 0.0% (0 relationships) | 0.0% (0 relationships) | 3.4% (2 relationships) |

Graph coverage includes relationships that are not yet quiz-approved. Therefore mastering every currently eligible document relationship does not necessarily produce 100% graph coverage. Detailed degree, connectivity and concentration metrics are the existing application values, recorded before and after each round in each student document. No values were inserted or tuned.

## Procedure and limitations

- Questions were generated and answers submitted through the actual local-model quiz API. Authored answer files were fixed before submission.
- Answers used the targeted relationship, its direction, conditions and qualifiers, together with the fictional profile. No internet research or hidden expected answers/criteria were used.
- Concept focus choices were planned before results; adaptive selection and green-fact exclusion remained in control.
- Repeated questions across sessions can arise from normal progress selection. No completed answer was resubmitted to obtain a different outcome.
- Technical grading failures permit at most two HTTP attempts with the same request ID and unchanged answer. Contribution validation failures and review decisions are preserved.
- Normal contribution checks were requested separately from grading. No professor approvals, corrections or grade overrides were added.
- These short, deliberately focused samples illustrate measured coverage; they do not prove complete topic knowledge.

Backup: `archive\databases\additional_student_quizzes_2026-11-26T095621904390+0000`. Verification: [verification.json](verification.json). Full request/response audit and metric snapshots: [metadata.json](metadata.json). Earlier exercise: [original reports](../README.md).
