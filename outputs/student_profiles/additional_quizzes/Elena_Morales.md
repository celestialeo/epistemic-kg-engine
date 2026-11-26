# Elena Morales: additional quizzes

**Origin:** fictional learner with authored simulated responses, not a real student.

**Profile:** Topic specialist. Neurons and glia; struggles with AI and LLM tuning.

Student ID: `f9ed9e9f-586b-40f7-9ea6-7c359d42535e`.

This append-only exercise plans two additional normal quizzes per topic, three questions per quiz. The limit applies only to the exercise process. Production interface, metrics, selection and grading remain unchanged. Answers were authored from the displayed question and targeted graph relationship, including its direction and conditions; no internet or hidden expected answers/criteria were used. Grades were not inserted, changed or pursued through revised submissions. The same request ID and text permit at most two attempts for technical failures.

Focus choices were planned before grading to sample different concepts through the existing focus control. Green relationships remain excluded, and normal adaptive selection can move beyond the requested focus. The intended profile is not a promised metric outcome.

[Earlier profile and preserved records](../Elena_Morales.md).

## Final All Topics view

Independent relationship coverage: **4.4%**. Assessed coverage: **14.6%**. Knowledge concentration (HHI): **0.388**. These are the existing application metrics at 2026-11-26T10:49:35.336307+00:00; no values were inserted. Unavailable concentration means there is no independently mastered subgraph to measure.

## Additional round 1

| Topic | Independent coverage before → after | Assessed coverage before → after | Average answer score before → after |
|---|---:|---:|---:|
| Ai Test | 0.0 → 0.0 | 16.7 → 41.7 | 0.0 → 0.0 |
| Llm Tuning | 0.0 → 0.0 | 4.5 → 8.0 | 0.0 → 14.3 |
| Neurons And Glia | 1.8 → 6.9 | 3.5 → 8.6 | 75.0 → 90.0 |

Coverage percentages count graph relationships; answer averages also include previous sessions. Incorrect, partial, assisted and pending responses do not establish independent mastery. Revisiting an assessed fact can leave assessment coverage unchanged. Accepted additions can enlarge the denominator without changing earlier mastery.

### Ai Test

Session: `83b6ceff-a7f7-4548-91ed-98e3365791ab`. Planned focus sequence: regularization, regularization, quantization.

Independent relationships: 0 → 0; assessed: 2 → 5. Reference relationships: 12 → 12.

| Existing graph metric | Before | After |
|---|---:|---:|
| relationship coverage | 0.0 | 0.0 |
| assessment coverage | 16.7 | 41.7 |
| concept reach | 0.0 | 0.0 |
| concept completeness | 0.0 | 0.0 |
| average degree | None | None |
| density | None | None |
| components | None | None |
| largest component | None | None |
| clustering | None | None |
| cross topic coverage | None | None |
| global efficiency | None | None |
| modularity | None | None |
| concentration | None | None |
| connection strength | 0.0 | 0.0 |

Null means unavailable, not a zero grade. Concentration and connectivity describe the measured subgraph, so a few connected correct answers can have high concentration despite low overall coverage.

This round added 0 independently demonstrated relationship(s) and 3 newly assessed relationship(s). No additional independent mastery was recorded; partial, assisted, incorrect and absent explanations cannot establish independent mastery. Newly assessed does not necessarily mean mastered.

#### Question 1

Explain the relationship between regularization and small transformer.

**Submitted answer:**

> Maybe regularization means repeating the same training examples until the transformer memorizes them. I am not sure.

Assistance: 0 hint(s); reveal: False. Recorded score: 0.0%.

**Recorded feedback:** Relationship progress: 0 supported, 0 related, 0 contradicted. Green: independent understanding. Yellow: partial or assisted. Red: contradicted or not demonstrated.
Not demonstrated:  Still missing: The learner failed to explain the substantive connection between regularization and small transformers. Instead of describing how regularization helps or improves the model's capability, the answer proposes an incorrect mechanism (repeating examples for memorization) and explicitly states uncertainty ('I am not sure'), which does not satisfy the criterion to explain the correct relationship.

Targeted graph reference: [{"id": "edge_00004", "subject": "regularization", "relationship": "helps", "object": "small transformer", "definition": "The source process facilitates or improves the target capability.", "conditions": null, "modality": null, "purpose": null, "timing": null, "negated": null, "argument_qualifiers": ["generalize beyond its training examples"], "participants": []}]

**Contributions and reviews:**

- regularization means repeating the same training examples — **rejected**.
  The student's claim that regularization means repeating training examples contradicts the graph fact (edge_00008) which defines regularization as a process to prevent overfitting, and is also inconsistent with edge_00004 which links it to generalization. Since no existing graph fact supports this specific incorrect mechanism, the relationship must be marked as novel.
  The student's claim is marked as 'novel' because the graph contains no fact defining regularization as 'repeating training examples'; existing facts (edge_00004, edge_00008) define it via generalization and overfitting prevention. Since the specific incorrect mechanism proposed by the student has no equivalent in the supplied data, a non-novel duplicate_fact_id cannot be assigned.

Answer ID: `6b9a6412-4b8c-46e6-9707-6a4849f447dd`. Saved: 2026-11-26T10:00:13.238808+00:00.

#### Question 2

Explain the relationship between small transformer and backpropagation.

