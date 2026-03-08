import argparse
import json
from pathlib import Path
from typing import Literal, List, Dict, Any

from pydantic import BaseModel, Field
from langchain_ollama import ChatOllama


RelationType = Literal["is_a", "has_part", "requires_understanding_of"]

BANNED_CONCEPTS = {
    "thing", "stuff", "content", "object", "item", "information", "knowledge", "concept"
}


def norm_concept(s: str) -> str:
    return " ".join(str(s).strip().lower().split())


class CriticResult(BaseModel):
    valid: bool
    score: float = Field(ge=0.0, le=1.0)
    reason: str


def salvage_first_json(s: str) -> str:
    start = s.find("{")
    end = s.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("No JSON object found in response")
    return s[start:end + 1]


def make_critic_prompt(source_concept: str, relation_type: str, target_concept: str, justification: str) -> str:
    return (
        "You are validating a proposed background-knowledge edge for a scientific knowledge graph.\n"
        "Return ONLY valid JSON with exactly these keys:\n"
        "valid: boolean\n"
        "score: number from 0 to 1\n"
        "reason: short explanation\n\n"
        "Judge whether the relation is educationally and scientifically appropriate.\n\n"
        f"source_concept: {source_concept}\n"
        f"relation_type: {relation_type}\n"
        f"target_concept: {target_concept}\n"
        f"justification: {justification}\n"
    )


def rule_validate(source_concept: str, relation_type: str, target_concept: str, confidence: float) -> tuple[bool, str]:
    if not source_concept or not target_concept:
        return False, "empty concept"
    if source_concept == target_concept:
        return False, "self-loop"
    if target_concept in BANNED_CONCEPTS:
        return False, "too generic"
    if relation_type not in {"is_a", "has_part", "requires_understanding_of"}:
        return False, "invalid relation type"
    if confidence < 0.35:
        return False, "low proposer confidence"
    return True, "rule-pass"


def main():
    parser = argparse.ArgumentParser(description="Score and approve background candidates.")
    parser.add_argument("--in", dest="in_path", required=True, help="Input background candidates JSON.")
    parser.add_argument("--out", dest="out_path", required=True, help="Output approved background JSON.")
    parser.add_argument("--use-critic", action="store_true", help="Use LLM critic pass.")
    parser.add_argument("--model", default="llama3.2:3b", help="Ollama model for critic.")
    parser.add_argument("--threshold", type=float, default=0.75, help="Final approval threshold.")
    args = parser.parse_args()

    in_path = Path(args.in_path)
    out_path = Path(args.out_path)

    data = json.loads(in_path.read_text(encoding="utf-8"))
    candidates = data.get("candidates", [])

    llm = ChatOllama(model=args.model, temperature=0) if args.use_critic else None

    approved_edges: List[Dict[str, Any]] = []
    rejected_edges: List[Dict[str, Any]] = []

    for row in candidates:
        if "error" in row:
            rejected_edges.append({"source_concept": row.get("source_concept"), "error": row["error"]})
            continue

        source_concept = norm_concept(row.get("source_concept", ""))

        for edge in row.get("edges", []):
            relation_type = edge.get("relation_type", "")
            target_concept = norm_concept(edge.get("target_concept", ""))
            justification = str(edge.get("justification", "")).strip()
            proposer_conf = float(edge.get("confidence", 0.5))

            ok, rule_reason = rule_validate(source_concept, relation_type, target_concept, proposer_conf)
            if not ok:
                rejected_edges.append(
                    {
                        "source_concept": source_concept,
                        "relation_type": relation_type,
                        "target_concept": target_concept,
                        "justification": justification,
                        "proposer_confidence": proposer_conf,
                        "reason": rule_reason,
                        "status": "rejected",
                    }
                )
                continue

            critic_valid = True
            critic_score = proposer_conf
            critic_reason = "critic-skipped"

            if llm is not None:
                try:
                    resp = llm.invoke(make_critic_prompt(source_concept, relation_type, target_concept, justification))
                    raw = getattr(resp, "content", str(resp))
                    raw_json = salvage_first_json(raw)
                    parsed = json.loads(raw_json)
                    validated = CriticResult.model_validate(parsed)
                    critic_valid = bool(validated.valid)
                    critic_score = float(validated.score)
                    critic_reason = validated.reason.strip()
                except Exception as e:
                    critic_valid = False
                    critic_score = 0.0
                    critic_reason = f"critic-error: {e}"

            final_score = (0.6 * proposer_conf) + (0.4 * critic_score if args.use_critic else 0.4 * proposer_conf)
            status = "accepted" if critic_valid and final_score >= args.threshold else "rejected"

            row_out = {
                "source_concept": source_concept,
                "relation_type": relation_type,
                "target_concept": target_concept,
                "justification": justification,
                "proposer_confidence": proposer_conf,
                "critic_score": critic_score,
                "critic_reason": critic_reason,
                "final_score": round(final_score, 4),
                "status": status,
            }

            if status == "accepted":
                approved_edges.append(row_out)
            else:
                rejected_edges.append(row_out)

    out = {
        "approved_edges": approved_edges,
        "rejected_edges": rejected_edges,
    }

    out_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"Saved {len(approved_edges)} approved edges and {len(rejected_edges)} rejected edges to {out_path}")


if __name__ == "__main__":
    main()