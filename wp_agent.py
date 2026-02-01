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
import json
import logging
import os
import re
import sys
import time
from datetime import date
from pathlib import Path
from typing import Any
from concurrent.futures import ThreadPoolExecutor, TimeoutError

from openai import OpenAI

from tools import wp_utilities as wpu

# ========================================================================================
# GLOBAL DATA
# ========================================================================================
OUT_DIR = Path('./out')
L_DEFAULT_MODEL = os.environ.get('WP_AGENT_LLM_MODEL', 'gpt-5.1')
DEFAULT_URL = 'johnmaconline.com'
PROMPT_PATH = Path('wp_meta_prompt.md')
CATEGORY_LIMIT = 4
TAG_LIMIT = 8
TAG_CONTEXT_LIMIT = 50
ALLOWED_CATEGORIES = ['AI', 'Leadership', 'Technology', 'Human']

# Simple price table (USD per 1M tokens)
PRICE_TABLE_DEFAULT = {
    'gpt-5.1': {'in_per_m': 2.50, 'out_per_m': 10.00},
    'gpt-4o': {'in_per_m': 2.50, 'out_per_m': 10.00},
    'gpt-4o-mini': {'in_per_m': 0.15, 'out_per_m': 0.60},
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


def estimate_tokens_and_cost(model: str, prompt_text: str, user_payload: dict[str, Any]) -> tuple[int, float]:
    try:
        import tiktoken  # type: ignore
    except Exception:
        tiktoken = None

    if not tiktoken:
        user_str = json.dumps(user_payload, ensure_ascii=False)
        total_in = max(1, int((len(prompt_text or '') + len(user_str)) / 4))
        price = PRICE_TABLE_DEFAULT.get(model) or {}
        in_rate = price.get('in_per_m', 0)
        cost = (total_in / 1_000_000) * in_rate if in_rate else 0
        return total_in, cost

    try:
        enc = tiktoken.encoding_for_model(model)
    except Exception:
        enc = tiktoken.get_encoding('cl100k_base')
    prompt_tokens = len(enc.encode(prompt_text or ''))
    user_str = json.dumps(user_payload, ensure_ascii=False)
    user_tokens = len(enc.encode(user_str))
    total_in = prompt_tokens + user_tokens
    price = PRICE_TABLE_DEFAULT.get(model) or {}
    in_rate = price.get('in_per_m', 0)
    cost = (total_in / 1_000_000) * in_rate if in_rate else 0
    return total_in, cost


def _call_llm(prompt_text: str, user_payload: dict[str, Any], model: str, out_path: Path | None) -> tuple[dict[str, Any], dict[str, Any]]:
    client = OpenAI()
    est_tokens, est_cost = estimate_tokens_and_cost(model, prompt_text, user_payload)
    log.debug(f'_call_llm: model={model}, est_tokens={est_tokens}, est_cost=${est_cost:.4f}')
    messages = [
        {'role': 'system', 'content': prompt_text},
        {'role': 'user', 'content': json.dumps(user_payload, ensure_ascii=False)},
    ]
    try:
        start = time.time()
        with ThreadPoolExecutor(max_workers=1) as ex:
            future = ex.submit(
                client.chat.completions.create,
                model=model,
                messages=messages,
                temperature=0,
                timeout=60,
            )
            while True:
                try:
                    resp = future.result(timeout=10)
                    break
                except TimeoutError:
                    elapsed = int(time.time() - start)
                    log.info(f'Still waiting on LLM return... {elapsed} seconds total')
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
        }
        return parsed, usage_info
    except Exception as e:
        log.error(f'LLM call failed: {e}')
        return {}, {}


def _usage_cost(model: str, usage_info: dict[str, Any], est_tokens: int, est_cost: float) -> dict[str, Any]:
    price = PRICE_TABLE_DEFAULT.get(model) or {}
    in_rate = price.get('in_per_m', 0)
    out_rate = price.get('out_per_m', 0)
    ptok = usage_info.get('prompt_tokens') or usage_info.get('input_tokens')
    ctok = usage_info.get('completion_tokens') or usage_info.get('output_tokens')
    if ptok is None and ctok is None:
        return {
            'prompt_tokens': None,
            'completion_tokens': None,
            'estimated_input_tokens': est_tokens,
            'estimated_input_cost': est_cost,
            'total_cost': est_cost
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
        'total_cost': in_cost + out_cost
    }


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


