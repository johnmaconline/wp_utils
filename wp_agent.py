##########################################################################################
#
# Script name: wp_agent.py
#
# Description: Agentic workflow (Google ADK style) for WordPress publishing.
#              Uses an OpenAI LLM to generate post metadata, then schedules
#              posts via wp_utilities.
#
# Author: John N. Macdonald
#
##########################################################################################

import argparse
import atexit
import json
import logging
import os
import re
import sys
import time
import csv
from datetime import date
from pathlib import Path
from typing import Any
from concurrent.futures import ThreadPoolExecutor, TimeoutError

from openai import OpenAI
import requests
from bs4 import BeautifulSoup

from tools import wp_utilities as wpu

# ========================================================================================
# GLOBAL DATA
# ========================================================================================
OUT_DIR = Path('./out')
L_DEFAULT_MODEL = os.environ.get('WP_AGENT_LLM_MODEL', 'gpt-5.1')
DEFAULT_URL = 'johnmaconline.com'
PROMPT_PATH = Path('wp_meta_prompt.md')
SUGGEST_PROMPT_PATH = Path('wp_suggest_prompt.md')
CATEGORY_LIMIT = 4
TAG_LIMIT = 8
TAG_CONTEXT_LIMIT = 50
ALLOWED_CATEGORIES = ['AI', 'Leadership', 'Technology', 'Human']
QUALITY_PROFILE_DEFAULT = 'balanced'
QUALITY_PROFILE_RULES = {
    'strict': {
        'min_tags': 4,
        'require_excerpt': True,
        'require_focus_keyphrase': True,
        'require_meta_description': True,
        'require_focus_in_meta': True,
        'meta_description_min_len': 120,
        'meta_description_max_len': 160,
    },
    'balanced': {
        'min_tags': 3,
        'require_excerpt': True,
        'require_focus_keyphrase': True,
        'require_meta_description': True,
        'require_focus_in_meta': True,
        'meta_description_min_len': 0,
        'meta_description_max_len': 160,
    },
    'loose': {
        'min_tags': 1,
        'require_excerpt': False,
        'require_focus_keyphrase': False,
        'require_meta_description': True,
        'require_focus_in_meta': False,
        'meta_description_min_len': 0,
        'meta_description_max_len': 160,
    },
}

# Simple price table (USD per 1M tokens, standard processing)
PRICE_TABLE_DEFAULT = {
    'gpt-5-nano': {'in_per_m': 0.05, 'out_per_m': 0.40},
    'gpt-5-mini': {'in_per_m': 0.25, 'out_per_m': 2.00},
    'gpt-5': {'in_per_m': 1.25, 'out_per_m': 10.00},
    'gpt-5-chat-latest': {'in_per_m': 1.25, 'out_per_m': 10.00},
    'gpt-5.2': {'in_per_m': 1.75, 'out_per_m': 14.00},
    'gpt-5.2-chat-latest': {'in_per_m': 1.75, 'out_per_m': 14.00},
    'gpt-5.1': {'in_per_m': 1.25, 'out_per_m': 10.00},
    'gpt-5.1-chat-latest': {'in_per_m': 1.25, 'out_per_m': 10.00},
    'gpt-4o': {'in_per_m': 2.50, 'out_per_m': 10.00},
    'gpt-4o-mini': {'in_per_m': 0.15, 'out_per_m': 0.60},
}

SAMPLE_OUTPUTS = {
    'metadata': {
        'title': 'Example title about practical AI leadership',
        'excerpt': 'A concise two-sentence excerpt that summarizes the article for readers.',
        'categories': ['AI', 'Leadership', 'Technology', 'Human'],
        'tags': ['ai', 'leadership', 'workflow', 'automation', 'productivity', 'writing', 'tools', 'strategy'],
        'focus_keyphrase': 'practical AI leadership',
        'meta_description': 'A short meta description that includes the focus keyphrase near the start.',
    },
    'suggest': {
        'topics': [{'title': 'Example topic title about practical AI leadership', 'category': 'AI'}] * 10
    },
}

# Per-model call behavior overrides.
MODEL_CALL_CAPABILITIES = {
    'gpt-5-nano': {
        'temperature': 1,
    },
}

# ========================================================================================
# Logging Setup
# ========================================================================================
log = logging.getLogger(os.path.basename(sys.argv[0]))
log.setLevel(logging.DEBUG)

formatter = logging.Formatter(
    '%(asctime)-15s [%(funcName)25s:%(lineno)-5s] %(levelname)-8s %(message)s')

try:
    fh = logging.FileHandler(f"{os.path.splitext(os.path.basename(sys.argv[0]))[0]}.log", mode='w')
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(formatter)
    log.addHandler(fh)
except Exception as e:
    log.debug(f'File logging disabled: {e}')


# ========================================================================================
# Google AI SDK Client (stub)
# ========================================================================================
def _init_google_client(api_key: str | None, model: str) -> dict[str, Any]:
    '''
    Initialize the Google AI SDK client (stub).
    Returns a dict with connection info for debugging.
    '''
    log.debug(f'_init_google_client: model={model}, key_set={bool(api_key)}')
    if not api_key:
        log.warning('GOOGLE_ADK_API_KEY not set; client stub will run without credentials.')
    else:
        log.info('GOOGLE_ADK_API_KEY found; initializing client stub.')
    return {
        'api_key': '(set)' if api_key else '(missing)',
        'model': model,
        'client': 'google-adk-stub'
    }


def _init_llm_backend() -> dict[str, Any]:
    '''
    Validate that OpenAI API key is set.
    '''
    openai_key = os.environ.get('OPENAI_API_KEY')
    if not openai_key:
        log.error('No OpenAI API key found. Set OPENAI_API_KEY.')
        return {
            'available': [],
            'status': 'missing-keys'
        }
    log.info('LLM credentials detected for: openai')
    return {
        'available': ['openai'],
        'status': 'ok'
    }