**Submitted answer:**

> I don't know what backpropagation does or when the transformer uses it.

Assistance: 0 hint(s); reveal: False. Recorded score: 0.0%.

**Recorded feedback:** Relationship progress: 0 supported, 0 related, 0 contradicted. Green: independent understanding. Yellow: partial or assisted. Red: contradicted or not demonstrated.
Not demonstrated:  Still missing: The learner explicitly states a lack of knowledge regarding the relationship between the small transformer and backpropagation. The answer fails to explain the substantive connection (that the transformer employs backpropagation) or describe the effect/condition, resulting in no correct criteria being met.

Targeted graph reference: [{"id": "edge_00002", "subject": "small transformer", "relationship": "uses", "object": "backpropagation", "definition": "The source entity employs the target mechanism or method to perform its function.", "conditions": "during training", "modality": null, "purpose": null, "timing": null, "negated": null, "argument_qualifiers": ["to improve its predictions"], "participants": []}]

**Contributions and reviews:**

No candidate rows. Check status: completed.


Answer ID: `3a2ef0f5-33c4-478e-8127-21343102ff47`. Saved: 2026-11-26T10:04:21.977679+00:00.

#### Question 3

Explain the relationship between quantization and memory requirements of the small transformer.

**Submitted answer:**

> I would guess quantization makes the memory requirement bigger because it stores more precise numbers, but I am uncertain.

Assistance: 0 hint(s); reveal: False. Recorded score: 0.0%.

**Recorded feedback:** Relationship progress: 0 supported, 0 related, 1 contradicted. Green: independent understanding. Yellow: partial or assisted. Red: contradicted or not demonstrated.
Contradiction: Your answer contradicts this relationship: I would guess quantization makes the memory requirement bigger Still missing: The learner asserts that quantization increases ('makes bigger') memory requirements. This directly contradicts the fact which states that quantization 'inhibits' (reduces or suppresses) the memory requirements of the small transformer.

Targeted graph reference: [{"id": "edge_00005", "subject": "quantization", "relationship": "inhibits", "object": "memory requirements of the small transformer", "definition": "SOURCE reduces or suppresses the occurrence or activity of TARGET.", "conditions": null, "modality": null, "purpose": null, "timing": null, "negated": null, "argument_qualifiers": ["after training"], "participants": []}]

**Contributions and reviews:**

Contribution processing issue retained: student_contribution_review failed for 418ab1fb-9c6e-5ef9-a00f-fecf0a5312bf:0:review after 3 attempts: Non-novel requires duplicate_fact_id of an equivalent supplied fact. A general or related fact that omits the new mechanism is not equivalent; otherwise use novel=true.

- quantization makes the memory requirement bigger — **pending**.
- quantization stores more precise numbers — **needs_review**.
  Technical issue: student_contribution_review failed for 418ab1fb-9c6e-5ef9-a00f-fecf0a5312bf:0:review after 3 attempts: Non-novel requires duplicate_fact_id of an equivalent supplied fact. A general or related fact that omits the new mechanism is not equivalent; otherwise use novel=true.

Answer ID: `0636028f-36a4-4310-b928-0ec4c05bc589`. Saved: 2026-11-26T10:08:43.713230+00:00.

### Llm Tuning

Session: `0cf840da-0b7d-4b4e-bf86-6fa1c0f13f3f`. Planned focus sequence: standard fine tuning, fine tuning, parameter efficient tuning.

Independent relationships: 0 → 0; assessed: 4 → 7. Reference relationships: 88 → 88.

| Existing graph metric | Before | After |
|---|---:|---:|
| relationship coverage | 0.0 | 0.0 |
| assessment coverage | 4.5 | 8.0 |
| concept reach | 0.0 | 0.0 |
| concept completeness | 0.0 | 0.0 |
| average degree | None | None |
| density | None | None |
| components | None | None |
| largest component | None | None |
| clustering | None | None |
| cross topic coverage | 0.0 | 0.0 |
| global efficiency | None | None |
| modularity | None | None |
| concentration | None | None |
| connection strength | 0.0 | 0.0 |

Null means unavailable, not a zero grade. Concentration and connectivity describe the measured subgraph, so a few connected correct answers can have high concentration despite low overall coverage.

This round added 0 independently demonstrated relationship(s) and 3 newly assessed relationship(s). No additional independent mastery was recorded; partial, assisted, incorrect and absent explanations cannot establish independent mastery. Newly assessed does not necessarily mean mastered.

#### Question 1

Explain the relationship between standard fine tuning and computationally expensive.

**Submitted answer:**

> It sounds expensive, but I do not know what part of the computation makes it expensive.

Assistance: 0 hint(s); reveal: False. Recorded score: 50.0%.

**Recorded feedback:** Relationship progress: 0 supported, 1 related, 0 contradicted. Green: independent understanding. Yellow: partial or assisted. Red: contradicted or not demonstrated.
Partly answered: The learner correctly identifies that 'standard fine tuning' possesses the property of being 'computationally expensive' (or simply 'expensive'). Still missing: The learner fails to explain the substantive connection or mechanism requested. Instead, they admit uncertainty about 'what part of the computation makes it expensive,' which does not satisfy the criterion to explain the relationship.

