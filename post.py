##########################################################################################
#
# Script name: schedule_post.py
#
# Description: Schedules a markdown blog post on WordPress using the REST API, generates
#              SEO metadata via OpenAI, and posts the article as a Twitter/X thread.
#
# Author: John Macdonald
#
##########################################################################################

import argparse
import logging
import sys
import os
import base64
import json
import requests
import openai
import tweepy
from bs4 import BeautifulSoup
from markdown import markdown
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo
from tools.wp_utilities import markdown_to_gutenberg_blocks

# ****************************************************************************************
# Global data and configuration
# ****************************************************************************************

# WordPress
WP_SITE_URL          = 'https://johnmaconline.com'
POST_TIME_ET         = time(hour=8, minute=44)

# Secrets from environment
WP_USERNAME          = os.getenv("WP_USERNAME")
WP_APP_PASSWORD      = os.getenv("WP_APP_PASSWORD")
OPENAI_API_KEY       = os.getenv("OPENAI_API_KEY")
TWITTER_API_KEY      = os.getenv("TWITTER_API_KEY")
TWITTER_API_SECRET   = os.getenv("TWITTER_API_SECRET")
TWITTER_ACCESS_TOKEN = os.getenv("TWITTER_ACCESS_TOKEN")
TWITTER_ACCESS_SECRET= os.getenv("TWITTER_ACCESS_SECRET")

# Logging config
log = logging.getLogger(os.path.basename(sys.argv[0]))
log.setLevel(logging.DEBUG)

fh = logging.FileHandler('schedule_post.log', mode='w')
fh.setLevel(logging.DEBUG)
formatter = logging.Formatter(
    '%(asctime)-15s [%(funcName)25s:%(lineno)-5s] %(levelname)-8s %(message)s')
fh.setFormatter(formatter)
log.addHandler(fh)

log.debug(f'Global data and configuration for this script...')
log.debug(f'WP_SITE_URL: {WP_SITE_URL}')
log.debug(f'POST_TIME_ET: {POST_TIME_ET}')
log.debug(f'WP_USERNAME: {WP_USERNAME}')
# Twitter username is not directly available from the API key, but if you want to log a Twitter username variable, define and log it here if present.

# ****************************************************************************************
# Exceptions
# ****************************************************************************************

class Error(Exception):
    """Base class for exceptions in this module."""
    pass

class PostError(Error):
    def __init__(self, message):
        self.message = f"Post error: {message}"
        super().__init__(self.message)

# ****************************************************************************************
# Functions
# ****************************************************************************************

def read_markdown_file(filepath):
    try:
        with open(filepath, 'r') as f:
            return f.read()
    except Exception as e:
        raise PostError(f"Failed to read markdown file: {e}")

def markdown_to_text(md_content):
    html = markdown(md_content)
    soup = BeautifulSoup(html, features="html.parser")
    return soup.get_text(separator='\n').strip()

def build_auth_header(username, app_password):
    token = base64.b64encode(
        f"{username}:{app_password}".encode()).decode("utf-8")
    return {
        "Authorization": f"Basic {token}",
        "Content-Type": "application/json"
    }

def local_to_utc(date_obj, local_time):
    eastern = ZoneInfo("America/New_York")
    dt_local = datetime.combine(date_obj, local_time).replace(tzinfo=eastern)
    return dt_local.astimezone(timezone.utc)

def generate_seo_fields(plain_text, api_key, model="gpt-4"):
    openai.api_key = api_key
    prompt = [
        {
            "role": "system",
            "content": (
                "You are an expert in blogging and SEO. "
                "Generate SEO metadata for a blog post."
            )
        },
        {
            "role": "user",
            "content": (
                f"""
Content:
{plain_text}

Return a JSON object with:
- keyphrase (max 5 words)
- meta_description (max 155 characters)
- excerpt (same as meta_description)
"""
            )
        }
    ]

    try:
        response = openai.ChatCompletion.create(
            model=model,
            messages=prompt,
            temperature=0.7
        )
        return json.loads(response['choices'][0]['message']['content'])
    except Exception as e:
        raise PostError(f"SEO generation failed: {e}")

