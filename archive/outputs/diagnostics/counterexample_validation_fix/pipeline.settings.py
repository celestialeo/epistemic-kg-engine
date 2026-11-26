"""Explicit operating policy; content counts derive from inputs, not topic quotas.

The embedded defaults keep the notebook portable. EKG_SETTINGS may name a partial
JSON override; otherwise pipeline_settings.json beside the notebook is used.
"""
import copy
import json
import math
import os
from pathlib import Path
import _submission_runtime as notebook
from pydantic import TypeAdapter


def _merge(defaults, overrides, prefix=''):
    if not isinstance(overrides, dict):
        raise ValueError(f'{prefix or "settings"} must be an object')
    result = copy.deepcopy(defaults)
    for key, value in overrides.items():
        if key not in defaults:
            raise ValueError(f'Unknown setting: {prefix}{key}')
        if isinstance(defaults[key], dict):
            result[key] = _merge(defaults[key], value, prefix + key + '.')
        else:
            result[key] = value
    return result


def validate(data):
    nullable = {'workload.' + key for key in data['workload']} | {'ui.quiz_neighbor_facts', 'ui.quiz_round_questions', 'ui.thumbnail_nodes', 'ui.thumbnail_edges'}
    nonnegative = {'model.temperature', 'model.seed', 'model.validation_retries', 'model.service_retries'}
    fractions = {'health.max_failure_rate', 'review.alias_similarity', 'ui.quiz_duplicate_similarity', 'metrics.shared_knowledge_fraction'}
    real_ui = {'graph_fit_zoom', 'graph_min_zoom', 'graph_max_zoom', 'graph_zoom_sensitivity',
               'graph_damping', 'graph_centering', 'graph_min_cooling', 'graph_spring_strength',
               'graph_participant_strength', 'graph_collision_strength'}
    for section, fields in data.items():
        for key, value in fields.items():
            path = section + '.' + key
            if path in nullable and value is None:
                continue
            if path in {'review.reasoning', 'review.reasoning_fallback'}:
                if type(value) is not bool:
                    raise ValueError(f'{path} must be boolean')
                continue
            if type(value) not in (int, float) or not math.isfinite(value):
                raise ValueError(f'{path} must be a finite number')
            if section in {'assessment_weights', 'metrics'}:
                if not 0 <= value <= 1:
                    raise ValueError(f'{path} must be between zero and one')
            elif path in fractions:
                if not 0 <= value < 1:
                    raise ValueError(f'{path} must be between zero inclusive and one exclusive')
            elif path in nonnegative or section == 'evaluation_weights':
                if value < 0:
                    raise ValueError(f'{path} must be nonnegative')
            elif value <= 0:
                raise ValueError(f'{path} must be positive, or null where automatic sizing is supported')
            if path not in fractions and not (section == 'ui' and key in real_ui) and section not in {'evaluation_weights', 'assessment_weights'} and path not in {
                'model.temperature', 'model.timeout_seconds', 'model.estimated_bytes_per_token',
                'operations.server_start_seconds', 'operations.server_stop_seconds',
                'operations.server_poll_seconds', 'operations.database_start_seconds', 'operations.database_poll_seconds',
                'operations.browser_open_delay_seconds'}:
                if type(value) is not int:
                    raise ValueError(f'{path} must be an integer')
    if data['model']['max_output_tokens'] >= data['model']['context_tokens']:
        raise ValueError('Output budget must be smaller than context budget')
    if data['health']['minimum'] > data['health']['window']:
        raise ValueError('Health minimum cannot exceed its window')
    if sum(data['evaluation_weights'].values()) <= 0:
        raise ValueError('At least one evaluation weight must be positive')
    if data['ui']['interaction_batch_bytes'] <= data['ui']['interaction_details_bytes']:
        raise ValueError('Interaction batch budget must leave room for event metadata beyond the details budget')
    if not data['ui']['graph_min_zoom'] <= data['ui']['graph_fit_zoom'] <= data['ui']['graph_max_zoom']:
        raise ValueError('Graph fit zoom must lie between minimum and maximum zoom')
    if data['ui']['graph_damping'] > 1 or data['ui']['graph_min_cooling'] > 1:
        raise ValueError('Graph damping and minimum cooling cannot exceed one')
    return data


