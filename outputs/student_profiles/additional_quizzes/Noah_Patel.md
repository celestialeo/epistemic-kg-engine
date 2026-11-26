# Noah Patel: additional quizzes

**Origin:** fictional learner with authored simulated responses, not a real student.

**Profile:** Struggling beginner. Limited starting knowledge; incomplete, incorrect and uncertain answers; uses help.

Student ID: `485fc905-6eb3-4c8c-b8de-ff66c495105d`.

This append-only exercise plans two additional normal quizzes per topic, three questions per quiz. The limit applies only to the exercise process. Production interface, metrics, selection and grading remain unchanged. Answers were authored from the displayed question and targeted graph relationship, including its direction and conditions; no internet or hidden expected answers/criteria were used. Grades were not inserted, changed or pursued through revised submissions. The same request ID and text permit at most two attempts for technical failures.

Focus choices were planned before grading to sample different concepts through the existing focus control. Green relationships remain excluded, and normal adaptive selection can move beyond the requested focus. The intended profile is not a promised metric outcome.

[Earlier profile and preserved records](../Noah_Patel.md).

## Final All Topics view

Independent relationship coverage: **0.0%**. Assessed coverage: **14.6%**. Knowledge concentration (HHI): **unavailable**. These are the existing application metrics at 2026-11-26T10:49:34.989628+00:00; no values were inserted. Unavailable concentration means there is no independently mastered subgraph to measure.

## Additional round 1

| Topic | Independent coverage before → after | Assessed coverage before → after | Average answer score before → after |
|---|---:|---:|---:|
| Ai Test | 0.0 → 0.0 | 16.7 → 41.7 | 12.5 → 21.4 |
| Llm Tuning | 0.0 → 0.0 | 4.5 → 8.0 | 25.0 → 14.3 |
| Neurons And Glia | 0.0 → 0.0 | 3.5 → 8.6 | 0.0 → 0.0 |

Coverage percentages count graph relationships; answer averages also include previous sessions. Incorrect, partial, assisted and pending responses do not establish independent mastery. Revisiting an assessed fact can leave assessment coverage unchanged. Accepted additions can enlarge the denominator without changing earlier mastery.

### Ai Test

Session: `d3ecb833-aed4-4e9f-b6a9-6f8dcdbec367`. Planned focus sequence: regularization, regularization, quantization.

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

> From the hint, I think regularization helps the small transformer work better. I cannot explain what it helps it do.

Assistance: 1 hint(s); reveal: False. Recorded score: 50.0%.

**Recorded feedback:** Relationship progress: 0 supported, 1 related, 0 contradicted. Green: independent understanding. Yellow: partial or assisted. Red: contradicted or not demonstrated.
Partly answered: The learner correctly identifies the enabling relationship ('helps') and the direction (improvement/work better) between regularization and the small transformer. Still missing: The learner fails to meet the 'full_relationship' criterion because they explicitly state they cannot explain the specific mechanism or capability improvement, resulting in an incomplete explanation of the substantive connection requested.

Targeted graph reference: [{"id": "edge_00004", "subject": "regularization", "relationship": "helps", "object": "small transformer", "definition": "The source process facilitates or improves the target capability.", "conditions": null, "modality": null, "purpose": null, "timing": null, "negated": null, "argument_qualifiers": ["generalize beyond its training examples"], "participants": []}]

Help shown: Consider how a process that facilitates or improves capability relates to the target entity.

**Contributions and reviews:**

- regularization helps the small transformer work better — **needs_review**.
  The student claim is novel because it introduces a specific performance benefit ('work better') that is not fully captured by existing graph facts, which focus on preventing overfitting or generalizing beyond training examples. While the relationship direction and entities are valid, the exact phrasing of the improvement mechanism constitutes a new contribution rather than a duplicate.
  The student claim is not novel because the graph already contains edge_00004, which explicitly states that regularization helps a small transformer with the specific qualifier 'generalize beyond its training examples', making 'work better' an unsupported generalization of an existing fact. The review incorrectly treats this as a new contribution by failing to recognize that the student's vague phrasing maps directly to the precise mechanism already defined in the knowledge graph.

Answer ID: `582a2302-3295-43f9-b065-94b6f7dd4086`. Saved: 2026-11-26T09:59:45.372971+00:00.

#### Question 2

Explain the relationship between small transformer and backpropagation.

**Submitted answer:**

> Backpropagation is when the transformer sends its finished prediction back to the person after training is over, I think.