Targeted graph reference: [{"id": "edge_00019", "subject": "standard fine tuning", "relationship": "is", "object": "computationally expensive", "definition": "Indicates that the source possesses the property described by the target.", "conditions": null, "modality": null, "purpose": null, "timing": null, "negated": null, "argument_qualifiers": ["because standard fine-tuning updates the weights and biases of every parameter on each backpropagation iteration"], "participants": []}]

**Contributions and reviews:**

- standard fine tuning is computationally expensive — **duplicate**.
  The student claim states 'standard fine tuning is computationally expensive', which is directly supported by edge_00019 in the graph facts. The proposed relationship matches this fact exactly, making it non-novel.
  The student claim that standard fine tuning is computationally expensive is directly supported by edge_00019 in the graph facts. The proposed relationship matches this fact exactly, making it non-novel.

Answer ID: `3889f679-2bac-47f8-a5e4-578e29da0588`. Saved: 2026-11-26T10:00:42.007673+00:00.

#### Question 2

Explain the relationship between fine tuning and solution for a specific application.

**Submitted answer:**

> Maybe fine-tuning makes a specific application more general. I might have that backwards.

Assistance: 0 hint(s); reveal: False. Recorded score: 0.0%.

**Recorded feedback:** Relationship progress: 0 supported, 0 related, 0 contradicted. Green: independent understanding. Yellow: partial or assisted. Red: contradicted or not demonstrated.
Not demonstrated:  Still missing: The answer fails to explain the substantive connection between 'fine tuning' and 'solution for a specific application'. Instead of describing how fine tuning transforms an input into a solution, it suggests the opposite effect ('makes... more general') and expresses uncertainty ('Maybe', 'I might have that backwards'). This contradicts or at best does not demonstrate the required relationship defined in the fact.

Targeted graph reference: [{"id": "edge_00009", "subject": "fine tuning", "relationship": "transforms_into", "object": "solution for a specific application", "definition": "Converts an input entity into a different output entity through a specific action.", "conditions": null, "modality": null, "purpose": null, "timing": null, "negated": null, "argument_qualifiers": ["foundation LLM"], "participants": []}]

**Contributions and reviews:**

- fine-tuning makes a specific application more general — **rejected**.
  The student's claim that fine-tuning makes a specific application more general contradicts the graph facts which state that fine-tuning transforms a foundation model into a solution for a specific application (edge_00009) and that fine-tuned models make better predictions on a task than the foundation model (edge_00022).
  The student's claim is contradicted because the graph explicitly states that fine-tuning transforms a foundation model into a solution for a specific application (edge_00009) and improves performance on that task (edge_00022), rather than increasing generality. The review correctly identifies this contradiction but fails to note that the student's statement uses 'uncertain' modality, which might warrant a different evaluation than a direct falsehood if the graph lacked specific evidence.

Answer ID: `2ca33db1-9b62-4552-9d4b-3250580be9eb`. Saved: 2026-11-26T10:04:29.597711+00:00.

#### Question 3

Explain the relationship between parameter efficient tuning and standard fine tuning.

**Submitted answer:**

> Parameter-efficient tuning sounds cheaper, but I cannot say how it differs from standard fine-tuning.

Assistance: 0 hint(s); reveal: False. Recorded score: 50.0%.

**Recorded feedback:** Relationship progress: 0 supported, 1 related, 0 contradicted. Green: independent understanding. Yellow: partial or assisted. Red: contradicted or not demonstrated.
Partly answered: The learner correctly identifies that parameter-efficient tuning is perceived as having lower cost ('sounds cheaper') compared to the alternative. Still missing: The learner fails to explicitly state the substantive connection (that it is a less expensive alternative) as a definitive fact, instead hedging with 'I cannot say how it differs'. The answer does not fully explain the relationship by confirming the direction of the effect without contradiction or uncertainty regarding the core comparison.

Targeted graph reference: [{"id": "edge_00021", "subject": "parameter efficient tuning", "relationship": "is_a_less_expensive_alternative_to", "object": "standard fine tuning", "definition": "Identifies one process as having lower cost than another specific process.", "conditions": null, "modality": null, "purpose": null, "timing": null, "negated": null, "argument_qualifiers": ["updates only a subset of the parameters on each backpropagation iteration"], "participants": []}]

**Contributions and reviews:**

- Parameter-efficient tuning sounds cheaper — **needs_review**.
  The student claim states that parameter-efficient tuning 'sounds cheaper', which aligns with the graph fact edge_00021 stating it is a 'less expensive alternative'. However, the graph explicitly defines standard fine-tuning as computationally expensive (edge_00019) and parameter-efficient tuning as updating only a subset of parameters (edge_00081), making the cost difference a factual property rather than merely a perception. The claim's use of 'sounds' implies opinion, whereas the graph substantiates the lower cost as an objective fact derived from its mechanism.
  The student claim uses 'sounds cheaper' to express a perception, whereas the graph (edge_00021) defines parameter-efficient tuning as an objective 'less expensive alternative' based on specific mechanisms like updating only adapter layers. Because the student's phrasing relies on subjective perception rather than the factual mechanism defined in the graph, it does not constitute an exact duplicate of edge_00021 and must be treated as novel.

Answer ID: `1ff4f385-8b67-45db-97de-53c087fdb1fe`. Saved: 2026-11-26T10:09:13.790163+00:00.

