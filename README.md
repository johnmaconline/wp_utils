# wp_utils

Utilities for working with a WordPress blog:

- Download posts via the WordPress REST API and concatenate them.
- Classify posts with OpenAI and add a category (additive).
- Schedule posts to WordPress and optionally post to Twitter/X.
- CI post‑processing utilities (copied from `jobber.ai/ci`).

## Scripts

### `wp_utilities.py`
Downloads posts via the WP REST API, concatenates files, and can list plugins.

Args:
- `--url` URL of the site or WP API root (default: `johnmaconline.com`, scheme optional)
- `--number` Number of posts to download
- `--outdir` Directory to save posts (default: `posts`)
- `--indir` One or more input dirs for concat (space‑separated)
- `--outfile` Output file base name (defaults to `out.<format>` if omitted)
- `--outfile-format` Results output format: `csv` or `json` (default: `csv`)

Results from `--get-plugins`, `--get-posts`, or any other `--get-*` operation are written to a file and also printed to stdout as an ASCII table. If `--outfile` is omitted, the default is `out.<format>`.
- `--format` Output formats for downloaded posts (supports multiple) [default: txt]
- `--date` Date range filter for posts: today, week, month, year, all, or MM-DD-YYYY:MM-DD-YYYY (overrides --number)
- `--post-state` Post state to fetch: published, scheduled, or draft [default: published]
- `--with-meta` Save per-post metadata JSON alongside downloaded posts
- `--get-posts` Download posts
- `--schedule-post` Schedule a post using markdown content + metadata JSON
- `--content-md` Markdown file path for `--schedule-post` (use `-` for stdin)
- `--meta-json` Metadata JSON file path for `--schedule-post`
- `--publish-date` Publish date (MM-DD-YYYY, scheduled at 8:44am Eastern; shifts existing scheduled posts by +1 day starting that date)
- `--dry-run` Show planned changes without creating a post (used with `--schedule-post`)
- `--preview` Print the final scheduled post payload (used with `--schedule-post`)
- `--export-site` Export site data: all, all-no-media, or comma-separated list (posts,pages,media,comments,users,categories,tags,taxonomies,types,statuses,settings,menus,plugins)
- `--incremental` For `--export-site`, append only new items to JSONL outputs
- `--list-posts` Print posts via WP REST API
- `--concat` Concatenate files
- `--get-plugins` Print plugin list via WP REST API (requires credentials)
- `--get-pages` Print pages via WP REST API
- `--get-categories` Print categories via WP REST API
- `--get-tags` Print tags via WP REST API
- `--get-users` Print users via WP REST API (requires credentials for permissions/created date)
- `--get-user-me` Print current user via WP REST API (requires credentials)
- `--get-media` Print media items via WP REST API
- `--get-comments` Print comments via WP REST API
- `--get-types` Print content types via WP REST API
- `--get-statuses` Print post statuses via WP REST API
- `--get-taxonomies` Print taxonomies via WP REST API
- `--get-settings` Print site settings via WP REST API (requires credentials)
- `--get-themes` Print themes via WP REST API (requires credentials)
- `--wp-username` WordPress username (or env `WP_USERNAME`)
- `--wp-app-password` WordPress application password (or env `WP_APP_PASSWORD`)
- `-v/--verbose` Verbose logging
- `-q/--quiet` Minimal stdout

Examples:
- Download all posts as txt:
  ```bash
  python3 wp_utilities.py --get-posts --url https://johnmaconline.com --outdir posts --format txt
  ```
- Download and concatenate:
  ```bash
  python3 wp_utilities.py --get-posts --url https://johnmaconline.com --outdir posts --format txt --concat --outfile all_files
  ```
- Download as txt + md + word and include metadata:
  ```bash
  python3 wp_utilities.py --get-posts --url https://johnmaconline.com --outdir posts --format txt md word --with-meta
  ```