Assistance: 0 hint(s); reveal: False. Recorded score: 0.0%.

**Recorded feedback:** Relationship progress: 0 supported, 0 related, 1 contradicted. Green: independent understanding. Yellow: partial or assisted. Red: contradicted or not demonstrated.
Contradiction: The learner asserts that backpropagation occurs 'after training is over' and involves sending predictions to a 'person'. This directly contradicts the fact which states the relationship exists 'during training' and defines it as employing a mechanism to perform its function (implied computational process), not a post-training action involving humans. Still missing: The answer fails to explain the substantive connection (using backpropagation during training) and instead provides an incorrect description of the timing and nature of the relationship.

Targeted graph reference: [{"id": "edge_00002", "subject": "small transformer", "relationship": "uses", "object": "backpropagation", "definition": "The source entity employs the target mechanism or method to perform its function.", "conditions": "during training", "modality": null, "purpose": null, "timing": null, "negated": null, "argument_qualifiers": ["to improve its predictions"], "participants": []}]

**Contributions and reviews:**

- Backpropagation is when the transformer sends its finished prediction back to the person. — **rejected**.
  The student's claim that backpropagation involves sending predictions back to a person after training contradicts established facts where backpropagation calculates gradients during training to improve model parameters, not human feedback post-training.
  The student's claim is factually incorrect because backpropagation is an internal algorithmic process for calculating gradients during training, not a mechanism for sending predictions to a human after training. The first review correctly identifies the contradiction but fails to explicitly challenge the false novelty of the claim by pointing out that the specific 'sending to person' relationship has no basis in the provided graph facts.

Answer ID: `92aba72f-68a2-47b7-b3f0-dea7b9d002e9`. Saved: 2026-11-26T10:04:01.551319+00:00.

#### Question 3

Explain the relationship between quantization and memory requirements of the small transformer.

**Submitted answer:**

> With the reveal, I understand that quantization makes the small transformer need less memory after training. I did not know that without the help.

Assistance: 0 hint(s); reveal: True. Recorded score: 50.0%.

**Recorded feedback:** Relationship progress: 0 supported, 1 related, 0 contradicted. Green: independent understanding. Yellow: partial or assisted. Red: contradicted or not demonstrated.
Partly answered: The learner correctly identifies that quantization reduces ('need less') the memory requirements of the small transformer, satisfying the criterion to explain the substantive connection with the correct direction. Still missing: The answer fails to meet the 'full_relationship' scope because it does not explicitly explain the causal mechanism or relationship itself; instead, it frames the knowledge as a personal realization ('With the reveal, I understand...') and includes an unrelated statement about not knowing something before help. The core instruction is to 'Explain the connection,' which requires stating the fact directly rather than describing the learner's state of understanding regarding that fact.

Targeted graph reference: [{"id": "edge_00005", "subject": "quantization", "relationship": "inhibits", "object": "memory requirements of the small transformer", "definition": "SOURCE reduces or suppresses the occurrence or activity of TARGET.", "conditions": null, "modality": null, "purpose": null, "timing": null, "negated": null, "argument_qualifiers": ["after training"], "participants": []}]

Help shown: Quantization inhibits the memory requirements of the small transformer by reducing or suppressing their occurrence or activity.

**Contributions and reviews:**

- quantization makes the small transformer need less memory — **duplicate**.
  The student claim states quantization reduces memory needs, which matches edge_00005 where quantization inhibits memory requirements. However, the predicate 'makes ... need less' is semantically equivalent to 'inhibits' in this context, and since no other fact explicitly links quantization to memory reduction with a different mechanism or scope, this is not a novel addition but a duplicate of an existing graph fact.
  The student claim is supported by edge_00005, which explicitly states that quantization inhibits memory requirements of the small transformer after training. However, the first review incorrectly labels this as a non-novel duplicate because it fails to recognize that the student's specific phrasing and context constitute a valid educational instance rather than an exact factual redundancy.

Answer ID: `68319798-2b64-4654-942d-95de7641901b`. Saved: 2026-11-26T10:08:17.793389+00:00.

### Llm Tuning

Session: `97546975-3e02-4380-827b-c46886e4d148`. Planned focus sequence: standard fine tuning, fine tuning, parameter efficient tuning.

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

> I think standard fine-tuning is cheap because you only change a few settings once.

Assistance: 0 hint(s); reveal: False. Recorded score: 0.0%.