### Neurons And Glia

Session: `6f5bf379-d8f8-403d-8360-ca4501d1a15d`. Planned focus sequence: brain astrocyte networks, brain astrocyte networks, brain astrocyte networks.

Independent relationships: 1 → 4; assessed: 2 → 5. Reference relationships: 57 → 58.

| Existing graph metric | Before | After |
|---|---:|---:|
| relationship coverage | 1.8 | 6.9 |
| assessment coverage | 3.5 | 8.6 |
| concept reach | 2.8 | 8.3 |
| concept completeness | 1.7 | 6.0 |
| average degree | 1.0 | 1.333 |
| density | 100.0 | 26.67 |
| components | 1 | 2 |
| largest component | 100.0 | 66.7 |
| clustering | 0.0 | 0.0 |
| cross topic coverage | None | 0.0 |
| global efficiency | 0.0 | 0.002 |
| modularity | 0.0 | 0.375 |
| concentration | 1.0 | 0.625 |
| connection strength | 0.028 | 0.111 |

Null means unavailable, not a zero grade. Concentration and connectivity describe the measured subgraph, so a few connected correct answers can have high concentration despite low overall coverage.

This round added 3 independently demonstrated relationship(s) and 3 newly assessed relationship(s). The increase comes from the saved independent answer outcomes. Newly assessed does not necessarily mean mastered.

#### Question 1

Explain the relationship between brain astrocyte networks and ion concentrations around neurons.

**Submitted answer:**

> Brain astrocyte networks control the ion concentrations in the environment around neurons.

Assistance: 0 hint(s); reveal: False. Recorded score: 100.0%.

**Recorded feedback:** Relationship progress: 1 supported, 0 related, 0 contradicted. Green: independent understanding. Yellow: partial or assisted. Red: contradicted or not demonstrated.
Complete: The learner correctly identifies the source (brain astrocyte networks) and target (ion concentrations), explicitly stating the regulatory effect ('control') which satisfies the 'regulates' relation definition. The phrasing 'in the environment around neurons' accurately reflects the target description without inventing new conditions or mechanisms.

Targeted graph reference: [{"id": "edge_00022", "subject": "brain astrocyte networks", "relationship": "regulates", "object": "ion concentrations around neurons", "definition": "The source maintains or controls the state of the target.", "conditions": null, "modality": null, "purpose": null, "timing": null, "negated": null, "argument_qualifiers": [], "participants": []}]

**Contributions and reviews:**

- Brain astrocyte networks control the ion concentrations in the environment around neurons. — **duplicate**.
  The student claim exactly matches edge_00022, which states that brain astrocyte networks regulate ion concentrations around neurons. Since this specific fact already exists in the graph with an identical subject, predicate, and object, the relationship is not novel.
  The student claim is a direct paraphrase of edge_00022, which explicitly states that brain astrocyte networks regulate ion concentrations around neurons. Therefore, the relationship is not novel as it duplicates an existing graph fact.

Answer ID: `3f043398-dbdf-4366-b6db-7aca2fe7a685`. Saved: 2026-11-26T10:00:49.454698+00:00.

#### Question 2

Explain the relationship between brain astrocyte networks and nutrients.

**Submitted answer:**

> Astrocyte networks in the brain provide nutrients. The network is the supplier in this relationship.

Assistance: 0 hint(s); reveal: False. Recorded score: 100.0%.

**Recorded feedback:** Relationship progress: 1 supported, 0 related, 0 contradicted. Green: independent understanding. Yellow: partial or assisted. Red: contradicted or not demonstrated.
Complete: The learner correctly identifies the source ('Astrocyte networks in the brain') and the target ('nutrients') and explicitly states the direction of the relationship using synonymous verbs ('provide' for 'supplies'). The second sentence clarifies the role without inventing mechanisms or adding unsupported conditions.

Targeted graph reference: [{"id": "edge_00023", "subject": "brain astrocyte networks", "relationship": "supplies", "object": "nutrients", "definition": "The source provides the target to another entity (implied recipients).", "conditions": null, "modality": null, "purpose": null, "timing": null, "negated": null, "argument_qualifiers": [], "participants": []}]

**Contributions and reviews:**

- Astrocyte networks in the brain provide nutrients. — **duplicate**.
  The student claim 'Astrocyte networks in the brain provide nutrients' is directly supported by edge_00023, which states 'brain astrocyte networks supplies nutrients'. The proposed relationship matches this existing fact exactly.
  The student claim is supported by edge_00023, which explicitly states that brain astrocyte networks supply nutrients. However, the first review incorrectly labels this as non-novel because it fails to recognize that while the core fact exists, the student's specific phrasing and context might constitute a distinct educational instance if not an exact string duplicate of the graph row.
- Astrocyte networks in the brain provide nutrients. — **duplicate**.
  The student claim exactly matches edge_00023, which states that brain astrocyte networks supply nutrients. Since this specific fact already exists in the graph with the same subject, predicate, and object, the relationship is not novel.
  The student claim is a direct paraphrase of edge_00023, which explicitly states that brain astrocyte networks supply nutrients. Therefore, the relationship is not novel as it duplicates an existing graph fact.

Answer ID: `25fbf4ef-7752-44f9-9507-bb4619409be5`. Saved: 2026-11-26T10:04:51.662627+00:00.