def _ensure_stdout_logging(level: int = logging.INFO):
    for h in list(log.handlers):
        if isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler):
            return
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(formatter)
    ch.setLevel(level)
    log.addHandler(ch)


def _expand_md_list(raw_list: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in raw_list or []:
        if not item:
            continue
        cands: list[str] = []
        if any(ch in item for ch in ('*', '?', '[')):
            import glob
            cands = sorted(glob.glob(item))
            if not cands:
                log.warning(f'Wildcard "{item}" did not match any files.')
        else:
            cands = [item]
        for c in cands:
            if c in seen:
                continue
            seen.add(c)
            out.append(c)
    return out


def _slugify(text: str, default: str = 'post') -> str:
    if not text:
        return default
    slug = re.sub(r'[^A-Za-z0-9]+', '_', text).lower()
    slug = re.sub(r'_+', '_', slug).strip('_')
    return slug[:80] or default


def _slug_from_url(url: str) -> str:
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        base = f"{parsed.netloc}{parsed.path}"
    except Exception:
        base = url
    return _slugify(base, default='url')


def _normalize_url(url: str) -> str:
    url = (url or '').strip()
    if not url:
        return ''
    if not re.match(r'^https?://', url, re.IGNORECASE):
        url = f'https://{url}'
    return url


def _extract_title_from_text(text: str, fallback: str) -> str:
    for line in text.splitlines():
        if line.strip():
            return line.strip()
    return fallback


def _fetch_url_text(url: str, timeout: int = 20) -> str:
    url = _normalize_url(url)
    if not url:
        return ''
    headers = {'User-Agent': 'wp-agent/1.0'}
    response = requests.get(url, headers=headers, timeout=timeout)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, 'html.parser')
    title = soup.title.get_text(' ', strip=True) if soup.title else ''
    paragraphs = [p.get_text(' ', strip=True) for p in soup.find_all('p')]
    paragraphs = [p for p in paragraphs if p]
    parts = [title] if title else []
    parts.extend(paragraphs)
    return "\n\n".join(parts).strip()


def _extract_h1_title(markdown_text: str) -> str:
    for line in markdown_text.splitlines():
        if not line.strip():
            continue
        if re.match(r'^\s*#\s+\S', line):
            return re.sub(r'^\s*#\s+', '', line).strip()
        break
    return ''


def _load_prompt(path: Path) -> str:
    try:
        return path.read_text(encoding='utf-8')
    except Exception as e:
        log.error(f'Failed to read prompt file: {path} ({e})')
        return ''


def _ensure_unique_dir(path: Path) -> Path:
    return path


def safe_json_loads(text: str) -> dict[str, Any]:
    if not text:
        return {}
    try:
        return json.loads(text)
    except Exception:
        start = text.find('{')
        end = text.rfind('}')
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except Exception:
                return {}
    return {}


def _estimate_text_tokens(model: str, text: str) -> int:
    try:
        import tiktoken  # type: ignore
    except Exception:
        tiktoken = None

    if not tiktoken:
        return max(1, int(len(text or '') / 4))

    try:
        enc = tiktoken.encoding_for_model(model)
    except Exception:
        enc = tiktoken.get_encoding('cl100k_base')
    return len(enc.encode(text or ''))


def _estimate_input_tokens(model: str, prompt_text: str, user_payload: dict[str, Any]) -> int:
    user_str = json.dumps(user_payload, ensure_ascii=False)
    prompt_tokens = _estimate_text_tokens(model, prompt_text or '')
    user_tokens = _estimate_text_tokens(model, user_str)
    return prompt_tokens + user_tokens


def _estimate_output_tokens(model: str, operation: str) -> int:
    sample = SAMPLE_OUTPUTS.get(operation)
    if not sample:
        return 0
    sample_text = json.dumps(sample, ensure_ascii=False)
    return _estimate_text_tokens(model, sample_text)


def _rank_models_by_est_cost(prompt_text: str, user_payload: dict[str, Any], operation: str, preferred_model: str) -> list[dict[str, Any]]:
    if not PRICE_TABLE_DEFAULT:
        return []

    candidates: list[dict[str, Any]] = []
    for model, price in PRICE_TABLE_DEFAULT.items():
        in_rate = price.get('in_per_m', 0)
        out_rate = price.get('out_per_m', 0)
        if not in_rate and not out_rate:
            continue
        in_tokens = _estimate_input_tokens(model, prompt_text, user_payload)
        out_tokens = _estimate_output_tokens(model, operation)
        in_cost = (in_tokens / 1_000_000) * in_rate if in_rate else 0
        out_cost = (out_tokens / 1_000_000) * out_rate if out_rate else 0
        candidates.append({
            'model': model,
            'input_tokens': in_tokens,
            'output_tokens': out_tokens,
            'total_cost': in_cost + out_cost,
            'input_cost': in_cost,
            'output_cost': out_cost,
        })
    candidates.sort(key=lambda c: (c['total_cost'], 0 if c['model'] == preferred_model else 1, c['model']))
    return candidates


def _select_min_cost_model(prompt_text: str, user_payload: dict[str, Any], operation: str, preferred_model: str) -> tuple[str, dict[str, Any]]:
    candidates = _rank_models_by_est_cost(prompt_text, user_payload, operation, preferred_model)
    if not candidates:
        return preferred_model, {}
    chosen = candidates[0]
    return chosen['model'], chosen


def estimate_tokens_and_cost(model: str, prompt_text: str, user_payload: dict[str, Any]) -> tuple[int, float]:
    total_in = _estimate_input_tokens(model, prompt_text, user_payload)
    price = PRICE_TABLE_DEFAULT.get(model) or {}
    in_rate = price.get('in_per_m', 0)
    cost = (total_in / 1_000_000) * in_rate if in_rate else 0
    return total_in, cost