def handle_args():
    wpu.load_dotenv()
    parser = argparse.ArgumentParser(
        description='Agentic WordPress publishing workflow (Google ADK style).'
    )
    parser.add_argument(
        '--content-md',
        nargs='+',
        required=True,
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
        '--outdir',
        default=str(OUT_DIR),
        help='Output directory for artifacts [default: ./out]'
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
    if args.meta_json:
        log.info(f'+  Meta JSON: {args.meta_json}')
    log.info(f'+  Schedule: {args.schedule}')
    if args.dry_run:
        log.info('+  Dry run enabled (no publish)')
    if args.preview:
        log.info('+  Preview enabled (payload printed)')
    if args.force:
        log.info('+  Force enabled (skip update prompts)')
    log.info(f'+  Output directory: {args.outdir}')
    log.info('++++++++++++++++++++++++++++++++++++++++++++++')

    return args


def run_agentic_workflow(args) -> tuple[int, dict[str, Any]]:
    log.debug(f'run_agentic_workflow: args={args}')
    _init_google_client(os.environ.get('GOOGLE_ADK_API_KEY'), args.llm_model)
    if args.meta_json and args.invoke_llm:
        log.info('Meta JSON provided; skipping LLM generation.')
        args.invoke_llm = False
    if args.invoke_llm:
        llm_info = _init_llm_backend()
        if llm_info.get('status') != 'ok':
            return 2, {}

    md_list = _expand_md_list(args.content_md)
    if not md_list:
        log.error('No markdown inputs found.')
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

    existing_categories = fetch_category_context(args.url, headers) if args.invoke_llm else []
    existing_tags = fetch_tag_context(args.url, headers) if args.invoke_llm else []

    total_cost = 0.0
    usage_totals = {
        'prompt_tokens': 0,
        'completion_tokens': 0,
        'estimated_input_tokens': 0,
        'estimated_input_cost': 0.0
    }

    if args.meta_json and len(md_list) > 1:
        log.error('Using --meta-json with multiple markdown inputs is not supported.')
        return 2, {}

    for md_path in md_list:
        path = Path(md_path)
        if not path.exists():
            log.error(f'Markdown file not found: {md_path}')
            continue
        markdown_text = path.read_text(encoding='utf-8')
        title_hint = _extract_h1_title(markdown_text) or path.stem
        slug = _slugify(title_hint, default=_slugify(path.stem))
        out_dir = _ensure_unique_dir(Path(args.outdir) / slug)
        out_dir.mkdir(parents=True, exist_ok=True)

        (out_dir / 'input.md').write_text(markdown_text, encoding='utf-8')
        meta_path = out_dir / 'meta.json'

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

            est_tokens, est_cost = estimate_tokens_and_cost(args.llm_model, prompt_text, llm_payload)
            llm_output_path = out_dir / 'llm_output.json'
            llm_json, usage_info = _call_llm(prompt_text, llm_payload, args.llm_model, None)
            usage_cost = _usage_cost(args.llm_model, usage_info, est_tokens, est_cost)

            llm_output = {
                'model': args.llm_model,
                'output': llm_json,
                'usage': usage_cost,
            }
            llm_output_path.write_text(json.dumps(llm_output, ensure_ascii=False, indent=2), encoding='utf-8')
            log.info(f'Wrote LLM output => {llm_output_path}')

            total_cost += usage_cost.get('total_cost', 0) or 0
            if usage_cost.get('prompt_tokens') is not None:
                usage_totals['prompt_tokens'] += usage_cost.get('prompt_tokens') or 0
            if usage_cost.get('completion_tokens') is not None:
                usage_totals['completion_tokens'] += usage_cost.get('completion_tokens') or 0
            if usage_cost.get('estimated_input_tokens') is not None:
                usage_totals['estimated_input_tokens'] += usage_cost.get('estimated_input_tokens') or 0
            if usage_cost.get('estimated_input_cost') is not None:
                usage_totals['estimated_input_cost'] += usage_cost.get('estimated_input_cost') or 0.0

            meta = normalize_meta(llm_json, title_hint)
            meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding='utf-8')
            log.info(f'Wrote meta => {meta_path}')
        else:
            log.warning('LLM disabled; writing stub meta and skipping publish.')
            log.info('Fill in meta.json (title, excerpt, categories, tags) and rerun with --invoke-llm or --schedule.')
            meta = {
                'title': title_hint,
                'excerpt': '',
                'categories': [],
                'tags': []
            }
            meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding='utf-8')
            log.info(f'Wrote meta => {meta_path}')
            continue

        if not args.schedule:
            log.info('Scheduling disabled; skipping publish step.')
            continue

        content_for_publish = wpu.strip_leading_h1(markdown_text)
        base_dir = path.parent
        if args.dry_run:
            payload = wpu.schedule_post_wp_api(
                args.url,
                headers,
                content_for_publish,
                meta,
                dry_run=True,
                preview=args.preview,
                tz_name=wpu.DEFAULT_TIMEZONE,
                force=args.force
            )
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
                force=args.force
            )
            if result.get('action') == 'skipped':
                log.info('Update skipped.')
                continue
            if args.preview:
                print(json.dumps(result.get('payload', {}), indent=2))
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
        'total_cost': total_cost
    }
    log.info('++++++++++++++++++++++++++++++++++++++++++++++')
    log.info(f'+  LLM totals: prompt_tokens={usage["prompt_tokens"]}, completion_tokens={usage["completion_tokens"]}')
    if usage_totals['estimated_input_tokens']:
        log.info(f'+  Estimated input tokens: {usage_totals["estimated_input_tokens"]}')
        log.info(f'+  Estimated input cost: ${usage_totals["estimated_input_cost"]:.4f}')
    log.info(f'+  Estimated LLM cost: ${usage["total_cost"]:.4f}')
    log.info('++++++++++++++++++++++++++++++++++++++++++++++')
    return 0, usage


def main():
    args = handle_args()
    rc_code, _usage = run_agentic_workflow(args)
    sys.exit(rc_code)


if __name__ == '__main__':
    main()
