# Maya Chen: additional quizzes

**Origin:** fictional learner with authored simulated responses, not a real student.

**Profile:** Strong generalist. All three topics; accurate natural explanations with occasional omissions.

Student ID: `32c46000-5115-449c-9698-42be061f1f6d`.

This append-only exercise plans two additional normal quizzes per topic, three questions per quiz. The limit applies only to the exercise process. Production interface, metrics, selection and grading remain unchanged. Answers were authored from the displayed question and targeted graph relationship, including its direction and conditions; no internet or hidden expected answers/criteria were used. Grades were not inserted, changed or pursued through revised submissions. The same request ID and text permit at most two attempts for technical failures.

Focus choices were planned before grading to sample different concepts through the existing focus control. Green relationships remain excluded, and normal adaptive selection can move beyond the requested focus. The intended profile is not a promised metric outcome.

[Earlier profile and preserved records](../Maya_Chen.md).

## Final All Topics view

Independent relationship coverage: **13.9%**. Assessed coverage: **14.6%**. Knowledge concentration (HHI): **0.136**. These are the existing application metrics at 2026-11-26T10:49:34.628337+00:00; no values were inserted. Unavailable concentration means there is no independently mastered subgraph to measure.

## Additional round 1

| Topic | Independent coverage before → after | Assessed coverage before → after | Average answer score before → after |
|---|---:|---:|---:|
| Ai Test | 33.3 → 41.7 | 33.3 → 41.7 | 100.0 → 100.0 |
| Llm Tuning | 3.4 → 6.8 | 4.5 → 8.0 | 75.0 → 85.7 |
| Neurons And Glia | 3.5 → 8.6 | 3.5 → 8.6 | 100.0 → 100.0 |

Coverage percentages count graph relationships; answer averages also include previous sessions. Incorrect, partial, assisted and pending responses do not establish independent mastery. Revisiting an assessed fact can leave assessment coverage unchanged. Accepted additions can enlarge the denominator without changing earlier mastery.

### Ai Test

Session: `3f469093-cc63-4950-ba0e-11feeeca7ddf`. Planned focus sequence: regularization, regularization, quantization.

Independent relationships: 4 → 5; assessed: 4 → 5. Reference relationships: 12 → 12.

| Existing graph metric | Before | After |
|---|---:|---:|
| relationship coverage | 33.3 | 41.7 |
| assessment coverage | 33.3 | 41.7 |
| concept reach | 29.4 | 41.2 |
| concept completeness | 22.1 | 36.4 |
| average degree | 1.6 | 1.429 |
| density | 40.0 | 23.81 |
| components | 1 | 2 |
| largest component | 100.0 | 71.4 |
| clustering | 0.0 | 0.0 |
| cross topic coverage | None | None |
| global efficiency | 0.049 | 0.056 |
| modularity | 0.0 | 0.32 |
| concentration | 1.0 | 0.68 |
| connection strength | 0.471 | 0.588 |

Null means unavailable, not a zero grade. Concentration and connectivity describe the measured subgraph, so a few connected correct answers can have high concentration despite low overall coverage.

This round added 1 independently demonstrated relationship(s) and 1 newly assessed relationship(s). The increase comes from the saved independent answer outcomes. Newly assessed does not necessarily mean mastered.

#### Question 1

Explain the relationship between quantization and memory requirements of the small transformer.

**Submitted answer:**

> After training, quantization reduces the memory the small transformer needs.

Assistance: 0 hint(s); reveal: False. Recorded score: 100.0%.

**Recorded feedback:** Relationship progress: 1 supported, 0 related, 0 contradicted. Green: independent understanding. Yellow: partial or assisted. Red: contradicted or not demonstrated.
Complete: The learner correctly identifies that quantization 'reduces' the memory requirements of the small transformer. This matches the fact's relation 'inhibits' (defined as reducing or suppressing). The phrase 'the memory the small transformer needs' is a valid paraphrase for 'memory requirements of the small transformer'. The mention of 'After training' aligns with the context implied by the question about the transformer's state, without inventing new conditions. All criteria for explaining the substantive connection with the correct direction are met.

Targeted graph reference: [{"id": "edge_00005", "subject": "quantization", "relationship": "inhibits", "object": "memory requirements of the small transformer", "definition": "SOURCE reduces or suppresses the occurrence or activity of TARGET.", "conditions": null, "modality": null, "purpose": null, "timing": null, "negated": null, "argument_qualifiers": ["after training"], "participants": []}]

**Contributions and reviews:**

