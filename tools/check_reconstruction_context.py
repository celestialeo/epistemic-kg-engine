"""Independently evaluate a candidate reconstruction using a saved run's model settings."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pipeline.evaluation import compare_texts, METRIC_VERSION
from pipeline.models import Models
from pipeline.trace import Trace


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--reconstruction', type=Path, required=True)
    parser.add_argument('--cache', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    config = json.loads((args.cache/'manifest.json').read_text(encoding='utf-8'))['config']
    trace = Trace(args.output, args.output.name)
    try:
        model = Models(trace, config['model'], config['embedding_model'], config.get('host', 'http://localhost:11434'),
                       context_tokens=config.get('context_tokens'),
                       max_output_tokens=config.get('max_output_tokens'), think=False)
        model.preflight()
        model.load_cache(args.cache)
        result = compare_texts(args.source.read_text(encoding='utf-8-sig'),
                               args.reconstruction.read_text(encoding='utf-8'), model, 'context_regression')
        trace.save('result.json', dict(metric_version=METRIC_VERSION, source=str(args.source),
                                       candidate=str(args.reconstruction), **result))
        print(json.dumps({k:result[k] for k in ('final_score', 'original_claim_count',
                                              'matched_claim_count', 'rejected_context_matches')}))
    finally:
        trace.close()


if __name__ == '__main__':
    main()
