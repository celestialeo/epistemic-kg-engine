"""One diagnostic pass, not a pipeline run: fresh extraction and saved quote repairs."""
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
from pipeline.extraction import Extraction, INSTRUCTION, grounded_records
from pipeline.models import Models
from pipeline.trace import Trace

previous = ROOT / 'outputs/runs/llm-tuning/custom/run_20261125_015836_UTC-0500_503a3cfd'
events = [json.loads(line) for line in (previous / 'events.jsonl').read_text(encoding='utf-8').splitlines()]
config = json.loads((previous / 'manifest.json').read_text(encoding='utf-8'))['config']
text = (previous / 'input.txt').read_text(encoding='utf-8')
load_dotenv(ROOT / '.env', override=False)
trace = Trace(ROOT / 'outputs/quote_prompt_fix/passage_attempt', 'quote_prompt_passage_once')
models = Models(trace, config['model'], config['embedding_model'],
    os.getenv('OLLAMA_HOST', 'http://127.0.0.1:11434'), timeout=config['model_timeout'],
    think=config['think'], context_tokens=config['context_tokens'],
    max_output_tokens=config['max_output_tokens'], registry_model=config['registry_model'])
models.cache_enabled = False
summary = []
try:
    for identifier in ('chunk_006_sentence_004', 'chunk_006_sentence_005'):
        request = next(e for e in events if e['event'] == 'model.request'
                       and e.get('entity_id') == identifier and e['data']['role'] == 'extractor')
        payload = json.loads(request['data']['prompt'].split('\nDATA:\n', 1)[1])
        sentence = payload['CURRENT_SENTENCE']
        start = text.index(sentence)
        unit = dict(id=identifier, text=sentence, start=start, end=start + len(sentence))
        left = text.rfind('\n\n', 0, start) + 2
        right = text.find('\n\n', start)
        if right < 0: right = len(text)
        context = dict(text=text[left:right], start=left, end=right)
        print('Fresh extraction:', identifier, flush=True)
        fresh = models.ask('extractor', INSTRUCTION, payload, Extraction, identifier)
        good, failed = grounded_records(fresh, unit, context, models, SimpleNamespace(entries={}), trace)
        trace.save(f'artifacts/{identifier}_fresh.json', dict(
            response=fresh.model_dump(), accepted={k: [r[2] for r in v] for k, v in good.items()},
            unresolved=failed))
        entry = dict(sentence=sentence, fresh_valid={k: len(v) for k, v in good.items()},
                     fresh_unresolved=len(failed))
        response = next(e for e in events if e['event'] == 'model.response'
                        and e.get('entity_id') == identifier and e['data']['role'] == 'extractor')
        recorded = Extraction.model_validate(json.loads(response['data']['response']['message']['content']))
        print('Repair recorded response:', identifier, flush=True)
        good, failed = grounded_records(recorded, unit, context, models, SimpleNamespace(entries={}), trace)
        trace.save(f'artifacts/{identifier}_repair.json', dict(
            original=recorded.model_dump(), accepted={k: [r[2] for r in v] for k, v in good.items()},
            unresolved=failed))
        entry.update(replay_valid={k: len(v) for k, v in good.items()}, replay_unresolved=len(failed))
        summary.append(entry)
        print(json.dumps(entry), flush=True)
    trace.save('summary.json', dict(sentences=summary, calls=models.calls, retries=models.retries,
                                   cache_hits=models.cache_hits, options=models.options))
finally:
    trace.close()