- quantization reduces the memory the small transformer needs — **needs_review**.
  The student claim states quantization reduces memory after training, which matches edge_00005 where quantization inhibits memory requirements under the same condition. However, the predicate 'inhibits' in the graph implies suppression or reduction of occurrence/activity, while the student's specific phrasing 'reduces the memory' aligns directly with this meaning; thus, it is not novel but a duplicate fact.
  The student claim is supported by edge_00005 because 'inhibits' semantically covers the reduction of memory requirements described in the quote. However, the first review incorrectly labels this as a duplicate without noting that the graph fact uses a broader term ('inhibits') while the student provides a specific mechanism detail ('reduces'), which technically makes the student's contribution novel under the provided guidelines.

Answer ID: `d89fa88d-f91c-47a4-b136-dd67252e95c6`. Saved: 2026-11-26T09:58:50.949247+00:00.

### Llm Tuning

Session: `b40ef885-13a6-473d-921c-9c9e2a2b24c3`. Planned focus sequence: standard fine tuning, fine tuning, parameter efficient tuning.

Independent relationships: 3 → 6; assessed: 4 → 7. Reference relationships: 88 → 88.

| Existing graph metric | Before | After |
|---|---:|---:|
| relationship coverage | 3.4 | 6.8 |
| assessment coverage | 4.5 | 8.0 |
| concept reach | 3.0 | 6.0 |
| concept completeness | 3.4 | 6.1 |
| average degree | 1.5 | 1.5 |
| density | 50.0 | 21.43 |
| components | 1 | 2 |
| largest component | 100.0 | 62.5 |
| clustering | 0.0 | 0.0 |
| cross topic coverage | 0.0 | 0.0 |
| global efficiency | 0.001 | 0.001 |
| modularity | 0.0 | 0.444 |
| concentration | 1.0 | 0.556 |
| connection strength | 0.045 | 0.09 |

Null means unavailable, not a zero grade. Concentration and connectivity describe the measured subgraph, so a few connected correct answers can have high concentration despite low overall coverage.

This round added 3 independently demonstrated relationship(s) and 3 newly assessed relationship(s). The increase comes from the saved independent answer outcomes. Newly assessed does not necessarily mean mastered.

#### Question 1

Explain the relationship between standard fine tuning and computationally expensive.

**Submitted answer:**

> Standard fine-tuning is computationally expensive because every backpropagation iteration updates the weights and biases across all the parameters.

Assistance: 0 hint(s); reveal: False. Recorded score: 100.0%.

**Recorded feedback:** Relationship progress: 1 supported, 0 related, 0 contradicted. Green: independent understanding. Yellow: partial or assisted. Red: contradicted or not demonstrated.
Complete: The learner correctly identifies that standard fine-tuning possesses the property of being computationally expensive. The explanation provided ('because every backpropagation iteration...') substantiates this connection without inventing mechanisms or adding unsupported conditions.

Targeted graph reference: [{"id": "edge_00019", "subject": "standard fine tuning", "relationship": "is", "object": "computationally expensive", "definition": "Indicates that the source possesses the property described by the target.", "conditions": null, "modality": null, "purpose": null, "timing": null, "negated": null, "argument_qualifiers": ["because standard fine-tuning updates the weights and biases of every parameter on each backpropagation iteration"], "participants": []}]

**Contributions and reviews:**

- every backpropagation iteration updates the weights and biases across all the parameters — **duplicate**.
  The student claim is a direct paraphrase of edge_00020, which explicitly states that standard fine-tuning updates weights and biases on each backpropagation iteration. The student's statement adds the qualifier 'across all the parameters,' which is substantiated by edge_00019 (citing the same mechanism) and edge_00021 (contrasting with parameter-efficient tuning that updates only a subset). Since the core fact exists in the graph, this is not novel.
  The student claim is a direct paraphrase of edge_00020, which explicitly states that standard fine-tuning updates weights and biases on each backpropagation iteration. The student's statement adds the qualifier 'across all the parameters,' which is substantiated by edge_00019 (citing the same mechanism) and edge_00021 (contrasting with parameter-efficient tuning that updates only a subset). Since the core fact exists in the graph, this is not novel.
- standard fine tuning is computationally expensive — **duplicate**.
  The student claim exactly matches the text of edge_00019, which explicitly states that standard fine tuning is computationally expensive with a matching definition and qualifier. Therefore, the claim is supported by an existing fact in the graph.
  The student claim is a direct paraphrase of edge_00019, which explicitly states that standard fine tuning is computationally expensive due to updating all parameters. The first review correctly identifies this as supported and non-novel, but fails to challenge the potential overgeneralization regarding 'computationally expensive' without specifying the context of parameter count or comparison to parameter-efficient methods present in other graph edges.

Answer ID: `6e41d408-c8a0-4017-8609-999c5f34df8e`. Saved: 2026-11-26T09:59:06.402229+00:00.

#### Question 2

Explain the relationship between fine tuning and foundation llm.

**Submitted answer:**

> Fine-tuning trains a foundation LLM further, using examples specific to the task the application needs to perform.

Assistance: 0 hint(s); reveal: False. Recorded score: 100.0%.

