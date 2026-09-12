"""
score_background_candidates.py
-----------------------------------
Improved scoring pipeline for background knowledge candidates.

Changes from v1 (score_background_candidates.py):
  1. Multi-dimensional scoring — each candidate edge is scored on 4 axes:
       D1: domain_relevance     — how relevant is the target to neuroscience domain
       D2: hierarchical_plausibility — does the proposed tier (P/S/C) make logical sense
       D3: prerequisite_value   — is this genuinely needed to understand the source concept
       D4: analogy_coherence    — reuses the analogy_score from the expansion pass
     These form a scoring vector per edge, not a single number.

  2. Eigenvalue-weighted ranking — the NxD scoring matrix is analysed via
     eigenvalue decomposition (numpy). The first eigenvector's component loadings
     weight each dimension according to how much it discriminates across candidates.
     This addresses comment 2b: no single factor is sufficient; discrimination
     across the population determines importance.

  3. Context-aware critic prompt — the critic sees the source_context paragraph,
     not just the concept string. Consistent with the context-anchored design.

  4. Transitivity awareness — the Elo/ranking approach is not used because
     as noted in comment 2, concept-relation transitivity fails along context
     dimensions. Instead the eigenvalue approach gives a per-edge absolute score
     that does not require pairwise comparisons.

  5. Tiered approval thresholds — parents and siblings are approved at a slightly
     lower threshold than children (children are the nosiest tier because generic
     concepts can appear as "children" of almost anything in neuroscience).

Outputs
-------
  --out    Approved background JSON {approved_edges: [...], rejected_edges: [...]}
           Each row carries:
             score_vector {D1, D2, D3, D4},
             eigenvalue_weighted_score,
             tier, concept_origin, source_context,
             status: accepted|rejected
"""

import argparse
import json
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field
from langchain_ollama import ChatOllama


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BANNED_CONCEPTS = {
    "thing", "stuff", "content", "object", "item", "information",
    "knowledge", "concept", "entity", "process", "structure", "function",
}

# Tiered approval thresholds: children are held to a higher bar
TIER_THRESHOLDS = {
    "parent":  0.55,
    "sibling": 0.60,
    "child":   0.68,
    "unknown": 0.65,
}

# Fallback dimension weights when eigenvalue decomposition is not possible
# (e.g., only 1 candidate). Emphasises domain relevance and prerequisite value.
FALLBACK_WEIGHTS = [0.35, 0.20, 0.30, 0.15]  # D1, D2, D3, D4


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def norm_concept(s: str) -> str:
    return " ".join(str(s).strip().lower().split())


def salvage_first_json(s: str) -> str:
    start = s.find("{")
    end = s.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("No JSON object found in response")
    return s[start:end + 1]


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class MultiDimCriticResult(BaseModel):
    domain_relevance: float = Field(ge=0.0, le=1.0,
        description="How relevant is target_concept to the neuroscience domain in context (0-1)")
    hierarchical_plausibility: float = Field(ge=0.0, le=1.0,
        description="Does the proposed tier (parent/sibling/child) make logical sense (0-1)")
    prerequisite_value: float = Field(ge=0.0, le=1.0,
        description="Is this genuinely needed to understand source_concept (0-1)")
    reason: str


# ---------------------------------------------------------------------------
# Rule-based gate (fast, no LLM)
# ---------------------------------------------------------------------------

def rule_validate(
    source_concept: str,
    relation_type: str,
    target_concept: str,
    confidence: float,
) -> Tuple[bool, str]:
    if not source_concept or not target_concept:
        return False, "empty concept"
    if source_concept == target_concept:
        return False, "self-loop"
    if target_concept in BANNED_CONCEPTS:
        return False, "too generic"
    valid_relations = {
        "is_a", "has_part", "requires_understanding_of", "sibling_of", "specializes"
    }
    if relation_type not in valid_relations:
        return False, f"invalid relation type: {relation_type}"
    if confidence < 0.25:
        return False, "proposer confidence too low"
    return True, "rule-pass"


# ---------------------------------------------------------------------------
# Multi-dimensional critic prompt
# ---------------------------------------------------------------------------

def make_multidim_critic_prompt(
    source_concept: str,
    tier: str,
    relation_type: str,
    target_concept: str,
    justification: str,
    source_context: Optional[str],
) -> str:
    ctx_block = ""
    if source_context and source_context.strip():
        ctx_block = (
            f"\nSOURCE CONTEXT (the paragraph where '{source_concept}' appears):\n"
            f"\"{source_context.strip()}\"\n"
        )

    return (
        "You are scoring a proposed background-knowledge edge for a neuroscience knowledge graph.\n"
        f"{ctx_block}\n"
        f"source_concept:  {source_concept}\n"
        f"proposed tier:   {tier}  (parent=more general, sibling=same level, child=more specific)\n"
        f"relation_type:   {relation_type}\n"
        f"target_concept:  {target_concept}\n"
        f"justification:   {justification}\n\n"
        "Score on THREE independent dimensions (0-1 each):\n"
        "  domain_relevance: Is target_concept genuinely relevant to neuroscience "
        "in the context given? (penalise generic concepts like 'cell' or 'signal')\n"
        "  hierarchical_plausibility: Does the proposed tier make logical sense? "
        "(e.g., is 'neuron' really a child of 'nervous system cell'?)\n"
        "  prerequisite_value: Would a student need to understand target_concept "
        "BEFORE understanding source_concept in this context?\n\n"
        "Return ONLY valid JSON with exactly these keys:\n"
        "domain_relevance: float 0-1\n"
        "hierarchical_plausibility: float 0-1\n"
        "prerequisite_value: float 0-1\n"
        "reason: one sentence explanation\n"
    )