- Download posts from the last week:
  ```bash
  python3 wp_utilities.py --get-posts --url https://johnmaconline.com --date week --format md
  ```
- List posts (no downloads):
  ```bash
  python3 wp_utilities.py --list-posts --url https://johnmaconline.com
  ```
- Get plugins (requires credentials) and save results:
  ```bash
  export WP_USERNAME="your_wp_user"
  export WP_APP_PASSWORD="xxxx xxxx xxxx xxxx xxxx"
  python3 wp_utilities.py --get-plugins --url https://johnmaconline.com --outfile plugins --outfile-format csv
  ```
  This writes `plugins.csv` and also prints to stdout.

- Get categories (public) and save JSON:
  ```bash
  python3 wp_utilities.py --get-categories --url https://johnmaconline.com --outfile categories --outfile-format json
  ```
- Export a full site backup (content + metadata + media binaries):
  ```bash
  python3 wp_utilities.py --export-site all --url https://johnmaconline.com
  ```
  Note: exporting plugins/users/settings may require WP credentials.
- Schedule a post from markdown + metadata:
  ```bash
  export WP_USERNAME="your_wp_user"
  export WP_APP_PASSWORD="xxxx xxxx xxxx xxxx xxxx"
  python3 wp_utilities.py --schedule-post --url https://johnmaconline.com \
    --content-md ./draft.md \
    --meta-json ./meta.json \
    --dry-run
  ```
  Preview payload (no post created):
  ```bash
  python3 wp_utilities.py --schedule-post --url https://johnmaconline.com \
    --content-md ./draft.md \
    --meta-json ./meta.json \
    --dry-run \
    --preview
  ```
  Notes:
  - `The250` is always added automatically; missing categories are created automatically.
  - Tags are optional and resolved by name; missing tags are created automatically.
  - If `slug` is omitted, it is auto-generated from the title (lowercase, words joined by `-`).
  - A leading `# H1` at the top of the markdown is stripped to avoid duplicate titles.
  - Yoast fields supported: `focus_keyphrase`, `meta_description`.
  Metadata JSON format:
  ```json
  {
    "title": "My Post Title",
    "categories": ["AI"],
    "tags": ["workflow", "automation"],
    "excerpt": "Short summary shown in listings",
    "slug": "my-post-title",
    "focus_keyphrase": "ai teaching intuition",
    "meta_description": "AI can teach information, but intuition still requires years of repetition."
  }
  ```
- Export everything but media binaries (metadata only):
  ```bash
  python3 wp_utilities.py --export-site all-no-media --url https://johnmaconline.com
  ```

### `wp_agent.py`
Agentic workflow (Google ADK style) for WordPress publishing. Uses OpenAI to generate metadata JSON
and then schedules the post using the same wp_utilities toolset.
Prompt template: `wp_meta_prompt.md`
Suggestion prompt: `wp_suggest_prompt.md`

Prereqs:
```bash
export OPENAI_API_KEY="your-openai-key"
export GOOGLE_ADK_API_KEY="your-google-key"  # stubbed client, used for parity with jobber.ai
export WP_USERNAME="your_wp_user"
export WP_APP_PASSWORD="xxxx xxxx xxxx xxxx xxxx"
```
Or set these in a `.env` file (required). Example:
```bash
OPENAI_API_KEY=your-openai-key
GOOGLE_ADK_API_KEY=your-google-key
WP_USERNAME=your_wp_user
WP_APP_PASSWORD=xxxx xxxx xxxx xxxx xxxx
```