**Recorded feedback:** Relationship progress: 1 supported, 0 related, 0 contradicted. Green: independent understanding. Yellow: partial or assisted. Red: contradicted or not demonstrated.
Complete: The learner correctly identifies 'fine tuning' as the agent performing the action of training and 'foundation llm' as the object receiving that training. The phrase 'trains a foundation LLM further' accurately reflects the substantive connection defined in the fact (relation: trains) with the correct direction.

Targeted graph reference: [{"id": "edge_00017", "subject": "fine tuning", "relationship": "trains", "object": "foundation llm", "definition": "Subject is the agent performing the action of providing training to the object.", "conditions": null, "modality": null, "purpose": null, "timing": null, "negated": null, "argument_qualifiers": ["on examples that are specific to the task of the application"], "participants": []}]

**Contributions and reviews:**

- fine tuning uses examples specific to the task the application needs to perform — **duplicate**.
  The student claim describes a specific mechanism (using task-specific examples) for fine-tuning, which is explicitly defined in edge_00017 as 'on examples that are specific to the task of the application'. Since this exact fact exists in the graph, the claim is not novel.
  The student claim is supported by edge_00017, which explicitly states that fine-tuning trains a foundation LLM 'on examples that are specific to the task of the application'. The first review correctly identifies this as non-novel but fails to challenge whether the graph's definition of 'fine tuning' in edge_00017 fully captures the nuance of 'using examples' versus other fine-tuning methods like parameter-efficient tuning mentioned elsewhere.
- fine tuning trains a foundation llm further — **duplicate**.
  The student claim 'fine tuning trains a foundation llm further' is directly supported by edge_00017, which states 'fine tuning trains foundation llm'. The relationship and definitions match exactly, making this non-novel.
  The student claim is directly supported by edge_00017, which explicitly states that 'fine tuning trains foundation llm' with matching definitions. The first review correctly identifies this as non-novel and faithful to the student text.

Answer ID: `bca9184e-1618-4091-906a-3a675cfaa05e`. Saved: 2026-11-26T10:03:35.123159+00:00.

#### Question 3

Explain the relationship between parameter efficient tuning and standard fine tuning.

**Submitted answer:**

> Parameter-efficient tuning costs less than standard fine-tuning because it updates only a subset of the parameters.

Assistance: 0 hint(s); reveal: False. Recorded score: 100.0%.

**Recorded feedback:** Relationship progress: 1 supported, 0 related, 0 contradicted. Green: independent understanding. Yellow: partial or assisted. Red: contradicted or not demonstrated.
Complete: The learner correctly identifies that parameter-efficient tuning has lower cost than standard fine-tuning, satisfying the 'is_a_less_expensive_alternative_to' relation. The additional explanation about updating a subset of parameters is consistent with the fact and does not contradict it.

Targeted graph reference: [{"id": "edge_00021", "subject": "parameter efficient tuning", "relationship": "is_a_less_expensive_alternative_to", "object": "standard fine tuning", "definition": "Identifies one process as having lower cost than another specific process.", "conditions": null, "modality": null, "purpose": null, "timing": null, "negated": null, "argument_qualifiers": ["updates only a subset of the parameters on each backpropagation iteration"], "participants": []}]

**Contributions and reviews:**

- Parameter-efficient tuning updates only a subset of the parameters — **duplicate**.
  The student claim describes a general mechanism ('updates only a subset') which is already covered by edge_00021 and edge_00081 in the graph. Since the student text does not introduce a new specific mechanism or detail absent from these existing facts, it is not novel.
  The student claim is a direct paraphrase of the definition provided in edge_00021 and edge_00081, making it non-novel. The first review incorrectly identifies this as non-novel without acknowledging that the student text faithfully expresses an existing graph fact rather than duplicating it verbatim.
- Parameter-efficient tuning costs less than standard fine-tuning — **duplicate**.
  The student claim exactly matches edge_00021, which states parameter-efficient tuning is a less expensive alternative to standard fine-tuning due to updating only a subset of parameters.
  The student claim is supported by edge_00021, which explicitly defines parameter-efficient tuning as a less expensive alternative to standard fine-tuning. The first review correctly identifies this match but fails to challenge the potential overgeneralization regarding 'cost' without specifying conditions like computational resources or environmental impact.

Answer ID: `379da027-d233-4ca4-bef2-8796ca83f7a4`. Saved: 2026-11-26T10:07:27.752020+00:00.

### Neurons And Glia

Session: `d9c821c8-6a77-4c0f-8f6b-b74607ee1564`. Planned focus sequence: brain astrocyte networks, brain astrocyte networks, brain astrocyte networks.

Independent relationships: 2 → 5; assessed: 2 → 5. Reference relationships: 57 → 58.

