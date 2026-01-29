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
- `--url` URL of the site or WP API root
- `--number` Number of posts to download
- `--outdir` Directory to save posts (default: `posts`)
- `--indir` One or more input dirs for concat (space‑separated)
- `--outfile` Output file base name (defaults to `out.<format>` if omitted)
- `--outfile-format` Results output format: `csv` or `json` (default: `csv`)

Results from `--get-plugins`, `--get-posts`, or any other `--get-*` operation are written to a file and also printed to stdout as an ASCII table. If `--outfile` is omitted, the default is `out.<format>`.
- `--format` Output formats for downloaded posts (supports multiple) [default: txt]
- `--with-meta` Save per-post metadata JSON alongside downloaded posts
- `--get-posts` Download posts
- `--list-posts` Print posts via WP REST API
- `--concat` Concatenate files
- `--get-plugins` Print plugin list via WP REST API (requires credentials)
- `--get-posts` Print posts via WP REST API
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

### `categorize_wp_posts.py`
Uses OpenAI to decide if posts should be tagged with a target category and additively updates categories.

Args:
- `--url` Site URL or WP API URL (required)
- `--target-category` Category to add when matched (default: `AI`)
- `--only-category` Only process posts already in this category (by name)
- `--model` OpenAI model (default: `gpt-4.1`)
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
