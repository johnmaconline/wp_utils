##########################################################################################
#
# Script name: categorize_wp_posts.py
#
# Description: Uses OpenAI to decide whether WordPress posts should be tagged with a
#              specific category, then updates posts via the WordPress REST API.
#              Supports dry-run mode and additive category updates.
#
##########################################################################################

import argparse
import base64
import csv
import json
import logging
import os
import sys
import time
from datetime import date
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from openai import OpenAI

# ****************************************************************************************
# Global data and configuration
# ****************************************************************************************

WP_API_MAX_PER_PAGE = 100
DEFAULT_USER_AGENT = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
    'AppleWebKit/537.36 (KHTML, like Gecko) '
    'Chrome/58.0.3029.110 Safari/537.3'
)

# Logging config
log = logging.getLogger(os.path.basename(sys.argv[0]))
log.setLevel(logging.DEBUG)

fh = logging.FileHandler('categorize_wp_posts.log', mode='w')
fh.setLevel(logging.DEBUG)
formatter = logging.Formatter(
    '%(asctime)-15s [%(funcName)25s:%(lineno)-5s] %(levelname)-8s %(message)s')
fh.setFormatter(formatter)
log.addHandler(fh)

# ****************************************************************************************
# Exceptions
# ****************************************************************************************

class Error(Exception):
    """Base class for exceptions in this module."""
    pass

class ConfigError(Error):
    def __init__(self, message):
        self.message = f"Config error: {message}"
        super().__init__(self.message)

class APIError(Error):
    def __init__(self, message):
        self.message = f"API error: {message}"
        super().__init__(self.message)

# ****************************************************************************************
# Helpers
# ****************************************************************************************

def build_wp_api_base(url):
    url = (url or '').strip()
    if not url:
        return ''

    normalized = url.rstrip('/')
    if '/wp-json/' in normalized:
        base = normalized.split('/wp-json/')[0]
        return base.rstrip('/')

    parsed = urlparse(normalized)
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}"

    return normalized


def build_wp_endpoints(url):
    base = build_wp_api_base(url)
    if not base:
        return '', ''
    posts_url = base.rstrip('/') + '/wp-json/wp/v2/posts'
    categories_url = base.rstrip('/') + '/wp-json/wp/v2/categories'
    return posts_url, categories_url


def build_auth_header(username, app_password):
    token = base64.b64encode(
        f"{username}:{app_password}".encode()).decode("utf-8")
    return {"Authorization": f"Basic {token}"}


def html_to_text(html_content):
    soup = BeautifulSoup(html_content or "", 'html.parser')
    return soup.get_text(separator='\n').strip()


def truncate_text(text, max_chars):
    if not max_chars or max_chars <= 0:
        return text
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rsplit(' ', 1)[0] + '...'


def safe_json_loads(text):
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None

# ****************************************************************************************
# WordPress API
# ****************************************************************************************

def fetch_wp_page(url, session, headers, params):
    response = session.get(url, headers=headers, params=params)
    if response.status_code >= 400:
        raise APIError(f"HTTP {response.status_code}: {response.text}")
    return response


def fetch_all_categories(categories_url, session, headers):
    categories = {}
    id_to_name = {}
    page = 1
    while True:
        params = {
            'per_page': WP_API_MAX_PER_PAGE,
            'page': page,
            'hide_empty': False
        }
        response = fetch_wp_page(categories_url, session, headers, params)
        data = response.json()
        for item in data:
            name = (item.get('name') or '').strip()
            if name:
                cat_id = item.get('id')
                categories[name.lower()] = cat_id
                if cat_id is not None:
                    id_to_name[cat_id] = name
        total_pages = int(response.headers.get('X-WP-TotalPages', 1))
        if page >= total_pages:
            break
        page += 1
    return categories, id_to_name


def fetch_posts(posts_url, session, headers, limit=None, category_id=None):
    posts = []
    page = 1
    while True:
        params = {
            'per_page': WP_API_MAX_PER_PAGE,
            'page': page,
            'orderby': 'date',
            'order': 'desc',
            'status': 'publish',
            '_fields': 'id,title,content,excerpt,categories,link'
        }
        if category_id:
            params['categories'] = category_id
        response = fetch_wp_page(posts_url, session, headers, params)
        data = response.json()
        posts.extend(data)
        if limit and len(posts) >= limit:
            return posts[:limit]
        total_pages = int(response.headers.get('X-WP-TotalPages', 1))
        if page >= total_pages:
            break
        page += 1
    return posts


def update_post_categories(posts_url, post_id, categories, session, headers):
    url = posts_url.rstrip('/') + f"/{post_id}"
    payload = {'categories': categories}
    response = session.post(url, headers=headers, json=payload)
    if response.status_code >= 400:
        raise APIError(f"Failed to update post {post_id}: {response.status_code} {response.text}")
    return response.json()

# ****************************************************************************************
# OpenAI classification
# ****************************************************************************************