| Existing graph metric | Before | After |
|---|---:|---:|
| relationship coverage | 3.5 | 8.6 |
| assessment coverage | 3.5 | 8.6 |
| concept reach | 4.2 | 9.7 |
| concept completeness | 2.7 | 6.9 |
| average degree | 1.333 | 1.429 |
| density | 66.67 | 23.81 |
| components | 1 | 2 |
| largest component | 100.0 | 57.1 |
| clustering | 0.0 | 0.0 |
| cross topic coverage | None | 0.0 |
| global efficiency | 0.001 | 0.003 |
| modularity | 0.0 | 0.48 |
| concentration | 1.0 | 0.52 |
| connection strength | 0.056 | 0.139 |

Null means unavailable, not a zero grade. Concentration and connectivity describe the measured subgraph, so a few connected correct answers can have high concentration despite low overall coverage.

This round added 3 independently demonstrated relationship(s) and 3 newly assessed relationship(s). The increase comes from the saved independent answer outcomes. Newly assessed does not necessarily mean mastered.

#### Question 1

Explain the relationship between brain astrocyte networks and ion concentrations around neurons.

**Submitted answer:**

> Astrocyte networks in the brain regulate the concentrations of ions around neurons, helping keep those concentrations controlled.

Assistance: 0 hint(s); reveal: False. Recorded score: 100.0%.

**Recorded feedback:** Relationship progress: 1 supported, 0 related, 0 contradicted. Green: independent understanding. Yellow: partial or assisted. Red: contradicted or not demonstrated.
Complete: The learner correctly identifies the source (astrocyte networks) and target (ion concentrations), explicitly stating the regulatory relationship ('regulate') and the effect ('helping keep... controlled'). This satisfies the requirement to explain the substantive connection with the correct direction.

Targeted graph reference: [{"id": "edge_00022", "subject": "brain astrocyte networks", "relationship": "regulates", "object": "ion concentrations around neurons", "definition": "The source maintains or controls the state of the target.", "conditions": null, "modality": null, "purpose": null, "timing": null, "negated": null, "argument_qualifiers": [], "participants": []}]

**Contributions and reviews:**

- Astrocyte networks in the brain regulate the concentrations of ions around neurons. — **duplicate**.
  The student claim exactly matches edge_00022, which states that brain astrocyte networks regulate ion concentrations around neurons. Since this specific fact already exists in the graph, the relationship is not novel.
  The student claim is a direct paraphrase of edge_00022, making it non-novel; however, the first review incorrectly asserts that the graph lacks connectivity because both endpoints are marked false in endpoint_connections, ignoring that the graph facts themselves define the valid relationships.
- Astrocyte networks in the brain help keep ion concentrations around neurons controlled. — **duplicate**.
  The student claim describes a specific regulatory function (ion concentration control) by astrocyte networks, which is explicitly supported by edge_00022 in the graph facts.
  The student claim is supported by edge_00022, which explicitly states that brain astrocyte networks regulate ion concentrations around neurons. However, the first review incorrectly marks the claim as non-novel (duplicate) because it fails to recognize that while the core fact exists, the student's specific phrasing and context may constitute a distinct educational instance rather than an exact duplicate of the graph row.

Answer ID: `4db41132-b25d-4f01-874b-09b7c248a147`. Saved: 2026-11-26T09:59:14.545694+00:00.

#### Question 2

Explain the relationship between brain astrocyte networks and nutrients.

**Submitted answer:**

> Brain astrocyte networks supply nutrients; they provide those nutrients as part of their supporting role.

Assistance: 0 hint(s); reveal: False. Recorded score: 100.0%.

**Recorded feedback:** Relationship progress: 1 supported, 0 related, 0 contradicted. Green: independent understanding. Yellow: partial or assisted. Red: contradicted or not demonstrated.
Complete: The learner correctly identifies the source ('brain astrocyte networks') and target ('nutrients') and explicitly states the direction of the relationship ('supply', 'provide'). The phrase 'as part of their supporting role' aligns with the definition that the source provides the target to another entity, satisfying the requirement to explain the substantive connection without inventing mechanisms or adding unsupported conditions.

Targeted graph reference: [{"id": "edge_00023", "subject": "brain astrocyte networks", "relationship": "supplies", "object": "nutrients", "definition": "The source provides the target to another entity (implied recipients).", "conditions": null, "modality": null, "purpose": null, "timing": null, "negated": null, "argument_qualifiers": [], "participants": []}]

**Contributions and reviews:**

- Brain astrocyte networks provide nutrients as part of their supporting role — **duplicate**.
  The student claim is supported by edge_00023, which explicitly states that brain astrocyte networks supply nutrients. The proposed relationship matches this fact without needing a new mechanism.
  The student claim is supported by edge_00023, which explicitly states that brain astrocyte networks supply nutrients. The proposed relationship matches this fact without needing a new mechanism.