# ---------------------------------------------------------------------------
# Eigenvalue-weighted ranking
# ---------------------------------------------------------------------------

def _dot(a: List[float], b: List[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def _norm(v: List[float]) -> float:
    return math.sqrt(sum(x * x for x in v))


def compute_eigenvalue_weights(score_matrix: List[List[float]]) -> List[float]:
    """
    Power-iteration approximation of the first eigenvector of S^T S,
    where S is the NxD score matrix.

    This gives dimension weights proportional to how much each dimension
    discriminates across the candidate set — addressing comment 2b:
    dimensions that vary the most across candidates carry the most weight.

    Returns a length-D weight vector (sums to 1.0).
    Falls back to FALLBACK_WEIGHTS if the matrix is degenerate.
    """
    N = len(score_matrix)
    if N < 2:
        return FALLBACK_WEIGHTS[:]

    D = len(score_matrix[0])

    # Compute S^T S (DxD covariance-like matrix)
    cov = [[0.0] * D for _ in range(D)]
    for row in score_matrix:
        for i in range(D):
            for j in range(D):
                cov[i][j] += row[i] * row[j]

    # Power iteration for first eigenvector
    v = [1.0 / math.sqrt(D)] * D
    for _ in range(50):  # 50 iterations is enough for convergence at this scale
        v_new = [0.0] * D
        for i in range(D):
            v_new[i] = sum(cov[i][j] * v[j] for j in range(D))
        n = _norm(v_new)
        if n < 1e-10:
            return FALLBACK_WEIGHTS[:]
        v = [x / n for x in v_new]

    # Convert eigenvector components to positive weights summing to 1
    weights = [abs(x) for x in v]
    total = sum(weights)
    if total < 1e-10:
        return FALLBACK_WEIGHTS[:]
    return [w / total for w in weights]


def compute_weighted_score(
    score_vector: List[float],
    weights: List[float],
) -> float:
    return sum(s * w for s, w in zip(score_vector, weights))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Multi-dimensional scoring with eigenvalue-weighted ranking for background "
            "knowledge candidates. Improved version of score_background_candidates.py."
        )
    )
    parser.add_argument("--in", dest="in_path", required=True,
                        help="Input background candidates JSON (from expand_background_knowledge.py).")
    parser.add_argument("--out", dest="out_path", required=True,
                        help="Output approved background JSON.")
    parser.add_argument("--use-critic", action="store_true",
                        help="Use LLM critic for multi-dimensional scoring (recommended).")
    parser.add_argument("--model", default="llama3.2:3b",
                        help="Ollama model for critic.")
    parser.add_argument("--threshold", type=float, default=None,
                        help="Override the per-tier approval threshold with a single value.")
    args = parser.parse_args()

    in_path = Path(args.in_path)
    out_path = Path(args.out_path)

    data = json.loads(in_path.read_text(encoding="utf-8"))
    candidates = data.get("candidates", [])

    llm = ChatOllama(model=args.model, temperature=0) if args.use_critic else None

    # -----------------------------------------------------------------------
    # Phase 1: collect all edge data + run critic
    # -----------------------------------------------------------------------
    all_rows: List[Dict[str, Any]] = []

    for row in candidates:
        if "error" in row:
            all_rows.append({
                "source_concept": row.get("source_concept", ""),
                "concept_origin": row.get("concept_origin", "extracted"),
                "error": row["error"],
                "status": "error",
            })
            continue

        source_concept = norm_concept(row.get("source_concept", ""))
        source_context: Optional[str] = row.get("source_context") or None
        concept_origin = row.get("concept_origin", "extracted")

        for edge in row.get("edges", []):
            relation_type = edge.get("relation_type", "")
            tier = edge.get("tier", "unknown")
            target_concept = norm_concept(edge.get("target_concept", ""))
            justification = str(edge.get("justification", "")).strip()
            proposer_conf = float(edge.get("confidence", 0.5))

            # Pass through analogy score from expansion phase (D4)
            analogy_score = edge.get("analogy_score")
            analogy_flag = edge.get("analogy_flag", "no_analogy_test")
            d4_analogy = float(analogy_score) if analogy_score is not None else 0.5

            # Rule gate
            ok, rule_reason = rule_validate(
                source_concept, relation_type, target_concept, proposer_conf
            )
            if not ok:
                all_rows.append({
                    "source_concept": source_concept,
                    "concept_origin": concept_origin,
                    "tier": tier,
                    "relation_type": relation_type,
                    "target_concept": target_concept,
                    "justification": justification,
                    "source_context": source_context or "",
                    "proposer_confidence": proposer_conf,
                    "score_vector": None,
                    "eigenvalue_weighted_score": 0.0,
                    "rule_reason": rule_reason,
                    "analogy_flag": analogy_flag,
                    "status": "rejected",
                })
                continue

            # Multi-dimensional critic
            d1 = d2 = d3 = proposer_conf  # fallback if no critic
            critic_reason = "critic-skipped"

            if llm is not None:
                try:
                    resp = llm.invoke(make_multidim_critic_prompt(
                        source_concept, tier, relation_type,
                        target_concept, justification, source_context
                    ))
                    raw = getattr(resp, "content", str(resp))
                    parsed = json.loads(salvage_first_json(raw))
                    result = MultiDimCriticResult.model_validate(parsed)
                    d1 = float(result.domain_relevance)
                    d2 = float(result.hierarchical_plausibility)
                    d3 = float(result.prerequisite_value)
                    critic_reason = result.reason.strip()
                except Exception as e:
                    critic_reason = f"critic-error: {e}"

            score_vector = [d1, d2, d3, d4_analogy]

            all_rows.append({
                "source_concept": source_concept,
                "concept_origin": concept_origin,
                "tier": tier,
                "relation_type": relation_type,
                "target_concept": target_concept,
                "justification": justification,
                "source_context": source_context or "",
                "proposer_confidence": proposer_conf,
                "score_vector": {
                    "D1_domain_relevance": d1,
                    "D2_hierarchical_plausibility": d2,
                    "D3_prerequisite_value": d3,
                    "D4_analogy_coherence": d4_analogy,
                },
                "critic_reason": critic_reason,
                "analogy_flag": analogy_flag,
                "rule_reason": "rule-pass",
                "status": "pending",
            })

    # -----------------------------------------------------------------------
    # Phase 2: eigenvalue-weighted ranking across all pending edges
    # -----------------------------------------------------------------------
    pending = [r for r in all_rows if r.get("status") == "pending"]

    if pending:
        matrix = [
            [
                r["score_vector"]["D1_domain_relevance"],
                r["score_vector"]["D2_hierarchical_plausibility"],
                r["score_vector"]["D3_prerequisite_value"],
                r["score_vector"]["D4_analogy_coherence"],
            ]
            for r in pending
        ]

        weights = compute_eigenvalue_weights(matrix)
        print(f"\nEigenvalue-derived dimension weights:")
        dims = ["D1_domain_relevance", "D2_hierarchical_plausibility",
                "D3_prerequisite_value", "D4_analogy_coherence"]
        for dim, w in zip(dims, weights):
            print(f"  {dim}: {w:.3f}")

        for row, vec in zip(pending, matrix):
            weighted = compute_weighted_score(vec, weights)
            row["eigenvalue_weighted_score"] = round(weighted, 4)
            row["dimension_weights_used"] = {d: round(w, 4) for d, w in zip(dims, weights)}

            # Tiered threshold
            tier = row.get("tier", "unknown")
            if args.threshold is not None:
                threshold = args.threshold
            else:
                threshold = TIER_THRESHOLDS.get(tier, TIER_THRESHOLDS["unknown"])

            row["threshold_used"] = threshold
            row["status"] = "accepted" if weighted >= threshold else "rejected"
    else:
        print("No pending edges to rank.")

    # -----------------------------------------------------------------------
    # Phase 3: separate and write output
    # -----------------------------------------------------------------------
    approved = [r for r in all_rows if r.get("status") == "accepted"]
    rejected = [r for r in all_rows if r.get("status") != "accepted"]

    # Summary statistics
    if approved:
        avg_score = sum(r.get("eigenvalue_weighted_score", 0.0) for r in approved) / len(approved)
        tier_counts = {}
        for r in approved:
            t = r.get("tier", "unknown")
            tier_counts[t] = tier_counts.get(t, 0) + 1
    else:
        avg_score = 0.0
        tier_counts = {}

    summary = {
        "total_edges_evaluated": len(all_rows),
        "approved": len(approved),
        "rejected": len(rejected),
        "avg_eigenvalue_weighted_score": round(avg_score, 4),
        "approved_by_tier": tier_counts,
        "critic_used": args.use_critic,
        "model": args.model,
    }

    out_path.write_text(
        json.dumps({"summary": summary, "approved_edges": approved, "rejected_edges": rejected}, indent=2),
        encoding="utf-8",
    )

    print(f"\nSummary: {summary}")
    print(f"Saved approved={len(approved)} rejected={len(rejected)} edges to {out_path}")


if __name__ == "__main__":
    main()