**Recorded feedback:** Relationship progress: 0 supported, 0 related, 1 contradicted. Green: independent understanding. Yellow: partial or assisted. Red: contradicted or not demonstrated.
Contradiction: The learner explicitly claims that 'standard fine-tuning is cheap'. This directly contradicts the fact which states that 'standard fine tuning' possesses the property of being 'computationally expensive'. The learner's reasoning ('because you only change a few settings once') supports this incorrect claim but does not alter the fundamental contradiction regarding the cost/expensiveness. Still missing: The answer fails to demonstrate the correct relationship (that standard fine-tuning is computationally expensive) and instead asserts the opposite.

Targeted graph reference: [{"id": "edge_00019", "subject": "standard fine tuning", "relationship": "is", "object": "computationally expensive", "definition": "Indicates that the source possesses the property described by the target.", "conditions": null, "modality": null, "purpose": null, "timing": null, "negated": null, "argument_qualifiers": ["because standard fine-tuning updates the weights and biases of every parameter on each backpropagation iteration"], "participants": []}]

**Contributions and reviews:**

- standard fine-tuning is cheap — **rejected**.
  The student's claim that standard fine-tuning is cheap because 'few settings' are changed contradicts edge_00019, which explicitly states it is computationally expensive due to updating all parameters.
  The student's claim relies on a misunderstanding of the term 'settings' versus 'parameters'; changing hyperparameters is not what fine-tuning entails. The graph explicitly defines standard fine-tuning as updating every parameter, which contradicts the notion of it being cheap.

Answer ID: `ff60ef94-73cd-4c70-9388-9e3bc8806ed3`. Saved: 2026-11-26T10:00:00.164150+00:00.

#### Question 2

Explain the relationship between fine tuning and solution for a specific application.

**Submitted answer:**

> Fine-tuning has something to do with an application, but I cannot explain what gets changed into the solution.

Assistance: 0 hint(s); reveal: False. Recorded score: 0.0%.

**Recorded feedback:** Relationship progress: 0 supported, 0 related, 0 contradicted. Green: independent understanding. Yellow: partial or assisted. Red: contradicted or not demonstrated.
Not demonstrated:  Still missing: The learner explicitly states they 'cannot explain' the connection and only offers a vague association ('has something to do with'), failing to demonstrate the substantive transformation from input entity to output entity required by the criteria.

Targeted graph reference: [{"id": "edge_00009", "subject": "fine tuning", "relationship": "transforms_into", "object": "solution for a specific application", "definition": "Converts an input entity into a different output entity through a specific action.", "conditions": null, "modality": null, "purpose": null, "timing": null, "negated": null, "argument_qualifiers": ["foundation LLM"], "participants": []}]

**Contributions and reviews:**

- Fine-tuning has something to do with an application. — **duplicate**.
  The student claim 'Fine-tuning has something to do with an application' is supported by edge_00009, which explicitly states that fine-tuning transforms a foundation LLM into a solution for a specific application.
  The student claim is supported by edge_00009, which states that fine-tuning transforms a foundation LLM into a solution for a specific application. However, the first review's assertion of 'false novelty' is incorrect because the graph fact explicitly links fine-tuning to applications, making the claim non-novel rather than novel.

Answer ID: `5ce5a42f-8e10-497b-a0e3-cbe666e64f9b`. Saved: 2026-11-26T10:04:08.272211+00:00.

#### Question 3

Explain the relationship between parameter efficient tuning and standard fine tuning.

**Submitted answer:**

> I don't know the difference. I just recognize the word tuning in both names.

Assistance: 0 hint(s); reveal: False. Recorded score: 0.0%.

**Recorded feedback:** Relationship progress: 0 supported, 0 related, 0 contradicted. Green: independent understanding. Yellow: partial or assisted. Red: contradicted or not demonstrated.
Not demonstrated:  Still missing: The learner failed to explain the substantive connection between parameter efficient tuning and standard fine tuning. The answer expresses uncertainty and focuses on superficial linguistic similarities rather than describing the relationship (e.g., that one is a less expensive alternative).

Targeted graph reference: [{"id": "edge_00021", "subject": "parameter efficient tuning", "relationship": "is_a_less_expensive_alternative_to", "object": "standard fine tuning", "definition": "Identifies one process as having lower cost than another specific process.", "conditions": null, "modality": null, "purpose": null, "timing": null, "negated": null, "argument_qualifiers": ["updates only a subset of the parameters on each backpropagation iteration"], "participants": []}]

**Contributions and reviews:**