Args:
- `--content-md` Markdown file(s) to publish (accepts globs and lists)
- `--invoke-llm` Call OpenAI to generate metadata JSON
- `--suggest` Suggest 10 topic ideas for the next article (LLM). Uses `--url` as input.
- `--meta-json` Use existing metadata JSON (skip LLM generation)
- `--schedule/--no-schedule` Schedule posts after metadata (default: true)
- `--dry-run` No publish
- `--preview` Print the final WordPress payload
- `--force` Skip confirmation prompts when updating existing posts
- `--llm-model` OpenAI model (default from `WP_AGENT_LLM_MODEL` or `gpt-5.1`)
- `--publish-date` Publish date (MM-DD-YYYY, scheduled at 8:44am Eastern; shifts existing scheduled posts by +1 day starting that date)
- `--minimize-cost` Auto-select the lowest estimated cost model for the operation (overrides `--llm-model`)
- `--quality-profile` Metadata quality profile for escalation: `strict`, `balanced`, `loose` (default: `balanced`)
- `--outdir` Output dir for artifacts (default: `./out`)
- `--url` Target site (default: `johnmaconline.com`)
- `--outfile` Output file base name for suggestions (defaults to out.<format> if omitted)
- `--outfile-format` Output format for suggestions file: `json` or `csv` (default: `json`)

Pricing estimates (used by `wp_agent.py` and `categorize_wp_posts.py` for cost logging, USD per 1M tokens, input/output; OpenAI API pricing verified on 2026-02-10):
- `gpt-5-nano`: $0.05 / $0.40
- `gpt-5-mini`: $0.25 / $2.00
- `gpt-5`: $1.25 / $10.00
- `gpt-5-chat-latest`: $1.25 / $10.00
- `gpt-5.2`: $1.75 / $14.00
- `gpt-5.2-chat-latest`: $1.75 / $14.00
- `gpt-5.1`: $1.25 / $10.00
- `gpt-5.1-chat-latest`: $1.25 / $10.00
- `gpt-4o`: $2.50 / $10.00
- `gpt-4o-mini`: $0.15 / $0.60

Notes:
- The LLM can suggest categories and tags. Categories are capped at 4 and limited to AI, Leadership, Technology, Human.
- `The250` is always added automatically and must exist on the site.
- Tags are capped at 8 and missing tags are created automatically.
- Existing tags are provided to the LLM (capped at 50 by usage count).
- If `--invoke-llm` is omitted, a stub `meta.json` is written and no publish occurs.
- Yoast fields supported via LLM output: `focus_keyphrase`, `meta_description` (<=160 chars).
- `--minimize-cost` uses a quality-gated model cascade for metadata: tries lowest-cost models first and escalates only if required metadata quality checks fail.
- `--quality-profile` controls those checks:
  - `strict`: excerpt required, >=4 tags, keyphrase + meta description required, keyphrase must appear in meta description, meta description length 120-160.
  - `balanced`: excerpt required, >=3 tags, keyphrase + meta description required, keyphrase must appear in meta description, meta description <=160.
  - `loose`: excerpt optional, >=1 tag, meta description required, keyphrase optional, meta description <=160.
- LLM calls use a model capability map for temperature settings and automatically retry once with API default temperature if a model rejects the configured value.
- `--publish-date` with `--dry-run` writes `shift_report.json` to the output directory.

Example:
```bash
python3 wp_agent.py \
  --content-md "new_posts/*.md" \
  --invoke-llm \
  --preview \
  --dry-run
```

To publish:
```bash
python3 wp_agent.py \
  --content-md "new_posts/*.md" \
  --invoke-llm
```

Use an existing meta JSON (skip LLM):
```bash
python3 wp_agent.py \
  --content-md "new_posts/post.md" \
  --meta-json "out/post_slug/meta.json"
```
- Incremental export of posts + media:
  ```bash
  python3 wp_utilities.py --export-site posts,media --incremental --url https://johnmaconline.com
  ```
  This writes to `export/` with `*.jsonl` files, `export/site.json`, and a `export/manifest.json`.

### `categorize_wp_posts.py`
Uses OpenAI to decide if posts should be tagged with a target category and additively updates categories.
Also supports single-call recategorization for `The250` posts into the 4 supported categories (`AI`, `Leadership`, `Technology`, `Human`).