def _configured_temperature_for_model(model: str) -> int:
    cfg = MODEL_CALL_CAPABILITIES.get(model) or {}
    return int(cfg.get('temperature', 0))


def _is_unsupported_temperature_error(err: Exception) -> bool:
    msg = str(err).lower()
    return 'temperature' in msg and 'unsupported' in msg


def _run_chat_completion(
    client: OpenAI,
    model: str,
    messages: list[dict[str, str]],
    temperature: int | None
):
    with ThreadPoolExecutor(max_workers=1) as ex:
        kwargs: dict[str, Any] = {
            'model': model,
            'messages': messages,
            'timeout': 60,
        }
        if temperature is not None:
            kwargs['temperature'] = temperature
        future = ex.submit(client.chat.completions.create, **kwargs)
        start = time.time()
        while True:
            try:
                return future.result(timeout=10)
            except TimeoutError:
                elapsed = int(time.time() - start)
                log.info(f'Still waiting on LLM return... {elapsed} seconds total')


def _call_llm(prompt_text: str, user_payload: dict[str, Any], model: str, out_path: Path | None) -> tuple[dict[str, Any], dict[str, Any]]:
    client = OpenAI()
    log.info(f'+  Using LLM model: {model}')
    llm_temperature = _configured_temperature_for_model(model)
    temperature_fallback = False
    est_tokens, est_cost = estimate_tokens_and_cost(model, prompt_text, user_payload)
    log.debug(f'_call_llm: model={model}, temperature={llm_temperature}, est_tokens={est_tokens}, est_cost=${est_cost:.4f}')
    messages = [
        {'role': 'system', 'content': prompt_text},
        {'role': 'user', 'content': json.dumps(user_payload, ensure_ascii=False)},
    ]
    try:
        try:
            resp = _run_chat_completion(client, model, messages, llm_temperature)
        except Exception as first_err:
            if not _is_unsupported_temperature_error(first_err):
                raise
            temperature_fallback = True
            log.warning(
                f'+  Model={model} rejected temperature={llm_temperature}; '
                'retrying with API default temperature'
            )
            resp = _run_chat_completion(client, model, messages, None)
        usage = getattr(resp, 'usage', None)
        content = (resp.choices[0].message.content or '').strip()
        parsed = safe_json_loads(content)
        if out_path and parsed:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(json.dumps(parsed, ensure_ascii=False, indent=2), encoding='utf-8')
            log.info(f'Wrote LLM output => {out_path}')
        usage_info = {
            'prompt_tokens': getattr(usage, 'prompt_tokens', None) if usage else None,
            'completion_tokens': getattr(usage, 'completion_tokens', None) if usage else None,
            'temperature_fallback': temperature_fallback,
        }
        return parsed, usage_info
    except Exception as e:
        log.error(f'LLM call failed: {e}')
        return {}, {}


def _usage_cost(model: str, usage_info: dict[str, Any], est_tokens: int, est_cost: float) -> dict[str, Any]:
    price = PRICE_TABLE_DEFAULT.get(model) or {}
    in_rate = price.get('in_per_m', 0)
    out_rate = price.get('out_per_m', 0)
    temp_fallback = bool(usage_info.get('temperature_fallback'))
    ptok = usage_info.get('prompt_tokens') or usage_info.get('input_tokens')
    ctok = usage_info.get('completion_tokens') or usage_info.get('output_tokens')
    if ptok is None and ctok is None:
        return {
            'prompt_tokens': None,
            'completion_tokens': None,
            'estimated_input_tokens': est_tokens,
            'estimated_input_cost': est_cost,
            'total_cost': est_cost,
            'temperature_fallback': temp_fallback,
        }
    ptok = ptok or 0
    ctok = ctok or 0
    in_cost = (ptok / 1_000_000) * in_rate if in_rate else 0
    out_cost = (ctok / 1_000_000) * out_rate if out_rate else 0
    return {
        'prompt_tokens': ptok,
        'completion_tokens': ctok,
        'prompt_cost': in_cost,
        'completion_cost': out_cost,
        'total_cost': in_cost + out_cost,
        'temperature_fallback': temp_fallback,
    }


def _accumulate_usage_totals(usage_totals: dict[str, Any], usage_cost: dict[str, Any]) -> None:
    if usage_cost.get('prompt_tokens') is not None:
        usage_totals['prompt_tokens'] += usage_cost.get('prompt_tokens') or 0
    if usage_cost.get('completion_tokens') is not None:
        usage_totals['completion_tokens'] += usage_cost.get('completion_tokens') or 0
    if usage_cost.get('estimated_input_tokens') is not None:
        usage_totals['estimated_input_tokens'] += usage_cost.get('estimated_input_tokens') or 0
    if usage_cost.get('estimated_input_cost') is not None:
        usage_totals['estimated_input_cost'] += usage_cost.get('estimated_input_cost') or 0.0
    if usage_cost.get('temperature_fallback'):
        usage_totals['temperature_fallback_calls'] += 1


def _dedup_list(values: list[str]) -> list[str]:
    seen = set()
    out = []
    for v in values:
        key = v.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(v.strip())
    return out


def _normalize_categories(categories: list[str]) -> list[str]:
    allowed_map = {c.lower(): c for c in ALLOWED_CATEGORIES}
    out: list[str] = []
    for cat in categories:
        key = cat.strip().lower()
        if key in allowed_map:
            out.append(allowed_map[key])
        else:
            log.warning(f'Category not allowed, skipping: {cat}')
    return _dedup_list(out)