#### Question 3

Explain the relationship between brain astrocyte networks and new neuronal connections.

**Submitted answer:**

> Brain astrocyte networks help regulate the formation and state of new neuronal connections.

Assistance: 0 hint(s); reveal: False. Recorded score: 100.0%.

**Recorded feedback:** Relationship progress: 1 supported, 0 related, 0 contradicted. Green: independent understanding. Yellow: partial or assisted. Red: contradicted or not demonstrated.
Complete: The learner correctly identifies the source ('brain astrocyte networks') and target ('new neuronal connections'). The phrase 'help regulate' semantically matches the required relation 'helps_control' (assisting in managing/limiting). The specific aspects of 'formation and state' are accurately reflected. No contradictory claims or invented mechanisms are present.

Targeted graph reference: [{"id": "edge_00024", "subject": "brain astrocyte networks", "relationship": "helps_control", "object": "new neuronal connections", "definition": "The source assists in managing or limiting the formation/state of the target.", "conditions": null, "modality": null, "purpose": null, "timing": null, "negated": null, "argument_qualifiers": [], "participants": []}]

**Contributions and reviews:**

- Brain astrocyte networks help regulate the formation and state of new neuronal connections. — **needs_review**.
  The student claim is novel because no existing graph fact exactly duplicates the specific predicate 'help regulate the formation and state of' combined with both 'brain astrocyte networks' and 'new neuronal connections'. While edge_00042 covers regulation of formation and density, it lacks the explicit 'state' component found in the student's text.
  The first review incorrectly claims novelty by ignoring edge_00042, which explicitly links 'brain astrocyte networks' to regulating the 'formation' of 'new neuronal connections', making the student's claim non-novel despite the minor semantic difference regarding 'state'. The review also fails to note that the student's predicate is a direct paraphrase of the existing graph fact rather than a distinct new mechanism.

Answer ID: `97a94a16-d7a8-464f-b1fd-cdc2451c65eb`. Saved: 2026-11-26T10:09:21.593830+00:00.

## Additional round 2

| Topic | Independent coverage before → after | Assessed coverage before → after | Average answer score before → after |
|---|---:|---:|---:|
| Ai Test | 0.0 → 0.0 | 41.7 → 41.7 | 0.0 → 0.0 |
| Llm Tuning | 0.0 → 0.0 | 8.0 → 11.4 | 14.3 → 10.0 |
| Neurons And Glia | 6.9 → 12.1 | 8.6 → 13.8 | 90.0 → 93.8 |

Coverage percentages count graph relationships; answer averages also include previous sessions. Incorrect, partial, assisted and pending responses do not establish independent mastery. Revisiting an assessed fact can leave assessment coverage unchanged. Accepted additions can enlarge the denominator without changing earlier mastery.

### Ai Test

Session: `a87acae7-758b-4903-a71f-7ef28710e8e9`. Planned focus sequence: retrieval augmented generation, retrieval augmented generation, self attention.

Independent relationships: 0 → 0; assessed: 5 → 5. Reference relationships: 12 → 12.

| Existing graph metric | Before | After |
|---|---:|---:|
| relationship coverage | 0.0 | 0.0 |
| assessment coverage | 41.7 | 41.7 |
| concept reach | 0.0 | 0.0 |
| concept completeness | 0.0 | 0.0 |
| average degree | None | None |
| density | None | None |
| components | None | None |
| largest component | None | None |
| clustering | None | None |
| cross topic coverage | None | None |
| global efficiency | None | None |
| modularity | None | None |
| concentration | None | None |
| connection strength | 0.0 | 0.0 |

Null means unavailable, not a zero grade. Concentration and connectivity describe the measured subgraph, so a few connected correct answers can have high concentration despite low overall coverage.

This round added 0 independently demonstrated relationship(s) and 0 newly assessed relationship(s). No additional independent mastery was recorded; partial, assisted, incorrect and absent explanations cannot establish independent mastery. Assessment coverage can stay unchanged when a fact is revisited or no eligible question remains.

#### Question 1

Explain the relationship between small transformer and self attention.

**Submitted answer:**

> I recognize the names, but I don't know how the small transformer uses self-attention.

Assistance: 0 hint(s); reveal: False. Recorded score: 0.0%.

**Recorded feedback:** Relationship progress: 0 supported, 0 related, 0 contradicted. Green: independent understanding. Yellow: partial or assisted. Red: contradicted or not demonstrated.
Not demonstrated:  Still missing: The learner explicitly states they do not know the connection and fails to explain the substantive relationship (that the small transformer employs self-attention) as required by the criteria.

Targeted graph reference: [{"id": "edge_00001", "subject": "small transformer", "relationship": "uses", "object": "self attention", "definition": "The source entity employs the target mechanism or method to perform its function.", "conditions": null, "modality": null, "purpose": null, "timing": null, "negated": null, "argument_qualifiers": ["to process text"], "participants": []}]

**Contributions and reviews:**

No candidate rows. Check status: completed.


Answer ID: `76ae9c1e-9c91-43ca-96de-4f8aa5254a28`. Saved: 2026-11-26T10:30:33.934618+00:00.

#### Question 2

Explain the relationship between small transformer and backpropagation.

**Submitted answer:**

> I think it is used while learning, but I do not know what it does for the transformer.