Args:
- `--url` Site URL or WP API URL (required)
- `--target-category` Category to add when matched (default: `AI`)
- `--only-category` Only process posts already in this category (by name)
- `--recategorize-the250` One-call-per-post recategorization mode for posts in `The250`
- `--start-date` Start date (MM-DD-YYYY); processing runs backward in time from this date
- `--model` OpenAI model (default: `gpt-4.1`)
- `--minimize-cost` Auto-select lowest estimated token cost model (enabled automatically for `--recategorize-the250`)
- `--limit` Max number of posts
- `--max-chars` Max chars sent to model (default: `8000`)
- `--min-confidence` Minimum confidence to add category (default: `0.8`)
- `--dry-run` No updates, just report
- `--sleep` Seconds to sleep between OpenAI calls (default: `0.4`)
- `--report` JSONL report path
- `--updated-csv` CSV output path (default: `updated_posts.csv`)
- `--confidence-column` Include confidence in CSV
- `--overwrite-csv` Overwrite CSV instead of append
- `--wp-username` WordPress username (or env `WP_USERNAME`)
- `--wp-app-password` WordPress application password (or env `WP_APP_PASSWORD`)
- `--openai-api-key` OpenAI API key (or env `OPENAI_API_KEY`)
- `-v/--verbose` Verbose logging
- `-q/--quiet` Minimal stdout

Examples:
- Dry‑run, only posts already in `The250`:
  ```bash
  export OPENAI_API_KEY="..."
  python3 categorize_wp_posts.py --url https://johnmaconline.com --target-category AI --only-category The250 --dry-run
  ```
- Dry-run recategorization for all `The250` posts from Feb 9, 2026 backward (single LLM call per post):
  ```bash
  export OPENAI_API_KEY="..."
  python3 categorize_wp_posts.py \
    --url https://johnmaconline.com \
    --recategorize-the250 \
    --start-date 02-09-2026 \
    --dry-run
  ```
- Apply recategorization updates:
  ```bash
  export OPENAI_API_KEY="..."
  export WP_USERNAME="your_wp_user"
  export WP_APP_PASSWORD="xxxx xxxx xxxx xxxx xxxx"
  python3 categorize_wp_posts.py \
    --url https://johnmaconline.com \
    --recategorize-the250 \
    --start-date 02-09-2026
  ```
- Apply updates:
  ```bash
  export OPENAI_API_KEY="..."
  export WP_USERNAME="your_wp_user"
  export WP_APP_PASSWORD="xxxx xxxx xxxx xxxx xxxx"
  python3 categorize_wp_posts.py --url https://johnmaconline.com --target-category AI
  ```

### `post.py`
Schedules a markdown post on WordPress and optionally posts a Twitter/X thread.

Args:
- `--file` Path to the markdown file (required)
- `--title` Title of the blog post (required)
- `--date` Publish date (YYYY‑MM‑DD, Eastern Time) (required)
- `--model` OpenAI model for SEO fields (default: `gpt-4`)
- `-v/--verbose` Verbose logging
- `-q/--quiet` Minimal stdout

Required env vars:
- `WP_USERNAME`
- `WP_APP_PASSWORD`
- `OPENAI_API_KEY`

Optional Twitter/X env vars:
- `TWITTER_API_KEY`
- `TWITTER_API_SECRET`
- `TWITTER_ACCESS_TOKEN`
- `TWITTER_ACCESS_SECRET`

## Credentials

### WordPress
Use a WordPress **Application Password** (not your normal login password). Create one in:
`WordPress Admin → Users → Profile → Application Passwords`.

Then set:
```bash
export WP_USERNAME="your_wp_user"
export WP_APP_PASSWORD="xxxx xxxx xxxx xxxx xxxx"
```

### OpenAI
```bash
export OPENAI_API_KEY="sk-..."
```

## Tests

Run all tests locally:
```bash
pytest
```

CI runs the same tests and post‑processing steps via `.github/workflows/tests.yml`.