- Brain astrocyte networks supply nutrients — **duplicate**.
  The student claim exactly matches edge_00023, which states that brain astrocyte networks supply nutrients. Since this specific fact already exists in the graph with the same subject, predicate, and object, the relationship is not novel.
  The student claim is a direct paraphrase of edge_00023, which explicitly states that brain astrocyte networks supply nutrients. Therefore, the relationship is not novel as it duplicates an existing graph fact.

Answer ID: `9e7276ba-07a5-4fa6-bacc-0a843f5286c1`. Saved: 2026-11-26T10:03:43.915859+00:00.

#### Question 3

Explain the relationship between brain astrocyte networks and new neuronal connections.

**Submitted answer:**

> Astrocyte networks help control new neuronal connections, including helping manage their formation.

Assistance: 0 hint(s); reveal: False. Recorded score: 100.0%.

**Recorded feedback:** Relationship progress: 1 supported, 0 related, 0 contradicted. Green: independent understanding. Yellow: partial or assisted. Red: contradicted or not demonstrated.
Complete: The learner correctly identifies the source (astrocyte networks) and target (new neuronal connections). The phrase 'help control' accurately reflects the 'helps_control' relation defined as assisting in managing or limiting formation/state. The addition of 'including helping manage their formation' provides specific detail consistent with the definition without inventing new mechanisms or contradicting the fact.

Targeted graph reference: [{"id": "edge_00024", "subject": "brain astrocyte networks", "relationship": "helps_control", "object": "new neuronal connections", "definition": "The source assists in managing or limiting the formation/state of the target.", "conditions": null, "modality": null, "purpose": null, "timing": null, "negated": null, "argument_qualifiers": [], "participants": []}]

**Contributions and reviews:**

No candidate rows. Check status: needs_review.

Contribution processing issue retained: student_contribution_extract failed for contributions:89a20faf-afed-4e65-bf83-5617789c759c:0 after 3 attempts: New entity 'formation of new neuronal connections' must be named in the student text; use actual subject/object entities, not input-field names


Answer ID: `89a20faf-afed-4e65-bf83-5617789c759c`. Saved: 2026-11-26T10:07:36.576292+00:00.

## Additional round 2

| Topic | Independent coverage before → after | Assessed coverage before → after | Average answer score before → after |
|---|---:|---:|---:|
| Ai Test | 41.7 → 41.7 | 41.7 → 41.7 | 100.0 → 100.0 |
| Llm Tuning | 6.8 → 10.2 | 8.0 → 11.4 | 85.7 → 90.0 |
| Neurons And Glia | 8.6 → 13.8 | 8.6 → 13.8 | 100.0 → 100.0 |

Coverage percentages count graph relationships; answer averages also include previous sessions. Incorrect, partial, assisted and pending responses do not establish independent mastery. Revisiting an assessed fact can leave assessment coverage unchanged. Accepted additions can enlarge the denominator without changing earlier mastery.

### Ai Test

Session: `not created`. Planned focus sequence: retrieval augmented generation, retrieval augmented generation, self attention.

Independent relationships: 5 → 5; assessed: 5 → 5. Reference relationships: 12 → 12.

| Existing graph metric | Before | After |
|---|---:|---:|
| relationship coverage | 41.7 | 41.7 |
| assessment coverage | 41.7 | 41.7 |
| concept reach | 41.2 | 41.2 |
| concept completeness | 36.4 | 36.4 |
| average degree | 1.429 | 1.429 |
| density | 23.81 | 23.81 |
| components | 2 | 2 |
| largest component | 71.4 | 71.4 |
| clustering | 0.0 | 0.0 |
| cross topic coverage | None | None |
| global efficiency | 0.056 | 0.056 |
| modularity | 0.32 | 0.32 |
| concentration | 0.68 | 0.68 |
| connection strength | 0.588 | 0.588 |

Null means unavailable, not a zero grade. Concentration and connectivity describe the measured subgraph, so a few connected correct answers can have high concentration despite low overall coverage.

This round added 0 independently demonstrated relationship(s) and 0 newly assessed relationship(s). No additional independent mastery was recorded; partial, assisted, incorrect and absent explanations cannot establish independent mastery. Assessment coverage can stay unchanged when a fact is revisited or no eligible question remains.

**Stopped early:** {"kind": "eligible_questions_exhausted", "command": "maya:ai test:r2:start:0", "message": {"detail": "No eligible unmastered facts remain. Choose another topic, enable review for known facts, or approve background facts in Run Insights."}}

### Llm Tuning

Session: `2fa8f0cd-503c-4949-8511-154358e22d31`. Planned focus sequence: distillation, teacher model, offline inference.

Independent relationships: 6 → 9; assessed: 7 → 10. Reference relationships: 88 → 88.