Assistance: 0 hint(s); reveal: False. Recorded score: 0.0%.

**Recorded feedback:** Relationship progress: 0 supported, 0 related, 0 contradicted. Green: independent understanding. Yellow: partial or assisted. Red: contradicted or not demonstrated.
Not demonstrated:  Still missing: The learner fails to explain the substantive connection between the small transformer and backpropagation. While the phrase 'used while learning' loosely aligns with the condition 'during training', the learner explicitly states they do not know what it does, failing to describe the effect (that the transformer employs backpropagation to perform its function). The answer contains no explanation of the relationship.

Targeted graph reference: [{"id": "edge_00002", "subject": "small transformer", "relationship": "uses", "object": "backpropagation", "definition": "The source entity employs the target mechanism or method to perform its function.", "conditions": "during training", "modality": null, "purpose": null, "timing": null, "negated": null, "argument_qualifiers": ["to improve its predictions"], "participants": []}]

**Contributions and reviews:**

No candidate rows. Check status: completed.


Answer ID: `f8965953-c2d8-44db-af89-8c729ae9fbb5`. Saved: 2026-11-26T10:33:52.949333+00:00.

#### Question 3

Explain the relationship between self attention and text.

**Submitted answer:**

> I think self-attention has something to do with text, but I cannot say what it does.

Assistance: 0 hint(s); reveal: False. Recorded score: 0.0%.

**Recorded feedback:** Relationship progress: 0 supported, 0 related, 0 contradicted. Green: independent understanding. Yellow: partial or assisted. Red: contradicted or not demonstrated.
Not demonstrated:  Still missing: The learner fails to explain the substantive connection between 'self attention' and 'text'. The answer explicitly states an inability to define the effect ('cannot say what it does'), which contradicts the requirement to explain that self-attention processes text.

Targeted graph reference: [{"id": "edge_00003", "subject": "self attention", "relationship": "processes", "object": "text", "definition": "The source action operates upon or handles the target data.", "conditions": null, "modality": null, "purpose": null, "timing": null, "negated": null, "argument_qualifiers": [], "participants": []}]

**Contributions and reviews:**

No candidate rows. Check status: completed.


Answer ID: `b366e231-545c-41eb-9cc6-04c2a3973832`. Saved: 2026-11-26T10:36:51.679518+00:00.

### Llm Tuning

Session: `ae6c76ec-793f-4441-bcc2-fbdc03e66f42`. Planned focus sequence: distillation, teacher model, offline inference.

Independent relationships: 0 → 0; assessed: 7 → 10. Reference relationships: 88 → 88.

| Existing graph metric | Before | After |
|---|---:|---:|
| relationship coverage | 0.0 | 0.0 |
| assessment coverage | 8.0 | 11.4 |
| concept reach | 0.0 | 0.0 |
| concept completeness | 0.0 | 0.0 |
| average degree | None | None |
| density | None | None |
| components | None | None |
| largest component | None | None |
| clustering | None | None |
| cross topic coverage | 0.0 | 0.0 |
| global efficiency | None | None |
| modularity | None | None |
| concentration | None | None |
| connection strength | 0.0 | 0.0 |

Null means unavailable, not a zero grade. Concentration and connectivity describe the measured subgraph, so a few connected correct answers can have high concentration despite low overall coverage.

This round added 0 independently demonstrated relationship(s) and 3 newly assessed relationship(s). No additional independent mastery was recorded; partial, assisted, incorrect and absent explanations cannot establish independent mastery. Newly assessed does not necessarily mean mastered.

#### Question 1

Explain the relationship between distillation and smaller version of a fine tuned llm.

**Submitted answer:**

> I remember something about a smaller model, but I cannot say whether distillation creates it or just runs it.

Assistance: 0 hint(s); reveal: False. Recorded score: 0.0%.

**Recorded feedback:** Relationship progress: 0 supported, 0 related, 0 contradicted. Green: independent understanding. Yellow: partial or assisted. Red: contradicted or not demonstrated.
Not demonstrated:  Still missing: The learner explicitly states uncertainty ('cannot say') and fails to explain the substantive connection (that distillation creates the smaller model). The answer does not assert the correct relationship defined in the fact.

Targeted graph reference: [{"id": "edge_00010", "subject": "distillation", "relationship": "creates", "object": "smaller version of a fine tuned llm", "definition": "The source is an action or process that results in the target being formed or produced.", "conditions": null, "modality": null, "purpose": null, "timing": null, "negated": null, "argument_qualifiers": ["with fewer parameters"], "participants": []}]

**Contributions and reviews:**

No candidate rows. Check status: needs_review.

Contribution processing issue retained: student_contribution_extract failed for contributions:ec912e30-7bb0-408a-b5c5-440d4a0535e1:0 after 3 attempts: New entity 'speaker' must be named in the student text; use actual subject/object entities, not input-field names


Answer ID: `ec912e30-7bb0-408a-b5c5-440d4a0535e1`. Saved: 2026-11-26T10:30:40.448999+00:00.

#### Question 2

Explain the relationship between teacher model and dataset.

**Submitted answer:**

> I know models use datasets, but I don't know what the teacher model does to this dataset.

Assistance: 0 hint(s); reveal: False. Recorded score: 0.0%.