No candidate rows. Check status: completed.


Answer ID: `14b0e0a6-efe3-4a32-b22d-8cc9f63c1ee6`. Saved: 2026-11-26T10:08:24.314249+00:00.

### Neurons And Glia

Session: `5eb57ad8-e9ea-4ffc-af61-b96757d7184f`. Planned focus sequence: brain astrocyte networks, brain astrocyte networks, brain astrocyte networks.

Independent relationships: 0 → 0; assessed: 2 → 5. Reference relationships: 57 → 58.

| Existing graph metric | Before | After |
|---|---:|---:|
| relationship coverage | 0.0 | 0.0 |
| assessment coverage | 3.5 | 8.6 |
| concept reach | 0.0 | 0.0 |
| concept completeness | 0.0 | 0.0 |
| average degree | None | None |
| density | None | None |
| components | None | None |
| largest component | None | None |
| clustering | None | None |
| cross topic coverage | None | 0.0 |
| global efficiency | None | None |
| modularity | None | None |
| concentration | None | None |
| connection strength | 0.0 | 0.0 |

Null means unavailable, not a zero grade. Concentration and connectivity describe the measured subgraph, so a few connected correct answers can have high concentration despite low overall coverage.

This round added 0 independently demonstrated relationship(s) and 3 newly assessed relationship(s). No additional independent mastery was recorded; partial, assisted, incorrect and absent explanations cannot establish independent mastery. Newly assessed does not necessarily mean mastered.

#### Question 1

Explain the relationship between brain astrocyte networks and ion concentrations around neurons.

**Submitted answer:**

> I don't know what astrocytes do with ions.

Assistance: 0 hint(s); reveal: False. Recorded score: 0.0%.

**Recorded feedback:** Relationship progress: 0 supported, 0 related, 0 contradicted. Green: independent understanding. Yellow: partial or assisted. Red: contradicted or not demonstrated.
Not demonstrated:  Still missing: The learner explicitly states they do not know the relationship, failing to explain the substantive connection (regulation) between brain astrocyte networks and ion concentrations as required.

Targeted graph reference: [{"id": "edge_00022", "subject": "brain astrocyte networks", "relationship": "regulates", "object": "ion concentrations around neurons", "definition": "The source maintains or controls the state of the target.", "conditions": null, "modality": null, "purpose": null, "timing": null, "negated": null, "argument_qualifiers": [], "participants": []}]

**Contributions and reviews:**

No candidate rows. Check status: completed.


Answer ID: `9976c412-c59a-4c23-8311-b92bc93c06c8`. Saved: 2026-11-26T10:00:06.128567+00:00.

#### Question 2

Explain the relationship between brain astrocyte networks and nutrients.

**Submitted answer:**

> I think nutrients are what make the astrocyte network. I do not know which way the relationship goes.

Assistance: 0 hint(s); reveal: False. Recorded score: 0.0%.

**Recorded feedback:** Relationship progress: 0 supported, 0 related, 0 contradicted. Green: independent understanding. Yellow: partial or assisted. Red: contradicted or not demonstrated.
Not demonstrated:  Still missing: The learner failed to explain the substantive connection between brain astrocyte networks and nutrients. The answer incorrectly suggests nutrients create the network (reversed causality) and explicitly states uncertainty about the direction of the relationship, rather than stating that the networks supply nutrients.

Targeted graph reference: [{"id": "edge_00023", "subject": "brain astrocyte networks", "relationship": "supplies", "object": "nutrients", "definition": "The source provides the target to another entity (implied recipients).", "conditions": null, "modality": null, "purpose": null, "timing": null, "negated": null, "argument_qualifiers": [], "participants": []}]

**Contributions and reviews:**

Contribution processing issue retained: student_contribution_review failed for cb099a86-3846-5478-82ab-e89d3a2aac38:0:review after 3 attempts: Non-novel requires duplicate_fact_id of an equivalent supplied fact. A general or related fact that omits the new mechanism is not equivalent; otherwise use novel=true.

- nutrients are what make the astrocyte network — **needs_review**.
  Technical issue: student_contribution_review failed for cb099a86-3846-5478-82ab-e89d3a2aac38:0:review after 3 attempts: Non-novel requires duplicate_fact_id of an equivalent supplied fact. A general or related fact that omits the new mechanism is not equivalent; otherwise use novel=true.

Answer ID: `ed70e29c-a266-496d-8cc0-0dc687026843`. Saved: 2026-11-26T10:04:15.207455+00:00.