def load_settings(path=None):
    defaults = json.loads(notebook.asset_text('pipeline_settings.json'))
    explicit = path or os.environ.get('EKG_SETTINGS')
    source = Path(explicit) if explicit else notebook.root / 'pipeline_settings.json'
    if explicit or source.exists():
        defaults = _merge(defaults, json.loads(source.read_text(encoding='utf-8-sig')))
    return validate(defaults)


SETTINGS = load_settings()


def setting(section, key):
    return SETTINGS[section][key]


def snapshot():
    return copy.deepcopy(SETTINGS)


def estimated_tokens(value):
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return math.ceil(len(text.encode('utf-8')) / setting('model', 'estimated_bytes_per_token'))


def automatic_chunk_words(text, context_tokens=None, output_tokens=None):
    words = text.split()
    if not words:
        return 1
    context = context_tokens or setting('model', 'context_tokens')
    output = output_tokens or setting('model', 'max_output_tokens')
    available = context - output - setting('model', 'prompt_reserve_tokens')
    if available <= 0:
        raise ValueError('Model budgets leave no space for source text')
    # Scale by this source's observed byte density, rather than a fixed word count.
    return max(1, min(len(words), math.floor(len(words) * available / max(1, estimated_tokens(text)))))


def budgeted_pages(items, models=None, *, shared=None, schema=None, size=None, role=None):
    """Visit every item; page by serialized content and operating budgets.

    A singleton that cannot fit is sent to the normal checked model boundary,
    which raises a resource error rather than dropping or approving the item.
    """
    options = getattr(models, 'options', {})
    context = options.get('num_ctx', setting('model', 'context_tokens'))
    output = options.get('num_predict', setting('model', 'max_output_tokens'))
    if role and not getattr(models, 'think', False):
        output = min(output, role_output_budget(role) or output)
    overhead = setting('model', 'prompt_reserve_tokens') + estimated_tokens(shared or {})
    item_schema = TypeAdapter(schema).json_schema() if schema is not None else {}
    overhead += estimated_tokens(item_schema)
    capacity = max(1, context - output - overhead)
    cap = size if size is not None else getattr(models, 'batch_size', setting('workload', 'batch_size'))
    page, used = [], 0
    for item in items:
        cost = max(1, estimated_tokens(item))
        if page and (used + cost > capacity or (cap and len(page) >= cap)):
            yield page
            page, used = [], 0
        page.append(item)
        used += cost
    if page:
        yield page


def role_output_budget(role):
    if role in {'concept_alias_resolver', 'concept_alias_verifier', 'relation_resolver',
                'relation_match_verifier', 'relation_definition', 'relation_definition_verifier',
                'source_role_reader', 'polarity_repair', 'background_link_reader'}:
        return setting('model', 'registry_output_tokens')
    return None


def predicate_instruction():
    return (f"Use a short reusable predicate with at most {setting('labels', 'predicate_words')} words "
            f"and {setting('labels', 'predicate_chars')} characters. ")


def predicate_pattern():
    extra = setting('labels', 'predicate_words') - 1
    return rf'^[a-z][a-z0-9]*(?:_[a-z0-9]+){{0,{extra}}}$'


def render_asset(name):
    """Use the same UI ceilings in HTML/JS and server validation."""
    return (notebook.asset_text(name)
            .replace('__UI_SETTINGS__', json.dumps(snapshot()['ui']))
            .replace('__INPUT_CHARS__', str(setting('ui', 'input_chars')))
            .replace('__STUDENT_NAME_CHARS__', str(setting('ui', 'student_name_chars'))))