**Recorded feedback:** Relationship progress: 0 supported, 0 related, 0 contradicted. Green: independent understanding. Yellow: partial or assisted. Red: contradicted or not demonstrated.
Not demonstrated:  Still missing: The learner explicitly states they do not know the relationship between the teacher model and the dataset. The answer fails to explain the substantive connection (that the teacher model applies labels) or provide any correct effect, resulting in no criteria being met.

Targeted graph reference: [{"id": "edge_00035", "subject": "teacher model", "relationship": "labels", "object": "dataset", "definition": "The process of applying labels to data items.", "conditions": null, "modality": null, "purpose": null, "timing": null, "negated": null, "argument_qualifiers": ["a dataset"], "participants": []}]

**Contributions and reviews:**

- models use datasets — **needs_review**.
  The student claim 'models use datasets' is a broad generalization not explicitly supported by the graph, which details specific training relationships (e.g., foundation llm trained on natural language) or inference processes (e.g., teacher model labels dataset). The graph lacks a direct fact stating that 'models' generally 'use' 'datasets' as a universal predicate without specifying the context of training versus inference.
  The student claim 'models use datasets' is a broad generalization not explicitly supported by the graph, which details specific training relationships (e.g., foundation llm trained on natural language) or inference processes (e.g., teacher model labels dataset). The graph lacks a direct fact stating that 'models' generally 'use' 'datasets' as a universal predicate without specifying the context of training versus inference.

Answer ID: `c677ecd9-dbd8-4b7b-93c6-b407d376c61a`. Saved: 2026-11-26T10:33:59.774915+00:00.

#### Question 3

Explain the relationship between engineering teams and offline inference.

**Submitted answer:**

> I am not sure; I thought engineering teams always needed online inference.

Assistance: 0 hint(s); reveal: False. Recorded score: 0.0%.

**Recorded feedback:** Relationship progress: 0 supported, 0 related, 0 contradicted. Green: independent understanding. Yellow: partial or assisted. Red: contradicted or not demonstrated.
Not demonstrated:  Still missing: The learner failed to explain the substantive connection between engineering teams and offline inference. Instead, the answer expresses uncertainty and presents an incorrect belief about 'online inference,' which contradicts the required fact that engineering teams 'use' (employ) offline inference as a tool.

Targeted graph reference: [{"id": "edge_00066", "subject": "engineering teams", "relationship": "use", "object": "offline inference", "definition": "employ a specific method or tool for their tasks", "conditions": null, "modality": null, "purpose": null, "timing": null, "negated": null, "argument_qualifiers": ["instead of online inference"], "participants": []}]

**Contributions and reviews:**

- engineering teams always needed online inference — **rejected**.
  The student's claim that engineering teams 'always' needed online inference is contradicted by graph facts stating they use offline inference (edge_00066) and that large models are too big for online inference (edge_00065). The absolute qualifier 'always' in the student text is not substantiated by the provided data.
  The student's claim is contradicted because the graph explicitly states that engineering teams use offline inference (edge_00066) and that large models are unsuitable for online inference (edge_00065), making the 'always' qualifier factually incorrect. The first review correctly identifies the contradiction but fails to challenge the student's overgeneralization by highlighting that the graph presents offline inference as a viable, resource-saving alternative specifically adopted by teams.

Answer ID: `a18de02f-5028-4583-9bdd-66cc8fd7bbbb`. Saved: 2026-11-26T10:36:58.625392+00:00.

### Neurons And Glia

Session: `01457180-7ab0-41b2-88f7-4e87ac80d9d9`. Planned focus sequence: axon, soma, axon terminals.

Independent relationships: 4 → 7; assessed: 5 → 8. Reference relationships: 58 → 58.

| Existing graph metric | Before | After |
|---|---:|---:|
| relationship coverage | 6.9 | 12.1 |
| assessment coverage | 8.6 | 13.8 |
| concept reach | 8.3 | 13.9 |
| concept completeness | 6.0 | 8.9 |
| average degree | 1.333 | 1.4 |
| density | 26.67 | 15.56 |
| components | 2 | 3 |
| largest component | 66.7 | 40.0 |
| clustering | 0.0 | 0.0 |
| cross topic coverage | 0.0 | 0.0 |
| global efficiency | 0.002 | 0.004 |
| modularity | 0.375 | 0.612 |
| concentration | 0.625 | 0.388 |
| connection strength | 0.111 | 0.194 |

Null means unavailable, not a zero grade. Concentration and connectivity describe the measured subgraph, so a few connected correct answers can have high concentration despite low overall coverage.

This round added 3 independently demonstrated relationship(s) and 3 newly assessed relationship(s). The increase comes from the saved independent answer outcomes. Newly assessed does not necessarily mean mastered.

#### Question 1

Explain the relationship between neurons and axon.

**Submitted answer:**

> An axon is a structural component of a neuron.

Assistance: 0 hint(s); reveal: False. Recorded score: 100.0%.

**Recorded feedback:** Relationship progress: 1 supported, 0 related, 0 contradicted. Green: independent understanding. Yellow: partial or assisted. Red: contradicted or not demonstrated.
Complete: The learner explicitly states that an axon is a structural component of a neuron, satisfying the requirement to explain the substantive connection with the correct direction. The answer avoids inventing mechanisms or adding unrequested conditions.