#### Question 3

Explain the relationship between brain astrocyte networks and new neuronal connections.

**Submitted answer:**

> Astrocytes have something to do with the new connections, but I cannot explain what they do.

Assistance: 0 hint(s); reveal: False. Recorded score: 0.0%.

**Recorded feedback:** Relationship progress: 0 supported, 0 related, 0 contradicted. Green: independent understanding. Yellow: partial or assisted. Red: contradicted or not demonstrated.
Not demonstrated:  Still missing: The learner explicitly states an inability to explain the connection ('I cannot explain what they do'). This fails the criterion to 'Explain the substantive connection between the named concepts'. The answer provides no direction, effect, or mechanism for how astrocytes influence neuronal connections.

Targeted graph reference: [{"id": "edge_00024", "subject": "brain astrocyte networks", "relationship": "helps_control", "object": "new neuronal connections", "definition": "The source assists in managing or limiting the formation/state of the target.", "conditions": null, "modality": null, "purpose": null, "timing": null, "negated": null, "argument_qualifiers": [], "participants": []}]

**Contributions and reviews:**

- Astrocytes have something to do with new neuronal connections. — **duplicate**.
  The student claim describes a general association between astrocytes and new connections, which is already fully captured by existing graph facts (edge_00024, edge_00042) detailing specific regulatory mechanisms like controlling formation/density. Since the student text lacks the specific mechanistic details present in the graph, it cannot be marked as a non-novel duplicate; instead, it represents a less specific version of an already substantiated fact.
  The student claim is a valid paraphrase of edge_00042 because the predicate 'have something to do with' semantically encompasses the specific regulatory action 'helps_control_formation_and_density_of'. The first review incorrectly penalizes the lack of mechanistic detail, failing to recognize that the graph fact already substantiates the general association asserted by the student.

Answer ID: `dcab33d8-7011-4ca9-8167-adf16a473467`. Saved: 2026-11-26T10:08:31.271477+00:00.

## Additional round 2

| Topic | Independent coverage before → after | Assessed coverage before → after | Average answer score before → after |
|---|---:|---:|---:|
| Ai Test | 0.0 → 0.0 | 41.7 → 41.7 | 21.4 → 15.0 |
| Llm Tuning | 0.0 → 0.0 | 8.0 → 11.4 | 14.3 → 10.0 |
| Neurons And Glia | 0.0 → 0.0 | 8.6 → 13.8 | 0.0 → 12.5 |

Coverage percentages count graph relationships; answer averages also include previous sessions. Incorrect, partial, assisted and pending responses do not establish independent mastery. Revisiting an assessed fact can leave assessment coverage unchanged. Accepted additions can enlarge the denominator without changing earlier mastery.

### Ai Test

Session: `443dc0da-fac9-4986-87f1-d0c5ab8e8d5b`. Planned focus sequence: retrieval augmented generation, retrieval augmented generation, self attention.

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

> I think self-attention is something the transformer does, but I can't explain what it is used for.

Assistance: 0 hint(s); reveal: False. Recorded score: 0.0%.

**Recorded feedback:** Relationship progress: 0 supported, 0 related, 0 contradicted. Green: independent understanding. Yellow: partial or assisted. Red: contradicted or not demonstrated.
Not demonstrated:  Still missing: The learner fails to explain the substantive connection (that the small transformer employs self attention) and explicitly states an inability to do so.

Targeted graph reference: [{"id": "edge_00001", "subject": "small transformer", "relationship": "uses", "object": "self attention", "definition": "The source entity employs the target mechanism or method to perform its function.", "conditions": null, "modality": null, "purpose": null, "timing": null, "negated": null, "argument_qualifiers": ["to process text"], "participants": []}]

**Contributions and reviews:**

No candidate rows. Check status: completed.


Answer ID: `d5eec29e-1bc5-499a-9add-180b71bfbfd5`. Saved: 2026-11-26T10:29:59.694792+00:00.

#### Question 2

Explain the relationship between small transformer and backpropagation.

**Submitted answer:**

> I was wrong about it happening after training, but I still cannot explain what backpropagation does.

Assistance: 0 hint(s); reveal: False. Recorded score: 0.0%.

**Recorded feedback:** Relationship progress: 0 supported, 0 related, 0 contradicted. Green: independent understanding. Yellow: partial or assisted. Red: contradicted or not demonstrated.
Not demonstrated:  Still missing: The learner explicitly states they 'cannot explain' the relationship and admits to being wrong about a condition ('after training'), failing to provide any substantive connection between the small transformer and backpropagation as required.