def normalize_meta(llm_json: dict[str, Any], default_title: str) -> dict[str, Any]:
    title = default_title or (llm_json.get('title') or '').strip()
    excerpt = (llm_json.get('excerpt') or '').strip()
    categories = llm_json.get('categories') or []
    if isinstance(categories, str):
        categories = [categories]
    categories = _dedup_list([str(c) for c in categories if str(c).strip()])
    categories = [c for c in categories if c.lower() != 'the250']
    categories = _normalize_categories(categories)
    if len(categories) > CATEGORY_LIMIT:
        log.warning(f'Categories over limit ({CATEGORY_LIMIT}); truncating.')
        categories = categories[:CATEGORY_LIMIT]
    tags = llm_json.get('tags') or []
    if isinstance(tags, str):
        tags = [tags]
    tags = _dedup_list([str(t) for t in tags if str(t).strip()])
    if len(tags) > TAG_LIMIT:
        log.warning(f'Tags over limit ({TAG_LIMIT}); truncating.')
        tags = tags[:TAG_LIMIT]
    focus_keyphrase = (llm_json.get('focus_keyphrase') or llm_json.get('yoast_focus_keyphrase') or '').strip()
    meta_description = (llm_json.get('meta_description') or llm_json.get('yoast_meta_description') or '').strip()
    if meta_description and len(meta_description) > 160:
        log.warning('Meta description over 160 chars; truncating.')
        meta_description = meta_description[:160].rstrip()
    return {
        'title': title,
        'excerpt': excerpt,
        'categories': categories,
        'tags': tags,
        'focus_keyphrase': focus_keyphrase,
        'meta_description': meta_description,
    }


def _metadata_quality_issues(meta: dict[str, Any], profile: str) -> list[str]:
    issues: list[str] = []
    rules = QUALITY_PROFILE_RULES.get(profile, QUALITY_PROFILE_RULES[QUALITY_PROFILE_DEFAULT])
    title = (meta.get('title') or '').strip()
    excerpt = (meta.get('excerpt') or '').strip()
    categories = meta.get('categories') or []
    tags = meta.get('tags') or []
    focus_keyphrase = (meta.get('focus_keyphrase') or '').strip()
    meta_description = (meta.get('meta_description') or '').strip()

    if not title:
        issues.append('missing title')
    if rules.get('require_excerpt') and not excerpt:
        issues.append('missing excerpt')
    if not categories:
        issues.append('missing categories')
    min_tags = int(rules.get('min_tags') or 0)
    if len(tags) < min_tags:
        issues.append(f'fewer than {min_tags} tags')
    if rules.get('require_focus_keyphrase') and not focus_keyphrase:
        issues.append('missing focus_keyphrase')
    if rules.get('require_meta_description') and not meta_description:
        issues.append('missing meta_description')
    max_meta_len = int(rules.get('meta_description_max_len') or 0)
    if meta_description and max_meta_len and len(meta_description) > max_meta_len:
        issues.append(f'meta_description > {max_meta_len} chars')
    min_meta_len = int(rules.get('meta_description_min_len') or 0)
    if meta_description and min_meta_len and len(meta_description) < min_meta_len:
        issues.append(f'meta_description < {min_meta_len} chars')
    if (
        rules.get('require_focus_in_meta')
        and focus_keyphrase
        and meta_description
        and focus_keyphrase.lower() not in meta_description.lower()
    ):
        issues.append('meta_description missing focus_keyphrase')
    return issues


def _call_llm_min_cost_with_quality(
    prompt_text: str,
    user_payload: dict[str, Any],
    preferred_model: str,
    default_title: str,
    quality_profile: str
) -> tuple[dict[str, Any], str, list[dict[str, Any]], dict[str, Any], list[str]]:
    ranked = _rank_models_by_est_cost(prompt_text, user_payload, 'metadata', preferred_model)
    candidate_models = [c['model'] for c in ranked]
    if preferred_model not in candidate_models:
        candidate_models.insert(0, preferred_model)
    if not candidate_models:
        candidate_models = [preferred_model]

    attempts: list[dict[str, Any]] = []
    last_json: dict[str, Any] = {}
    last_usage: dict[str, Any] = {}
    last_issues: list[str] = ['no successful LLM output']
    accepted_model = candidate_models[-1]

    for model in candidate_models:
        est_tokens, est_cost = estimate_tokens_and_cost(model, prompt_text, user_payload)
        llm_json, usage_info = _call_llm(prompt_text, user_payload, model, None)
        usage_cost = _usage_cost(model, usage_info, est_tokens, est_cost)
        normalized = normalize_meta(llm_json, default_title)
        issues = _metadata_quality_issues(normalized, quality_profile)
        attempts.append({
            'model': model,
            'usage': usage_cost,
            'issues': issues,
            'output': llm_json,
        })
        if not issues:
            accepted_model = model
            return llm_json, accepted_model, attempts, usage_info, []
        log.warning(f'+  Metadata quality check failed for model={model}: {", ".join(issues)}')
        last_json = llm_json
        last_usage = usage_info
        last_issues = issues

    accepted_model = attempts[-1]['model'] if attempts else preferred_model
    return last_json, accepted_model, attempts, last_usage, last_issues


def normalize_user_meta(meta: dict[str, Any], default_title: str) -> dict[str, Any]:
    title = (meta.get('title') or meta.get('post_title') or '').strip() or default_title
    excerpt = (meta.get('excerpt') or '').strip()
    categories = meta.get('categories') or []
    if isinstance(categories, str):
        categories = [categories]
    categories = _dedup_list([str(c) for c in categories if str(c).strip()])
    categories = [c for c in categories if c.lower() != 'the250']
    categories = _normalize_categories(categories)
    if len(categories) > CATEGORY_LIMIT:
        log.warning(f'Categories over limit ({CATEGORY_LIMIT}); truncating.')
        categories = categories[:CATEGORY_LIMIT]
    tags = meta.get('tags') or []
    if isinstance(tags, str):
        tags = [tags]
    tags = _dedup_list([str(t) for t in tags if str(t).strip()])
    if len(tags) > TAG_LIMIT:
        log.warning(f'Tags over limit ({TAG_LIMIT}); truncating.')
        tags = tags[:TAG_LIMIT]
    focus_keyphrase = (
        (meta.get('focus_keyphrase') or meta.get('yoast_focus_keyphrase') or meta.get('yoast_wpseo_focuskw') or '')
    ).strip()
    meta_description = (
        (meta.get('meta_description') or meta.get('yoast_meta_description') or meta.get('yoast_wpseo_metadesc') or '')
    ).strip()
    if meta_description and len(meta_description) > 160:
        log.warning('Meta description over 160 chars; truncating.')
        meta_description = meta_description[:160].rstrip()
    out = dict(meta)
    out['title'] = title
    out['excerpt'] = excerpt
    out['categories'] = categories
    out['tags'] = tags
    if focus_keyphrase:
        out['focus_keyphrase'] = focus_keyphrase
    if meta_description:
        out['meta_description'] = meta_description
    return out