def classify_post(client, model, target_category, title, excerpt, content, max_chars):
    content_text = html_to_text(content)
    excerpt_text = html_to_text(excerpt)

    trimmed_content = truncate_text(content_text, max_chars)
    trimmed_excerpt = truncate_text(excerpt_text, max_chars)

    prompt = (
        "You are a careful content classifier. "
        "Decide whether the blog post should be tagged with the category named below. "
        "Return a JSON object with: add (true/false), confidence (0-1), reason (short). "
        "Only answer with JSON."
    )

    user_text = (
        f"Category: {target_category}\n"
        f"Title: {title}\n"
        f"Excerpt: {trimmed_excerpt}\n"
        f"Content: {trimmed_content}\n"
    )

    response = client.responses.create(
        model=model,
        input=[
            {
                "role": "system",
                "content": [{"type": "input_text", "text": prompt}]
            },
            {
                "role": "user",
                "content": [{"type": "input_text", "text": user_text}]
            }
        ],
        temperature=0,
        max_output_tokens=256
    )

    output_text = (response.output_text or '').strip()
    result = safe_json_loads(output_text)
    if not result:
        raise APIError(f"Invalid JSON from model: {output_text}")
    return result

# ****************************************************************************************
# CLI
# ****************************************************************************************

def handle_args():
    parser = argparse.ArgumentParser(
        description='Classify WordPress posts with OpenAI and add a category via WP REST API.'
    )
    parser.add_argument(
        '--url',
        required=True,
        help='Site URL or WP API URL (e.g. https://example.com or https://example.com/wp-json/wp/v2/posts)')
    parser.add_argument(
        '--target-category',
        default='AI',
        help='Category name to add when a post matches [default: AI]')
    parser.add_argument(
        '--only-category',
        help='Only process posts that already have this category (by name)')
    parser.add_argument(
        '--model',
        default='gpt-4.1',
        help='OpenAI model to use [default: gpt-4.1]')
    parser.add_argument(
        '--limit',
        type=int,
        help='Max number of posts to process')
    parser.add_argument(
        '--max-chars',
        type=int,
        default=8000,
        help='Max characters of content/excerpt to send to the model [default: 8000]')
    parser.add_argument(
        '--min-confidence',
        type=float,
        default=0.8,
        help='Minimum confidence required to add category [default: 0.8]')
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Do not update posts; only log what would change')
    parser.add_argument(
        '--sleep',
        type=float,
        default=0.4,
        help='Seconds to sleep between OpenAI calls [default: 0.4]')
    parser.add_argument(
        '--report',
        help='Optional path to write a JSONL report')
    parser.add_argument(
        '--updated-csv',
        default='updated_posts.csv',
        help='Path to write CSV of updated post titles [default: updated_posts.csv]')
    parser.add_argument(
        '--confidence-column',
        action='store_true',
        help='Include model confidence in the updated CSV')
    parser.add_argument(
        '--overwrite-csv',
        action='store_true',
        help='Overwrite updated CSV instead of appending')
    parser.add_argument(
        '--wp-username',
        default=os.getenv('WP_USERNAME'),
        help='WordPress username (or set WP_USERNAME env var)')
    parser.add_argument(
        '--wp-app-password',
        default=os.getenv('WP_APP_PASSWORD'),
        help='WordPress application password (or set WP_APP_PASSWORD env var)')
    parser.add_argument(
        '--openai-api-key',
        default=os.getenv('OPENAI_API_KEY'),
        help='OpenAI API key (or set OPENAI_API_KEY env var)')
    parser.add_argument(
        '-v',
        '--verbose',
        action='store_true',
        help='Enable verbose output to stdout.')
    parser.add_argument(
        '-q',
        '--quiet',
        action='store_true',
        help='Minimal stdout.')
    args = parser.parse_args()

    # Configure stdout logging
    ch = logging.StreamHandler(sys.stdout)
    if args.verbose:
        ch.setLevel(logging.DEBUG)
    elif args.quiet:
        ch.setLevel(logging.ERROR)
    else:
        ch.setLevel(logging.INFO)
    ch.setFormatter(formatter)
    log.addHandler(ch)

    return args

# ****************************************************************************************
# Main
# ****************************************************************************************