Targeted graph reference: [{"id": "edge_00002", "subject": "small transformer", "relationship": "uses", "object": "backpropagation", "definition": "The source entity employs the target mechanism or method to perform its function.", "conditions": "during training", "modality": null, "purpose": null, "timing": null, "negated": null, "argument_qualifiers": ["to improve its predictions"], "participants": []}]

**Contributions and reviews:**

No candidate rows. Check status: needs_review.

Contribution processing issue retained: student_contribution_extract failed for contributions:a29a842d-5248-4107-97c9-88aaac1faad0:0 after 3 attempts: New entity 'speaker' must be named in the student text; use actual subject/object entities, not input-field names


Answer ID: `a29a842d-5248-4107-97c9-88aaac1faad0`. Saved: 2026-11-26T10:33:32.203459+00:00.

#### Question 3

Explain the relationship between self attention and text.

**Submitted answer:**

> I don't know what self-attention does to text.

Assistance: 0 hint(s); reveal: False. Recorded score: 0.0%.

**Recorded feedback:** Relationship progress: 0 supported, 0 related, 0 contradicted. Green: independent understanding. Yellow: partial or assisted. Red: contradicted or not demonstrated.
Not demonstrated:  Still missing: The learner explicitly states a lack of knowledge regarding the relationship between self-attention and text. This fails to explain the substantive connection (that self-attention processes text) required by the criteria.

Targeted graph reference: [{"id": "edge_00003", "subject": "self attention", "relationship": "processes", "object": "text", "definition": "The source action operates upon or handles the target data.", "conditions": null, "modality": null, "purpose": null, "timing": null, "negated": null, "argument_qualifiers": [], "participants": []}]

**Contributions and reviews:**

No candidate rows. Check status: completed.


Answer ID: `8edfc3c6-1ffd-45a7-a24a-68bc9f54ef97`. Saved: 2026-11-26T10:36:32.522008+00:00.

### Llm Tuning

Session: `72a92cb6-5d91-43e4-ac63-ff6849d8c399`. Planned focus sequence: distillation, teacher model, offline inference.

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

> I thought distillation made the model bigger by giving it more parameters.

Assistance: 0 hint(s); reveal: False. Recorded score: 0.0%.

**Recorded feedback:** Relationship progress: 0 supported, 0 related, 1 contradicted. Green: independent understanding. Yellow: partial or assisted. Red: contradicted or not demonstrated.
Contradiction: The learner asserts that distillation makes the model 'bigger' and adds 'more parameters'. This directly contradicts the fact which states that distillation 'creates' a 'smaller version' of an LLM. The direction of the effect (increasing size vs decreasing size) is incompatible. Still missing: The correct relationship where distillation results in a smaller model.

Targeted graph reference: [{"id": "edge_00010", "subject": "distillation", "relationship": "creates", "object": "smaller version of a fine tuned llm", "definition": "The source is an action or process that results in the target being formed or produced.", "conditions": null, "modality": null, "purpose": null, "timing": null, "negated": null, "argument_qualifiers": ["with fewer parameters"], "participants": []}]

**Contributions and reviews:**

- distillation makes the model bigger — **rejected**.
  The student's claim that distillation makes a model bigger by adding parameters contradicts graph facts edge_00010 and edge_00028, which explicitly state that distillation creates a smaller version of an LLM with fewer parameters. The relationship 'distillation --makes bigger--> model' is therefore false based on the provided data.
  The student's claim that distillation increases model size by adding parameters is directly contradicted by graph facts edge_00010 and edge_00028, which define distillation as a process creating a smaller LLM with fewer parameters. The proposed relationship 'distillation --makes bigger--> model' is therefore factually incorrect within the context of the provided knowledge graph.

Answer ID: `1ebce0f3-1b93-4771-b534-64482c7214fd`. Saved: 2026-11-26T10:30:14.064636+00:00.

#### Question 2

Explain the relationship between teacher model and dataset.

**Submitted answer:**

> I think the dataset labels the teacher model, but I can't explain that.

Assistance: 0 hint(s); reveal: False. Recorded score: 0.0%.