| Existing graph metric | Before | After |
|---|---:|---:|
| relationship coverage | 6.8 | 10.2 |
| assessment coverage | 8.0 | 11.4 |
| concept reach | 6.0 | 10.4 |
| concept completeness | 6.1 | 10.0 |
| average degree | 1.5 | 1.286 |
| density | 21.43 | 9.89 |
| components | 2 | 5 |
| largest component | 62.5 | 35.7 |
| clustering | 0.0 | 0.0 |
| cross topic coverage | 0.0 | 0.0 |
| global efficiency | 0.001 | 0.001 |
| modularity | 0.444 | 0.716 |
| concentration | 0.556 | 0.284 |
| connection strength | 0.09 | 0.134 |

Null means unavailable, not a zero grade. Concentration and connectivity describe the measured subgraph, so a few connected correct answers can have high concentration despite low overall coverage.

This round added 3 independently demonstrated relationship(s) and 3 newly assessed relationship(s). The increase comes from the saved independent answer outcomes. Newly assessed does not necessarily mean mastered.

#### Question 1

Explain the relationship between distillation and smaller version of a fine tuned llm.

**Submitted answer:**

> Distillation produces a smaller version of a fine-tuned LLM, with fewer parameters.

Assistance: 0 hint(s); reveal: False. Recorded score: 100.0%.

**Recorded feedback:** Relationship progress: 1 supported, 0 related, 0 contradicted. Green: independent understanding. Yellow: partial or assisted. Red: contradicted or not demonstrated.
Complete: The learner correctly identifies the substantive connection (distillation creates/produces) and the direction (smaller version), satisfying the full_relationship criterion. The additional detail about 'fewer parameters' is consistent with the target concept and does not contradict the fact.

Targeted graph reference: [{"id": "edge_00010", "subject": "distillation", "relationship": "creates", "object": "smaller version of a fine tuned llm", "definition": "The source is an action or process that results in the target being formed or produced.", "conditions": null, "modality": null, "purpose": null, "timing": null, "negated": null, "argument_qualifiers": ["with fewer parameters"], "participants": []}]

**Contributions and reviews:**

- Distillation produces a smaller version of a fine-tuned LLM — **duplicate**.
  The student claim exactly matches edge_00010 and edge_00028, which are already present in the graph as non-novel facts.
  The student claim is a direct paraphrase of edge_00010 and edge_00028, making it non-novel. The first review correctly identifies the lack of novelty but fails to challenge whether the specific phrasing 'smaller version' adds any new nuance regarding parameter counts or architecture changes that might warrant a distinct fact ID.
- A smaller version of a fine-tuned LLM produced by distillation has fewer parameters — **duplicate**.
  The student claim states a smaller version has fewer parameters, which is directly supported by edge_00010 and edge_00028 in the graph facts.
  The student claim is supported by edge_00010 and edge_00028, which explicitly state that distillation creates a smaller version with fewer parameters. The first review correctly identifies this support but fails to note that the graph also contains edge_00030, which contradicts the implied quality of such models by stating distilled predictions are generally worse than larger ones.

Answer ID: `da0f3c69-2ee1-4d5c-a91d-8fe4786037e6`. Saved: 2026-11-26T10:29:44.082552+00:00.

#### Question 2

Explain the relationship between teacher model and dataset.

**Submitted answer:**

> The teacher model assigns labels to the data items in a dataset.

Assistance: 0 hint(s); reveal: False. Recorded score: 100.0%.

**Recorded feedback:** Relationship progress: 1 supported, 0 related, 0 contradicted. Green: independent understanding. Yellow: partial or assisted. Red: contradicted or not demonstrated.
Complete: The learner correctly identifies the direction (teacher model -> dataset) and the specific action (assigns/labels). The phrase 'data items' is a valid synonym for 'data items' implied by the definition of applying labels. No conditions or purposes were required by the fact, so none are missing.

Targeted graph reference: [{"id": "edge_00035", "subject": "teacher model", "relationship": "labels", "object": "dataset", "definition": "The process of applying labels to data items.", "conditions": null, "modality": null, "purpose": null, "timing": null, "negated": null, "argument_qualifiers": ["a dataset"], "participants": []}]

**Contributions and reviews:**

- The teacher model assigns labels to the data items in a dataset. — **duplicate**.
  The student claim describes a generic action ('assigns labels') which is already fully covered by existing graph facts (e.g., edge_00035, edge_00039) without adding new mechanisms or details; therefore it is not novel.
  The student claim is a direct paraphrase of edge_00035 ('teacher model' --labels--> 'dataset'), making it non-novel. The first review incorrectly treats this generic restatement as lacking novelty, failing to recognize that the graph already contains an exact duplicate fact.

Answer ID: `abf793d2-8b4e-4795-a566-740bd742a423`. Saved: 2026-11-26T10:33:16.509448+00:00.

#### Question 3