def fetch_category_context(url: str, headers: dict[str, str]) -> list[str]:
    data = wpu.fetch_wp_endpoint(url, 'categories', headers)
    if not isinstance(data, list):
        return []
    data = sorted(data, key=lambda d: d.get('count', 0), reverse=True)
    names = [d.get('name') or '' for d in data if d.get('name')]
    return [n for n in names if n]


def fetch_tag_context(url: str, headers: dict[str, str]) -> list[str]:
    data = wpu.fetch_wp_endpoint(url, 'tags', headers)
    if not isinstance(data, list):
        return []
    data = sorted(data, key=lambda d: d.get('count', 0), reverse=True)
    names = [d.get('name') or '' for d in data if d.get('name')]
    names = [n for n in names if n]
    return names[:TAG_CONTEXT_LIMIT]


def build_llm_payload(markdown_text: str, categories: list[str], tags: list[str]) -> dict[str, Any]:
    return {
        'markdown': markdown_text,
        'existing_categories': categories,
        'existing_tags': tags,
        'category_limit': CATEGORY_LIMIT,
        'tag_limit': TAG_LIMIT,
        'allowed_categories': ALLOWED_CATEGORIES,
        'notes': {
            'always_add_category': 'The250',
            'categories_limit': CATEGORY_LIMIT,
            'tags_limit': TAG_LIMIT,
            'tags_context_limit': TAG_CONTEXT_LIMIT
        }
    }


def build_suggest_payload(markdown_text: str, categories: list[str], tags: list[str]) -> dict[str, Any]:
    return {
        'markdown': markdown_text,
        'existing_categories': categories,
        'existing_tags': tags,
        'allowed_categories': ALLOWED_CATEGORIES,
        'topic_count': 10
    }