**Recorded feedback:** Relationship progress: 0 supported, 0 related, 0 contradicted. Green: independent understanding. Yellow: partial or assisted. Red: contradicted or not demonstrated.
Not demonstrated:  Still missing: The learner incorrectly reverses the causal direction (claiming the dataset labels the model instead of the model labeling the dataset) and explicitly states an inability to explain the connection. The answer fails to demonstrate the substantive relationship where the teacher model applies labels to the dataset.

Targeted graph reference: [{"id": "edge_00035", "subject": "teacher model", "relationship": "labels", "object": "dataset", "definition": "The process of applying labels to data items.", "conditions": null, "modality": null, "purpose": null, "timing": null, "negated": null, "argument_qualifiers": ["a dataset"], "participants": []}]

**Contributions and reviews:**

- the dataset labels the teacher model — **needs_review**.
  The student's claim that a dataset labels a teacher model contradicts the graph facts where the teacher model (or bulk inference) creates labeled data, and datasets are used to train models rather than label them.
  The student's claim is not contradicted but rather supported by edge_00035, which explicitly states that a 'teacher model' labels a 'dataset'. The first review incorrectly interprets the direction of the relationship, failing to recognize that in distillation contexts, the teacher model generates the labels for the dataset used to train the student.

Answer ID: `ee200c43-6bfc-461b-b60b-2887f3e83e14`. Saved: 2026-11-26T10:33:39.040659+00:00.

#### Question 3

Explain the relationship between engineering teams and offline inference.

**Submitted answer:**

> I don't know what offline inference is, so I can't explain the connection.

Assistance: 0 hint(s); reveal: False. Recorded score: 0.0%.

**Recorded feedback:** Relationship progress: 0 supported, 0 related, 0 contradicted. Green: independent understanding. Yellow: partial or assisted. Red: contradicted or not demonstrated.
Not demonstrated:  Still missing: The learner explicitly states they cannot explain the connection due to a lack of knowledge about one of the concepts. This fails to demonstrate the substantive relationship (that engineering teams use offline inference) required by the criteria.

Targeted graph reference: [{"id": "edge_00066", "subject": "engineering teams", "relationship": "use", "object": "offline inference", "definition": "employ a specific method or tool for their tasks", "conditions": null, "modality": null, "purpose": null, "timing": null, "negated": null, "argument_qualifiers": ["instead of online inference"], "participants": []}]

**Contributions and reviews:**

No candidate rows. Check status: completed.


Answer ID: `0ad160f0-b999-4c19-8125-c569cc954898`. Saved: 2026-11-26T10:36:39.112111+00:00.

### Neurons And Glia

Session: `3773ec36-a0fc-4cd2-acef-b7089c76c316`. Planned focus sequence: axon, soma, axon terminals.

Independent relationships: 0 → 0; assessed: 5 → 8. Reference relationships: 58 → 58.

| Existing graph metric | Before | After |
|---|---:|---:|
| relationship coverage | 0.0 | 0.0 |
| assessment coverage | 8.6 | 13.8 |
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

Explain the relationship between neurons and axon.

**Submitted answer:**

> The hint helps: an axon is a part of a neuron, one of the pieces that make it up.

Assistance: 1 hint(s); reveal: False. Recorded score: 100.0%.

**Recorded feedback:** Relationship progress: 1 supported, 0 related, 0 contradicted. Green: independent understanding. Yellow: partial or assisted. Red: contradicted or not demonstrated.
Complete: The learner correctly identifies the structural component relationship (axon as a part of a neuron), satisfying the requirement to explain the substantive connection. The phrase 'one of the pieces that make it up' reinforces this structural composition without inventing mechanisms or adding unsupported conditions.

Targeted graph reference: [{"id": "edge_00007", "subject": "neurons", "relationship": "has_part", "object": "axon", "definition": "TARGET is a structural component of SOURCE, not merely located there or participating in it.", "conditions": null, "modality": null, "purpose": null, "timing": null, "negated": null, "argument_qualifiers": ["an axon"], "participants": []}]

Help shown: Consider how the term 'has_part' defines a structural composition where one entity is an integral piece of another.

**Contributions and reviews:**

- an axon is a part of a neuron — **duplicate**.
  The student claim 'an axon is a part of a neuron' is directly supported by edge_00007, which explicitly defines an axon as a structural component of a neuron using the same compositional relationship.
  The student claim is factually supported by edge_00007, which explicitly defines an axon as a structural component of a neuron. However, the first review incorrectly labels this as 'not novel' because it fails to recognize that while the specific compositional relationship exists in the graph, the student's phrasing introduces a distinct pedagogical perspective on part-whole ontology that warrants recognition rather than simple duplication.