Targeted graph reference: [{"id": "edge_00007", "subject": "neurons", "relationship": "has_part", "object": "axon", "definition": "TARGET is a structural component of SOURCE, not merely located there or participating in it.", "conditions": null, "modality": null, "purpose": null, "timing": null, "negated": null, "argument_qualifiers": ["an axon"], "participants": []}]

**Contributions and reviews:**

- An axon is a structural component of a neuron. — **needs_review**.
  The student claim is novel because the existing graph contains 'axon' as a structural component of 'neurons' (edge_00007) but does not explicitly define the axon itself as a structural component in a standalone fact row. The relationship and endpoint definitions faithfully express the quote, with both 'axon' and 'neuron' present in the graph's connectivity.
  The student claim is not novel because edge_00007 explicitly defines 'axon' as a structural component of 'neurons', which fully substantiates the quote. The first review incorrectly identifies this as novel by misinterpreting the requirement for a standalone fact row rather than recognizing that existing graph connectivity and definitions already cover the claim.

Answer ID: `418778fb-4626-4f20-ade0-614605726293`. Saved: 2026-11-26T10:30:53.188498+00:00.

#### Question 2

Explain the relationship between neurons and soma.

**Submitted answer:**

> The soma is one of the structural parts that make up a neuron.

Assistance: 0 hint(s); reveal: False. Recorded score: 100.0%.

**Recorded feedback:** Relationship progress: 1 supported, 0 related, 0 contradicted. Green: independent understanding. Yellow: partial or assisted. Red: contradicted or not demonstrated.
Complete: The learner correctly identifies the 'has_part' relationship by stating the soma is a 'structural part' that 'make up' (is a component of) a neuron. This matches the fact definition that the target is a structural component of the source.

Targeted graph reference: [{"id": "edge_00005", "subject": "neurons", "relationship": "has_part", "object": "soma", "definition": "TARGET is a structural component of SOURCE, not merely located there or participating in it.", "conditions": null, "modality": null, "purpose": null, "timing": null, "negated": null, "argument_qualifiers": ["a soma"], "participants": []}]

**Contributions and reviews:**

- The soma is one of the structural parts that make up a neuron. — **needs_review**.
  The student claim is novel because no existing graph fact explicitly states that the soma is a structural part of a neuron, despite related facts defining neurons as having parts like the soma. The proposed relationship correctly captures the part-whole definition provided in the student text without duplicating an exact existing claim.
  The student claim is supported by graph fact edge_00005, which explicitly states that a neuron has_part a soma. The first review incorrectly identifies the claim as novel because it fails to recognize that existing facts already define the structural part-whole relationship between neurons and their soma.

Answer ID: `4519aac0-e62c-4864-9eb1-b2d669f17dca`. Saved: 2026-11-26T10:34:06.892214+00:00.

#### Question 3

Explain the relationship between axon terminals and neurotransmitters.

**Submitted answer:**

> Axon terminals discharge chemical messengers called neurotransmitters.

Assistance: 0 hint(s); reveal: False. Recorded score: 100.0%.

**Recorded feedback:** Relationship progress: 1 supported, 0 related, 0 contradicted. Green: independent understanding. Yellow: partial or assisted. Red: contradicted or not demonstrated.
Complete: The learner correctly identifies the substantive connection (release/discharge) and direction from axon terminals to neurotransmitters. The phrase 'chemical messengers' is a valid synonym for 'neurotransmitters'. No external facts or mechanisms were invented.

Targeted graph reference: [{"id": "edge_00015", "subject": "axon terminals", "relationship": "release", "object": "neurotransmitters", "definition": "The act of expelling or discharging a substance from a cell or structure.", "conditions": null, "modality": null, "purpose": null, "timing": null, "negated": null, "argument_qualifiers": ["chemical messengers"], "participants": []}]

**Contributions and reviews:**

- Axon terminals discharge chemical messengers called neurotransmitters. — **needs_review**.
  The student claim is novel because no existing graph fact explicitly defines the 'discharge' relationship between axon terminals and neurotransmitters, despite edge_00015 covering the release action with slightly different phrasing. The proposed relationship faithfully expresses the quote by correctly identifying axon terminals as the source and neurotransmitters as the discharged substance.
  The student claim is not novel because edge_00015 explicitly defines the relationship between axon terminals and neurotransmitters using the predicate 'release', which is semantically equivalent to 'discharge' in this biological context. The first review incorrectly treats this semantic equivalence as a lack of explicit definition, failing to recognize that the graph already substantiates the core factual claim.

Answer ID: `1f5c1f9a-db1b-400d-ace9-53137afbeaee`. Saved: 2026-11-26T10:37:05.363660+00:00.

## Observations retained

- Earlier records, including the previously accepted but incorrect self-attention/person contribution and the unresolved earlier neural-networks answer, remain unchanged. These are not corrected or retried by this exercise.

## Audit trail

Pre-exercise database backup: `archive\databases\additional_student_quizzes_2026-11-26T095621904390+0000`. Full immutable request bodies, bounded retry history, graph references and metric snapshots are in `metadata.json`. Authored answers are in `answers_r*.json`.

Previous records, pending answers and contribution decisions were preserved. No administrative correction was mixed into natural student performance. Local model grading and contribution decisions can be surprising or wrong; their actual results remain recorded. This small, deliberately focused exercise does not establish full-topic mastery.