def main():
    args = handle_args()

    if not args.openai_api_key:
        raise ConfigError("Missing OPENAI_API_KEY (env var or --openai-api-key)")

    posts_url, categories_url = build_wp_endpoints(args.url)
    if not posts_url or not categories_url:
        raise ConfigError("Invalid URL. Please provide a site URL or WP API URL.")

    log.info('++++++++++++++++++++++++++++++++++++++++++++++')
    log.info(f'+  {os.path.basename(sys.argv[0])}')
    log.info(f'+  Python Version: {sys.version.split()[0]}')
    log.info(f'+  Today is: {date.today()}')
    log.info(f'+  Target URL: {args.url}')
    log.info(f'+  Posts endpoint: {posts_url}')
    log.info(f'+  Target category: {args.target_category}')
    if args.only_category:
        log.info(f'+  Only process category: {args.only_category}')
    log.info(f'+  Model: {args.model}')
    log.info(f'+  Dry run: {args.dry_run}')
    if args.limit:
        log.info(f'+  Post limit: {args.limit}')
    log.info('++++++++++++++++++++++++++++++++++++++++++++++')

    session = requests.Session()
    headers = {'User-Agent': DEFAULT_USER_AGENT}

    # Add WP auth if provided (required for updates)
    if args.wp_username and args.wp_app_password:
        headers.update(build_auth_header(args.wp_username, args.wp_app_password))
    elif not args.dry_run:
        raise ConfigError("Missing WP credentials. Provide WP_USERNAME/WP_APP_PASSWORD or --wp-username/--wp-app-password.")

    client = OpenAI(api_key=args.openai_api_key)

    log.info('Fetching categories...')
    categories, categories_by_id = fetch_all_categories(categories_url, session, headers)
    target_key = args.target_category.strip().lower()
    if target_key not in categories:
        raise ConfigError(f"Target category '{args.target_category}' not found in WordPress.")
    target_category_id = categories[target_key]
    only_category_id = None
    if args.only_category:
        only_key = args.only_category.strip().lower()
        if only_key not in categories:
            raise ConfigError(f"Only-category '{args.only_category}' not found in WordPress.")
        only_category_id = categories[only_key]

    log.info('Fetching posts...')
    posts = fetch_posts(posts_url, session, headers, limit=args.limit, category_id=only_category_id)
    log.info(f'Fetched {len(posts)} posts')

    report_fh = None
    if args.report:
        report_fh = open(args.report, 'w')

    updated = 0
    skipped = 0
    updated_posts = []
    for post in posts:
        post_id = post.get('id')
        title_html = (post.get('title') or {}).get('rendered', '')
        title = BeautifulSoup(title_html, 'html.parser').get_text().strip()
        excerpt = (post.get('excerpt') or {}).get('rendered', '')
        content = (post.get('content') or {}).get('rendered', '')
        existing_categories = post.get('categories') or []

        if target_category_id in existing_categories:
            log.info(f"[{post_id}] already has category '{args.target_category}', skipping")
            skipped += 1
            continue

        try:
            result = classify_post(
                client,
                args.model,
                args.target_category,
                title,
                excerpt,
                content,
                args.max_chars
            )
        except Exception as e:
            log.error(f"[{post_id}] classification failed: {e}")
            skipped += 1
            continue

        add_category = bool(result.get('add'))
        confidence_raw = result.get('confidence')
        try:
            confidence = float(confidence_raw) if confidence_raw is not None else 0.0
        except (TypeError, ValueError):
            confidence = 0.0
            log.warning(f"[{post_id}] invalid confidence value '{confidence_raw}', treating as 0.0")
        reason = result.get('reason')

        if add_category and confidence >= args.min_confidence:
            new_categories = list(existing_categories) + [target_category_id]
            log.info(f"[{post_id}] add '{args.target_category}' (confidence={confidence}): {reason}")
            existing_names = [categories_by_id.get(cid, str(cid)) for cid in existing_categories]
            new_names = [categories_by_id.get(cid, str(cid)) for cid in new_categories]
            if not args.dry_run:
                try:
                    update_post_categories(posts_url, post_id, new_categories, session, headers)
                    updated += 1
                    updated_posts.append({
                        'id': post_id,
                        'title': title,
                        'link': post.get('link'),
                        'target_category': args.target_category,
                        'categories_before': ';'.join(existing_names),
                        'categories_after': ';'.join(new_names),
                        'confidence': confidence,
                        'dry_run': False
                    })
                except Exception as e:
                    log.error(f"[{post_id}] update failed: {e}")
            else:
                updated += 1
                updated_posts.append({
                    'id': post_id,
                    'title': title,
                    'link': post.get('link'),
                    'target_category': args.target_category,
                    'categories_before': ';'.join(existing_names),
                    'categories_after': ';'.join(new_names),
                    'confidence': confidence,
                    'dry_run': True
                })
        else:
            if add_category and confidence < args.min_confidence:
                log.info(
                    f"[{post_id}] no change (confidence={confidence} below min {args.min_confidence}): {reason}"
                )
            else:
                log.info(f"[{post_id}] no change (confidence={confidence}): {reason}")
            skipped += 1

        if report_fh:
            report_fh.write(json.dumps({
                'id': post_id,
                'title': title,
                'link': post.get('link'),
                'add_category': add_category,
                'confidence': confidence,
                'reason': reason,
                'dry_run': args.dry_run
            }) + '\n')

        time.sleep(args.sleep)

    if report_fh:
        report_fh.close()

    if updated_posts:
        write_mode = 'w' if args.overwrite_csv else 'a'
        file_exists = os.path.exists(args.updated_csv)
        with open(args.updated_csv, write_mode, newline='') as csvfile:
            fieldnames = [
                'id', 'title', 'link', 'target_category',
                'categories_before', 'categories_after', 'dry_run'
            ]
            if args.confidence_column:
                fieldnames.append('confidence')
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames, extrasaction='ignore')
            if args.overwrite_csv or not file_exists or os.path.getsize(args.updated_csv) == 0:
                writer.writeheader()
            writer.writerows(updated_posts)
        log.info(f"Wrote updated posts CSV: {args.updated_csv}")

    log.info(f"Done. Updated: {updated}, Skipped: {skipped}")

if __name__ == '__main__':
    main()