Explain the relationship between engineering teams and offline inference.

**Submitted answer:**

> Engineering teams use offline inference in place of online inference for their tasks.

Assistance: 0 hint(s); reveal: False. Recorded score: 100.0%.

**Recorded feedback:** Relationship progress: 1 supported, 0 related, 0 contradicted. Green: independent understanding. Yellow: partial or assisted. Red: contradicted or not demonstrated.
Complete: The learner correctly identifies the 'use' relationship between engineering teams and offline inference. The phrase 'for their tasks' aligns with the fact's definition ('employ a specific method or tool for their tasks'). Although the learner adds 'in place of online inference', this does not contradict the core fact; it merely provides additional context about the substitution, which is permissible as long as the primary relationship (use) is maintained. The criteria for explaining the substantive connection are met.

Targeted graph reference: [{"id": "edge_00066", "subject": "engineering teams", "relationship": "use", "object": "offline inference", "definition": "employ a specific method or tool for their tasks", "conditions": null, "modality": null, "purpose": null, "timing": null, "negated": null, "argument_qualifiers": ["instead of online inference"], "participants": []}]

**Contributions and reviews:**

- Engineering teams use offline inference in place of online inference for their tasks. — **duplicate**.
  The student claim exactly duplicates edge_00066, which states 'engineering teams use offline inference' with the qualifier 'instead of online inference'. Since the claim matches this existing fact without adding a new mechanism or detail, it is not novel.
  The student claim is a direct paraphrase of edge_00066, which explicitly states that engineering teams use offline inference instead of online inference. Since the claim adds no new mechanism or detail and matches an existing graph fact, it is not novel.

Answer ID: `5216dea2-4900-4188-bcc5-346f2c114eaa`. Saved: 2026-11-26T10:36:18.477929+00:00.

### Neurons And Glia

Session: `fb422bd7-3463-4a5e-bbe5-cdb612228c20`. Planned focus sequence: axon, soma, axon terminals.

Independent relationships: 5 → 8; assessed: 5 → 8. Reference relationships: 58 → 58.

| Existing graph metric | Before | After |
|---|---:|---:|
| relationship coverage | 8.6 | 13.8 |
| assessment coverage | 8.6 | 13.8 |
| concept reach | 9.7 | 15.3 |
| concept completeness | 6.9 | 9.8 |
| average degree | 1.429 | 1.455 |
| density | 23.81 | 14.55 |
| components | 2 | 3 |
| largest component | 57.1 | 45.5 |
| clustering | 0.0 | 0.0 |
| cross topic coverage | 0.0 | 0.0 |
| global efficiency | 0.003 | 0.005 |
| modularity | 0.48 | 0.594 |
| concentration | 0.52 | 0.406 |
| connection strength | 0.139 | 0.222 |

Null means unavailable, not a zero grade. Concentration and connectivity describe the measured subgraph, so a few connected correct answers can have high concentration despite low overall coverage.

This round added 3 independently demonstrated relationship(s) and 3 newly assessed relationship(s). The increase comes from the saved independent answer outcomes. Newly assessed does not necessarily mean mastered.

#### Question 1

Explain the relationship between neurons and axon.

**Submitted answer:**

> A neuron includes an axon as one of its structural parts.

Assistance: 0 hint(s); reveal: False. Recorded score: 100.0%.

**Recorded feedback:** Relationship progress: 1 supported, 0 related, 0 contradicted. Green: independent understanding. Yellow: partial or assisted. Red: contradicted or not demonstrated.
Complete: The learner correctly identifies the 'has_part' relationship, stating that a neuron includes an axon as a structural part. This matches the fact definition where the target (axon) is a structural component of the source (neuron). The direction and substantive nature of the connection are accurately explained without inventing mechanisms or adding unnecessary conditions.

Targeted graph reference: [{"id": "edge_00007", "subject": "neurons", "relationship": "has_part", "object": "axon", "definition": "TARGET is a structural component of SOURCE, not merely located there or participating in it.", "conditions": null, "modality": null, "purpose": null, "timing": null, "negated": null, "argument_qualifiers": ["an axon"], "participants": []}]

**Contributions and reviews:**

- A neuron includes an axon as one of its structural parts. — **duplicate**.
  The student claim states a neuron includes an axon as a structural part, which is directly supported by edge_00007 in the graph facts.
  The student claim is factually correct and aligns with edge_00007, which explicitly states that an axon is a structural component of a neuron. However, the first review incorrectly labels this as non-novel because it fails to recognize that while the specific relationship exists in the graph, the student's phrasing introduces a distinct pedagogical framing ('includes as one of its structural parts') rather than merely duplicating the existing fact.

Answer ID: `169b725b-f39d-4601-85b0-69e07520da19`. Saved: 2026-11-26T10:29:52.725040+00:00.

#### Question 2

Explain the relationship between neurons and soma.