def _write_suggestions_output(path: Path, fmt: str, suggest_output: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    topics = suggest_output.get('topics') or []
    if fmt == 'csv':
        with open(path, 'w', newline='') as file:
            writer = csv.DictWriter(file, fieldnames=['title', 'category'])
            writer.writeheader()
            for item in topics:
                if isinstance(item, dict):
                    writer.writerow({
                        'title': item.get('title', ''),
                        'category': item.get('category', ''),
                    })
                else:
                    writer.writerow({'title': str(item), 'category': ''})
        return path
    with open(path, 'w') as file:
        json.dump(suggest_output, file, indent=2)
    return path


def handle_args():
    wpu.load_dotenv()
    parser = argparse.ArgumentParser(
        description='Agentic WordPress publishing workflow (Google ADK style).'
    )
    parser.add_argument(
        '--content-md',
        nargs='+',
        help='Markdown file(s) to publish (supports globs).'
    )
    parser.add_argument(
        '--url',
        default=DEFAULT_URL,
        help='URL of the WordPress site (default: johnmaconline.com)'
    )
    parser.add_argument(
        '--invoke-llm',
        action='store_true',
        help='Use OpenAI to generate metadata JSON.'
    )
    parser.add_argument(
        '--suggest',
        action='store_true',
        help='Suggest 10 topic ideas for the next article (LLM).'
    )
    parser.add_argument(
        '--meta-json',
        help='Path to existing metadata JSON (skip LLM generation).'
    )
    parser.add_argument(
        '--schedule',
        action=argparse.BooleanOptionalAction,
        default=True,
        help='Schedule posts after metadata generation (default: True).'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Run without publishing to WordPress.'
    )
    parser.add_argument(
        '--preview',
        action='store_true',
        help='Print the final WordPress payload for each post.'
    )
    parser.add_argument(
        '--force',
        action='store_true',
        help='Skip confirmation prompts when updating existing posts.'
    )
    parser.add_argument(
        '--llm-model',
        default=L_DEFAULT_MODEL,
        help=f'OpenAI model to use [default: {L_DEFAULT_MODEL}]'
    )
    parser.add_argument(
        '--publish-date',
        help='Publish date for scheduled posts (MM-DD-YYYY, scheduled at 8:44am Eastern)'
    )
    parser.add_argument(
        '--minimize-cost',
        action='store_true',
        help='Auto-select the lowest estimated cost model for the operation (overrides --llm-model).'
    )
    parser.add_argument(
        '--quality-profile',
        choices=['strict', 'balanced', 'loose'],
        default=QUALITY_PROFILE_DEFAULT,
        help=f'Metadata quality profile for model escalation [default: {QUALITY_PROFILE_DEFAULT}]'
    )
    parser.add_argument(
        '--outdir',
        default=str(OUT_DIR),
        help='Output directory for artifacts [default: ./out]'
    )
    parser.add_argument(
        '--outfile',
        nargs='?',
        const='',
        help='Output file base name for suggestions (defaults to out.<format> if omitted)'
    )
    parser.add_argument(
        '--outfile-format',
        choices=['json', 'csv'],
        default='json',
        help='Output format for suggestions file [default: json]'
    )
    parser.add_argument(
        '--wp-username',
        default=os.getenv('WP_USERNAME'),
        help='WordPress username (or set WP_USERNAME env var)'
    )
    parser.add_argument(
        '--wp-app-password',
        default=os.getenv('WP_APP_PASSWORD'),
        help='WordPress application password (or set WP_APP_PASSWORD env var)'
    )
    parser.add_argument(
        '-v',
        '--verbose',
        action='store_true',
        help='Verbose logging.'
    )
    parser.add_argument(
        '-q',
        '--quiet',
        action='store_true',
        help='Minimal logging.'
    )
    args = parser.parse_args()

    level = logging.DEBUG if args.verbose else (logging.ERROR if args.quiet else logging.INFO)
    _ensure_stdout_logging(level)

    log.info('++++++++++++++++++++++++++++++++++++++++++++++')
    log.info(f'+  {os.path.basename(sys.argv[0])}')
    log.info(f'+  Python Version: {sys.version.split()[0]}')
    log.info(f'+  Today is: {date.today()}')
    log.info(f'+  Target URL: {args.url}')
    log.info(f'+  Content inputs: {args.content_md}')
    log.info(f'+  Invoke LLM: {args.invoke_llm}')
    if args.suggest:
        log.info('+  Suggest enabled (topic ideas only)')
    if args.meta_json:
        log.info(f'+  Meta JSON: {args.meta_json}')
    log.info(f'+  Schedule: {args.schedule}')
    if args.dry_run:
        log.info('+  Dry run enabled (no publish)')
    if args.preview:
        log.info('+  Preview enabled (payload printed)')
    if args.force:
        log.info('+  Force enabled (skip update prompts)')
    log.info(f'+  Requested LLM model: {args.llm_model}')
    if args.publish_date:
        log.info(f'+  Publish date: {args.publish_date} (8:44am Eastern)')
    if args.minimize_cost:
        log.info('+  Minimize cost enabled (auto-select model)')
    log.info(f'+  Quality profile: {args.quality_profile}')
    log.info(f'+  Output directory: {args.outdir}')
    log.info('++++++++++++++++++++++++++++++++++++++++++++++')

    return args


def run_agentic_workflow(args) -> tuple[int, dict[str, Any]]:
    log.debug(f'run_agentic_workflow: args={args}')
    _init_google_client(os.environ.get('GOOGLE_ADK_API_KEY'), args.llm_model)
    if args.meta_json and args.invoke_llm:
        log.info('Meta JSON provided; skipping LLM generation.')
        args.invoke_llm = False
    if args.suggest and args.schedule:
        log.info('Suggestion mode enabled; skipping publish steps.')
        args.schedule = False
    if args.invoke_llm or args.suggest:
        llm_info = _init_llm_backend()
        if llm_info.get('status') != 'ok':
            return 2, {}

    md_list = _expand_md_list(args.content_md) if args.content_md else []
    if args.suggest and args.content_md:
        log.info('Suggest mode uses --url as input; ignoring --content-md.')
        md_list = []
    if not md_list and not args.suggest:
        log.error('No markdown inputs found. Provide --content-md.')
        return 2, {}
    publish_date = None
    if args.publish_date:
        try:
            publish_date = wpu.parse_publish_date(args.publish_date)
        except ValueError as exc:
            log.error(str(exc))
            return 2, {}
        if args.suggest:
            log.info('Publish date provided in suggest mode; ignoring.')
            publish_date = None
        if publish_date and len(md_list) > 1:
            log.error('Using --publish-date with multiple markdown inputs is not supported.')
            return 2, {}

    headers = {
        'User-Agent': 'wp-agent/1.0'
    }
    if args.wp_username and args.wp_app_password:
        headers.update(wpu.build_auth_header(args.wp_username, args.wp_app_password))

    if args.schedule and not (args.wp_username and args.wp_app_password):
        log.error('Missing WP credentials for scheduling.')
        return 2, {}

    prompt_text = _load_prompt(PROMPT_PATH)
    if args.invoke_llm and not prompt_text:
        return 2, {}
    suggest_prompt = _load_prompt(SUGGEST_PROMPT_PATH) if args.suggest else ''
    if args.suggest and not suggest_prompt:
        return 2, {}

    need_context = args.invoke_llm or args.suggest
    existing_categories = fetch_category_context(args.url, headers) if need_context else []
    existing_tags = fetch_tag_context(args.url, headers) if need_context else []

    total_cost = 0.0
    usage_totals = {
        'prompt_tokens': 0,
        'completion_tokens': 0,
        'estimated_input_tokens': 0,
        'estimated_input_cost': 0.0,
        'temperature_fallback_calls': 0,
    }

    if args.meta_json and len(md_list) > 1:
        log.error('Using --meta-json with multiple markdown inputs is not supported.')
        return 2, {}

    inputs = []
    for md_path in md_list:
        path = Path(md_path)
        if not path.exists():
            log.error(f'Markdown file not found: {md_path}')
            continue
        markdown_text = path.read_text(encoding='utf-8')
        title_hint = _extract_h1_title(markdown_text) or path.stem
        slug = _slugify(title_hint, default=_slugify(path.stem))
        inputs.append({
            'source': md_path,
            'text': markdown_text,
            'title_hint': title_hint,
            'slug': slug,
            'base_dir': path.parent,
        })
    if args.suggest:
        url_norm = _normalize_url(args.url)
        if not url_norm:
            log.error('Invalid --url for suggestions.')
            return 2, {}
        try:
            text = _fetch_url_text(url_norm)
        except Exception as exc:
            log.error(f'Failed to fetch URL {url_norm}: {exc}')
            return 2, {}
        title_hint = _extract_title_from_text(text, url_norm)
        slug = _slug_from_url(url_norm)
        inputs.append({
            'source': url_norm,
            'text': text,
            'title_hint': title_hint,
            'slug': slug,
            'base_dir': Path.cwd(),
        })

    for item in inputs:
        markdown_text = item['text']
        title_hint = item['title_hint']
        slug = item['slug']
        out_dir = _ensure_unique_dir(Path(args.outdir) / slug)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / 'input.md').write_text(markdown_text, encoding='utf-8')
        meta_path = out_dir / 'meta.json'

        if args.suggest:
            suggest_payload = build_suggest_payload(markdown_text, existing_categories, existing_tags)
            suggest_input_path = out_dir / 'suggest_input.json'
            suggest_input_path.write_text(json.dumps(suggest_payload, ensure_ascii=False, indent=2), encoding='utf-8')
            log.info(f'Wrote suggestions input => {suggest_input_path}')

            model_for_call = args.llm_model
            if args.minimize_cost:
                model_for_call, choice = _select_min_cost_model(
                    suggest_prompt,
                    suggest_payload,
                    'suggest',
                    args.llm_model
                )
                if choice:
                    log.info(
                        f'+  Minimize cost: operation=suggest, model={model_for_call}, '
                        f'input_tokens={choice["input_tokens"]}, output_tokens={choice["output_tokens"]}, '
                        f'est_total_cost=${choice["total_cost"]:.6f}'
                    )
            est_tokens, est_cost = estimate_tokens_and_cost(model_for_call, suggest_prompt, suggest_payload)
            suggest_output_path = out_dir / 'suggestions.json'
            suggest_json, usage_info = _call_llm(suggest_prompt, suggest_payload, model_for_call, None)
            usage_cost = _usage_cost(model_for_call, usage_info, est_tokens, est_cost)
            if usage_cost.get('total_cost'):
                total_cost += usage_cost.get('total_cost', 0) or 0
            _accumulate_usage_totals(usage_totals, usage_cost)
            suggest_output = {
                'model': model_for_call,
                'usage': usage_cost,
                'topics': suggest_json.get('topics', suggest_json)
            }
            suggest_output_path.write_text(json.dumps(suggest_output, ensure_ascii=False, indent=2), encoding='utf-8')
            log.info(f'Wrote suggestions => {suggest_output_path}')
            print(json.dumps(suggest_output, ensure_ascii=False, indent=2))
            outfile = args.outfile or f"out.{args.outfile_format}"
            out_path = Path(outfile)
            if not out_path.suffix:
                out_path = Path(f"{outfile}.{args.outfile_format}")
            file_path = _write_suggestions_output(out_path, args.outfile_format, suggest_output)
            log.info(f'Wrote suggestions file => {file_path}')
            continue
        if args.suggest:
            suggest_payload = build_suggest_payload(markdown_text, existing_categories, existing_tags)
            suggest_input_path = out_dir / 'suggest_input.json'
            suggest_input_path.write_text(json.dumps(suggest_payload, ensure_ascii=False, indent=2), encoding='utf-8')
            log.info(f'Wrote suggestions input => {suggest_input_path}')

            est_tokens, est_cost = estimate_tokens_and_cost(args.llm_model, suggest_prompt, suggest_payload)
            suggest_output_path = out_dir / 'suggestions.json'
            suggest_json, usage_info = _call_llm(suggest_prompt, suggest_payload, args.llm_model, None)
            usage_cost = _usage_cost(args.llm_model, usage_info, est_tokens, est_cost)
            if usage_cost.get('total_cost'):
                total_cost += usage_cost.get('total_cost', 0) or 0
            _accumulate_usage_totals(usage_totals, usage_cost)
            suggest_output = {
                'model': args.llm_model,
                'usage': usage_cost,
                'topics': suggest_json.get('topics', suggest_json)
            }
            suggest_output_path.write_text(json.dumps(suggest_output, ensure_ascii=False, indent=2), encoding='utf-8')
            log.info(f'Wrote suggestions => {suggest_output_path}')
            print(json.dumps(suggest_output, ensure_ascii=False, indent=2))
            continue
        if args.meta_json:
            meta_src = Path(args.meta_json)
            if not meta_src.exists():
                log.error(f'Metadata file not found: {args.meta_json}')
                continue
            try:
                meta_raw = json.loads(meta_src.read_text(encoding='utf-8'))
            except Exception as exc:
                log.error(f'Failed to read meta JSON: {exc}')
                continue
            if not isinstance(meta_raw, dict):
                log.error('Meta JSON must be an object.')
                continue
            meta = normalize_user_meta(meta_raw, title_hint)
            meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding='utf-8')
            log.info(f'Wrote meta => {meta_path}')
        elif args.invoke_llm:
            llm_payload = build_llm_payload(markdown_text, existing_categories, existing_tags)
            llm_input_path = out_dir / 'llm_input.json'
            llm_input_path.write_text(json.dumps(llm_payload, ensure_ascii=False, indent=2), encoding='utf-8')
            log.info(f'Wrote LLM input => {llm_input_path}')

            model_for_call = args.llm_model
            llm_json: dict[str, Any] = {}
            usage_cost: dict[str, Any] = {}
            if args.minimize_cost:
                ranked = _rank_models_by_est_cost(prompt_text, llm_payload, 'metadata', args.llm_model)
                if ranked:
                    log.info(
                        '+  Minimize cost: operation=metadata, candidates='
                        + ', '.join(f'{c["model"]}(${c["total_cost"]:.6f})' for c in ranked)
                    )
                llm_json, model_for_call, attempts, _, final_issues = _call_llm_min_cost_with_quality(
                    prompt_text,
                    llm_payload,
                    args.llm_model,
                    title_hint,
                    args.quality_profile
                )
                for attempt in attempts:
                    attempt_usage = attempt.get('usage') or {}
                    total_cost += attempt_usage.get('total_cost', 0) or 0
                    _accumulate_usage_totals(usage_totals, attempt_usage)
                usage_cost = attempts[-1].get('usage') if attempts else {}
                if final_issues:
                    log.warning(
                        f'+  Proceeding with model={model_for_call} after exhausting candidates; '
                        f'remaining issues: {", ".join(final_issues)}'
                    )
                else:
                    log.info(f'+  Selected model for metadata: {model_for_call}')
            else:
                est_tokens, est_cost = estimate_tokens_and_cost(model_for_call, prompt_text, llm_payload)
                llm_json, usage_info = _call_llm(prompt_text, llm_payload, model_for_call, None)
                usage_cost = _usage_cost(model_for_call, usage_info, est_tokens, est_cost)
                total_cost += usage_cost.get('total_cost', 0) or 0
                _accumulate_usage_totals(usage_totals, usage_cost)

            llm_output_path = out_dir / 'llm_output.json'
            llm_output = {
                'model': model_for_call,
                'output': llm_json,
                'usage': usage_cost,
            }
            llm_output_path.write_text(json.dumps(llm_output, ensure_ascii=False, indent=2), encoding='utf-8')
            log.info(f'Wrote LLM output => {llm_output_path}')

            meta = normalize_meta(llm_json, title_hint)
            meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding='utf-8')
            log.info(f'Wrote meta => {meta_path}')
        else:
            log.warning('LLM disabled; writing stub meta.')
            if not args.dry_run and args.schedule:
                log.info('Dry-run is required without --invoke-llm. Use --meta-json to schedule without LLM.')
            meta = {
                'title': title_hint,
                'excerpt': '',
                'categories': [],
                'tags': []
            }
            meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding='utf-8')
            log.info(f'Wrote meta => {meta_path}')
            if not args.dry_run and args.schedule:
                continue

        if not args.schedule:
            log.info('Scheduling disabled; skipping publish step.')
            continue

        content_for_publish = wpu.strip_leading_h1(markdown_text)
        base_dir = item['base_dir']
        if args.dry_run:
            log.info('*** this is a dry-run ***')
            payload = wpu.schedule_post_wp_api(
                args.url,
                headers,
                content_for_publish,
                meta,
                dry_run=True,
                preview=args.preview,
                tz_name=wpu.DEFAULT_TIMEZONE,
                force=args.force,
                publish_date=publish_date
            )
            shifted_posts = payload.get('shifted_posts') or []
            if publish_date:
                shifted_posts = list(shifted_posts)
                shifted_posts.append({
                    'operation': 'shift-scheduled',
                    'id': '',
                    'title': meta.get('title') or meta.get('post_title') or '',
                    'from': '(new)',
                    'to': payload.get('scheduled_for') or ''
                })
            if shifted_posts:
                print(wpu.render_ascii_table(shifted_posts))
                shift_path = out_dir / 'shift_report.json'
                shift_path.write_text(json.dumps(shifted_posts, ensure_ascii=False, indent=2), encoding='utf-8')
                log.info(f'Wrote shift report => {shift_path}')
            if payload.get('action') == 'skipped':
                log.info('Update skipped.')
                continue
            if args.preview:
                print(json.dumps(payload.get('payload', {}), indent=2))
            (out_dir / 'final_payload.json').write_text(
                json.dumps(payload.get('payload', {}), ensure_ascii=False, indent=2),
                encoding='utf-8'
            )
        else:
            content_for_publish, uploads = wpu.upload_media_and_replace(content_for_publish, str(base_dir), args.url, headers)
            if uploads:
                log.info(f'Uploaded {len(uploads)} image(s)')
            result = wpu.schedule_post_wp_api(
                args.url,
                headers,
                content_for_publish,
                meta,
                dry_run=False,
                preview=args.preview,
                tz_name=wpu.DEFAULT_TIMEZONE,
                force=args.force,
                publish_date=publish_date
            )
            if result.get('action') == 'skipped':
                log.info('Update skipped.')
                continue
            if args.preview:
                print(json.dumps(result.get('payload', {}), indent=2))
                shifted_posts = result.get('shifted_posts') or []
                if shifted_posts:
                    shift_path = out_dir / 'shift_report.json'
                    shift_path.write_text(json.dumps(shifted_posts, ensure_ascii=False, indent=2), encoding='utf-8')
                    log.info(f'Wrote shift report => {shift_path}')
                post = result.get('post', {})
            else:
                post = result
            (out_dir / 'publish_result.json').write_text(
                json.dumps(post, ensure_ascii=False, indent=2),
                encoding='utf-8'
            )
            log.info(f'Published => {post.get("link") or ""}')

    usage = {
        'prompt_tokens': usage_totals['prompt_tokens'],
        'completion_tokens': usage_totals['completion_tokens'],
        'estimated_input_tokens': usage_totals['estimated_input_tokens'],
        'estimated_input_cost': usage_totals['estimated_input_cost'],
        'temperature_fallback_calls': usage_totals['temperature_fallback_calls'],
        'total_cost': total_cost
    }
    log.info('++++++++++++++++++++++++++++++++++++++++++++++')
    log.info(f'+  LLM totals: prompt_tokens={usage["prompt_tokens"]}, completion_tokens={usage["completion_tokens"]}')
    if usage_totals['estimated_input_tokens']:
        log.info(f'+  Estimated input tokens: {usage_totals["estimated_input_tokens"]}')
        log.info(f'+  Estimated input cost: ${usage_totals["estimated_input_cost"]:.4f}')
    log.info(f'+  Temperature fallback retries: {usage["temperature_fallback_calls"]}')
    log.info(f'+  Estimated LLM cost: ${usage["total_cost"]:.4f}')
    log.info('++++++++++++++++++++++++++++++++++++++++++++++')
    return 0, usage


def main():
    args = handle_args()
    if args.dry_run:
        atexit.register(lambda: log.info(f'NO changes were made to the WP site: {args.url}'))
    rc_code, _usage = run_agentic_workflow(args)
    sys.exit(rc_code)


if __name__ == '__main__':
    main()