def schedule_post(
        title,
        content_markdown,
        publish_datetime_utc,
        excerpt=None):
    
    post_url = f"{WP_SITE_URL.rstrip('/')}/wp-json/wp/v2/posts"

    payload = {
        "title"    : title,
        "content"  : markdown_to_gutenberg_blocks(content_markdown),
        "status"   : "future",
        "date_gmt" : publish_datetime_utc.strftime("%Y-%m-%dT%H:%M:%S"),
    }

    if excerpt:
        payload["excerpt"] = excerpt

    headers = build_auth_header(WP_USERNAME, WP_APP_PASSWORD)

    log.debug(f"Scheduling post: {title} at {payload['date_gmt']} GMT")

    response = requests.post(post_url, json=payload, headers=headers)

    if response.status_code == 201:
        result = response.json()
        log.info(f"✅ Post scheduled: {result.get('link')}")
        return result.get('link')
    else:
        raise PostError(f"Failed to schedule post: {response.status_code} - {response.text}")

def post_to_twitter_thread(content, title):
    if not all([TWITTER_API_KEY, TWITTER_API_SECRET,
                TWITTER_ACCESS_TOKEN, TWITTER_ACCESS_SECRET]):
        log.warning("Missing Twitter credentials. Skipping Twitter post.")
        return

    try:
        auth = tweepy.OAuth1UserHandler(
            TWITTER_API_KEY,
            TWITTER_API_SECRET,
            TWITTER_ACCESS_TOKEN,
            TWITTER_ACCESS_SECRET
        )
        api = tweepy.API(auth)

        prefix     = f"{title.strip()}\n\n"
        full_text  = prefix + content.strip()
        tweets     = []

        while len(full_text) > 0:
            chunk = full_text[:270]
            if '\n' in chunk:
                chunk = chunk[:chunk.rfind('\n')]
            tweets.append(chunk.strip())
            full_text = full_text[len(chunk):].strip()

        last_tweet = None
        for tweet in tweets:
            if last_tweet:
                last_tweet = api.update_status(
                    status=tweet,
                    in_reply_to_status_id=last_tweet.id,
                    auto_populate_reply_metadata=True)
            else:
                last_tweet = api.update_status(status=tweet)
            log.info(f"Tweeted: {tweet[:50]}...")
    except Exception as e:
        log.error(f"Failed to post thread: {e}")

# ****************************************************************************************
# arguments
# ****************************************************************************************

def handle_args():
    parser = argparse.ArgumentParser(
        description='Schedule a markdown blog post on WordPress and post to Twitter.')
    
    parser.add_argument(
        '--file',
        required=True,
        help='Path to the markdown file.')
    parser.add_argument(
        '--title',
        required=True,
        help='Title of the blog post.')
    parser.add_argument(
        '--date',
        required=True,
        help='Date to publish (YYYY-MM-DD, Eastern Time)')
    parser.add_argument(
        '--model',
        default='gpt-4',
        help='OpenAI model to use [default: gpt-4]')
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

    # Configure stdout logging based on arguments
    ch = logging.StreamHandler(sys.stdout)
    if args.verbose:
        ch.setLevel(logging.DEBUG)
    elif args.quiet:
        ch.setLevel(logging.ERROR)
    else:
        ch.setLevel(logging.INFO)
    ch.setFormatter(formatter)
    log.addHandler(ch)

    log.debug(f'Checking script requirements...')

    if not WP_USERNAME or not WP_APP_PASSWORD or not OPENAI_API_KEY:
        log.error("Missing one or more required environment variables.")
        sys.exit(1)

    log.info('++++++++++++++++++++++++++++++++++++++++++++++')
    log.info(f'+  {os.path.basename(sys.argv[0])}')
    log.info(f'+  Python Version: {sys.version.split()[0]}')
    log.info(f'+  Today is: {datetime.today().date()}')
    log.info(f'+  OpenAI model: {args.model}')
    log.info('++++++++++++++++++++++++++++++++++++++++++++++')

    return args

# ****************************************************************************************
# Main
# ****************************************************************************************

def main():
    args = handle_args()

    try:
        publish_date    = datetime.strptime(args.date, "%Y-%m-%d").date()
        publish_dt_utc  = local_to_utc(publish_date, POST_TIME_ET)
        md_raw          = read_markdown_file(args.file)
        plain_text      = markdown_to_text(md_raw)

        seo             = generate_seo_fields(plain_text, api_key=OPENAI_API_KEY, model=args.model)
        excerpt         = seo.get("meta_description")

        log.info(f"SEO: keyphrase='{seo.get('keyphrase')}', excerpt='{excerpt}'")

        link = schedule_post(
            title                = args.title,
            content_markdown     = md_raw,
            publish_datetime_utc = publish_dt_utc,
            excerpt              = excerpt
        )

        print(f"Post scheduled: {link}")

        post_to_twitter_thread(plain_text, args.title)

    except Exception as e:
        log.error(f"Failed: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()