**Submitted answer:**

> A neuron has a soma as one of its structural components.

Assistance: 0 hint(s); reveal: False. Recorded score: 100.0%.

**Recorded feedback:** Relationship progress: 1 supported, 0 related, 0 contradicted. Green: independent understanding. Yellow: partial or assisted. Red: contradicted or not demonstrated.
Complete: The learner correctly identifies the 'has_part' relationship, stating that a neuron possesses a soma as a structural component. This matches the fact definition where the target (soma) is a structural component of the source (neuron). The direction and substantive nature of the connection are accurately explained without inventing mechanisms or adding unnecessary conditions.

Targeted graph reference: [{"id": "edge_00005", "subject": "neurons", "relationship": "has_part", "object": "soma", "definition": "TARGET is a structural component of SOURCE, not merely located there or participating in it.", "conditions": null, "modality": null, "purpose": null, "timing": null, "negated": null, "argument_qualifiers": ["a soma"], "participants": []}]

**Contributions and reviews:**

- A neuron has a soma as one of its structural components. — **needs_review**.
  The student claim is novel because the graph contains no exact duplicate fact for this specific predicate and object combination, though a similar 'has_part' relationship exists for other components. The claim is supported as factual since the graph explicitly defines 'soma' as a structural component of 'neurons' via edge_00005.
  The student claim is supported because edge_00005 explicitly defines the 'has_part' relationship between neurons and soma, matching the student's assertion that a neuron has a soma as a structural component. The claim is not novel but rather duplicates an existing fact in the graph, contradicting the first review's conclusion of novelty.

Answer ID: `aa502d62-694f-4f36-98d2-56474ed3f5b2`. Saved: 2026-11-26T10:33:24.812699+00:00.

#### Question 3

Explain the relationship between axon terminals and neurotransmitters.

**Submitted answer:**

> Axon terminals release neurotransmitters, which are chemical messengers.

Assistance: 0 hint(s); reveal: False. Recorded score: 100.0%.

**Recorded feedback:** Relationship progress: 1 supported, 0 related, 0 contradicted. Green: independent understanding. Yellow: partial or assisted. Red: contradicted or not demonstrated.
Complete: The learner correctly identifies the substantive connection (release) and direction between axon terminals and neurotransmitters. The additional phrase 'which are chemical messengers' is a valid elaboration that does not contradict the fact.

Targeted graph reference: [{"id": "edge_00015", "subject": "axon terminals", "relationship": "release", "object": "neurotransmitters", "definition": "The act of expelling or discharging a substance from a cell or structure.", "conditions": null, "modality": null, "purpose": null, "timing": null, "negated": null, "argument_qualifiers": ["chemical messengers"], "participants": []}]

**Contributions and reviews:**

- Neurotransmitters are chemical messengers — **duplicate**.
  The student claim 'Neurotransmitters are chemical messengers' is a direct restatement of edge_00016, which defines neurotransmitters as chemical messengers conveying signals across synapses. Since the student's statement lacks the specific mechanism (diffusion and binding) found in edge_00039 but matches the core classification of edge_00016 exactly, it is not novel.
  The student claim is a direct paraphrase of edge_00016, which explicitly defines neurotransmitters as chemical messengers; therefore, it lacks novelty. The first review incorrectly penalizes the omission of specific mechanisms (diffusion and binding) found in edge_00039, treating a valid classification statement as non-novel solely because it is less detailed than another fact.
- Axon terminals release neurotransmitters — **duplicate**.
  The student claim exactly matches edge_00015, which defines axon terminals releasing neurotransmitters. Since this specific relationship and definition are already present in the graph, the contribution is non-novel.
  The student claim is a direct paraphrase of edge_00015, making it non-novel as per the instruction that exact duplicates require a duplicate_fact_id. However, the first review incorrectly labels this as 'non-novel' without assigning the required duplicate_fact_id to the existing graph row, violating the schema constraint for non-novel decisions.

Answer ID: `51d79217-a95e-4205-9760-6d8e08d5f93c`. Saved: 2026-11-26T10:36:25.522495+00:00.

## Observations retained

- AI Test has only five eligible document relationships; background additions are not approved quiz material. Four were already independently mastered before this exercise. The first new answer mastered the remaining relationship, so additional normal AI questions must stop early rather than enabling review or changing approvals.

## Audit trail

Pre-exercise database backup: `archive\databases\additional_student_quizzes_2026-11-26T095621904390+0000`. Full immutable request bodies, bounded retry history, graph references and metric snapshots are in `metadata.json`. Authored answers are in `answers_r*.json`.

Previous records, pending answers and contribution decisions were preserved. No administrative correction was mixed into natural student performance. Local model grading and contribution decisions can be surprising or wrong; their actual results remain recorded. This small, deliberately focused exercise does not establish full-topic mastery.