Answer ID: `52284985-9bf0-4c9f-a4fa-e763df6b8c5b`. Saved: 2026-11-26T10:30:27.644399+00:00.

#### Question 2

Explain the relationship between neurons and soma.

**Submitted answer:**

> I don't know what soma means.

Assistance: 0 hint(s); reveal: False. Recorded score: 0.0%.

**Recorded feedback:** Relationship progress: 0 supported, 0 related, 0 contradicted. Green: independent understanding. Yellow: partial or assisted. Red: contradicted or not demonstrated.
Not demonstrated:  Still missing: The learner failed to explain the substantive connection between neurons and soma. The answer expresses uncertainty about the term 'soma' rather than describing that a soma is a structural component of a neuron.

Targeted graph reference: [{"id": "edge_00005", "subject": "neurons", "relationship": "has_part", "object": "soma", "definition": "TARGET is a structural component of SOURCE, not merely located there or participating in it.", "conditions": null, "modality": null, "purpose": null, "timing": null, "negated": null, "argument_qualifiers": ["a soma"], "participants": []}]

**Contributions and reviews:**

No candidate rows. Check status: completed.


Answer ID: `29df3dc0-a1e7-4fe8-b7c8-66400daf3e72`. Saved: 2026-11-26T10:33:45.220146+00:00.

#### Question 3

Explain the relationship between axon terminals and neurotransmitters.

**Submitted answer:**

> I think neurotransmitters are the little parts that axon terminals are made of.

Assistance: 0 hint(s); reveal: False. Recorded score: 0.0%.

**Recorded feedback:** Relationship progress: 0 supported, 0 related, 0 contradicted. Green: independent understanding. Yellow: partial or assisted. Red: contradicted or not demonstrated.
Not demonstrated:  Still missing: The learner claims that neurotransmitters are the structural components ('little parts') that make up axon terminals. This contradicts the required relationship where axon terminals release (expel) neurotransmitters. The answer fails to explain the connection of 'release' and incorrectly describes a part-whole relationship instead.

Targeted graph reference: [{"id": "edge_00015", "subject": "axon terminals", "relationship": "release", "object": "neurotransmitters", "definition": "The act of expelling or discharging a substance from a cell or structure.", "conditions": null, "modality": null, "purpose": null, "timing": null, "negated": null, "argument_qualifiers": ["chemical messengers"], "participants": []}]

**Contributions and reviews:**

Contribution processing issue retained: student_contribution_review failed for 40fa9d58-c5c4-595a-be02-9a32140ce93a:0:review after 3 attempts: Non-novel requires duplicate_fact_id of an equivalent supplied fact. A general or related fact that omits the new mechanism is not equivalent; otherwise use novel=true.

- neurotransmitters are the little parts that axon terminals are made of — **needs_review**.
  Technical issue: student_contribution_review failed for 40fa9d58-c5c4-595a-be02-9a32140ce93a:0:review after 3 attempts: Non-novel requires duplicate_fact_id of an equivalent supplied fact. A general or related fact that omits the new mechanism is not equivalent; otherwise use novel=true.

Answer ID: `91047be0-06fb-44e3-8dce-5bb8ed0d5003`. Saved: 2026-11-26T10:36:44.759482+00:00.

## Observations retained

- Additional round 1, AI Test question 3: the original revealed answer correctly said quantization reduces memory after training, but the grader awarded 50 and objected to its personal-learning framing. The first HTTP attempt failed validation because context_used was not an exact quote; the one allowed technical retry used the identical answer and request ID and succeeded. No wording or grade was changed.
- Additional round 2 neuron-structure question 1 received 100 after a hint. It is assisted evidence, not independent green mastery. The generated hint used the internal relation label has_part; that wording was preserved.
- The backpropagation question repeated through normal selection in round 2. The new answer withdrew the earlier wrong timing but still admitted not knowing the function; the grader recorded 0. The original round-1 answer and grade remain unchanged.

## Audit trail

Pre-exercise database backup: `archive\databases\additional_student_quizzes_2026-11-26T095621904390+0000`. Full immutable request bodies, bounded retry history, graph references and metric snapshots are in `metadata.json`. Authored answers are in `answers_r*.json`.

Previous records, pending answers and contribution decisions were preserved. No administrative correction was mixed into natural student performance. Local model grading and contribution decisions can be surprising or wrong; their actual results remain recorded. This small, deliberately focused exercise does not establish full-topic mastery.
