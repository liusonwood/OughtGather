<div align="center">

# 📖 Ought Gather

**Automated information aggregator delivering custom RSS, web articles, and newsletters to your Kindle as daily EPUBs**

[![Daily Gather](https://github.com/liusonwood/oughtgather/actions/workflows/daily-gather.yml/badge.svg)](https://github.com/liusonwood/oughtgather/actions/workflows/daily-gather.yml)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![License: AGPL v3](https://img.shields.io/badge/License-AGPL%20v3-blue.svg)](LICENSE)
[![EPUB 3.0](https://img.shields.io/badge/EPUB-3.0-6f42c1)](docs/EPUB_COMPLIANCE.md)
[![Kindle Delivery](https://img.shields.io/badge/Kindle-Email%20Delivery-orange)](#github-actions-deployment)

🌐 [简体中文](./README.md) | [English](./README_EN.md)

</div>

Ought Gather is a Python-based automated information aggregation tool. It collects content from highly customizable sources like RSS feeds, webpages, newsletters, and read-later services, then formats and sends them daily as an EPUB book to your Kindle.

<p align="center">
  <img src="img/Kindle_img0.jpg" alt="Kindle preview 0" width="24%">
  <img src="img/Kindle_img1.jpg" alt="Kindle preview 1" width="24%">
  <img src="img/Kindle_img2.jpg" alt="Kindle preview 2" width="24%">
  <img src="img/Kindle_img3.jpg" alt="Kindle preview 3" width="24%">
</p>

## Features

- **Built-in Source Types**: Supports 4 core content sources out of the box: `rss`, `web`, `mail`, and `trending`.
- **Plugin Architecture**: Easily add custom content sources using Python plugins.
- **Serverless Automation**: Powered by GitHub Actions—no dedicated or self-hosted server required.
- **Automatic Emoji Rendering**: Dynamically converts emojis in text into black-and-white PNG images, ensuring flawless display on Kindle and other e-paper/e-ink screens.
- **Advanced Content Controls**: Configure source-specific priorities, link preservation (`keep_link`), full-text extraction (`full_text`), HTML element exclusion (`exclude`), and title keyword filtering (`delete`).
- **Standard EPUB 3.0 Generation**: Creates compliant EPUB files featuring an auto-generated cover, table of contents, main body, and a delivery summary chapter.
- **Dynamic Covers**: Supports custom cover images, fallback to Bing's Daily Wallpaper, and simple solid background fallback if network requests fail.
- **Formatting Placeholders**: Supports `{time}` for dates in titles and `</br>` for cover line-breaks.
- **Deduplication System**: Keeps track of processed content using `fetched_urls.txt`, with automatic pruning once records exceed 500,000 entries.
- **Environment Overrides**: Allows delivering full configurations via the `CONFIG_JSON` environment variable to keep private content feeds out of public source repositories.
- **Scheduled Triggers**: Supports Cloudflare Workers as an external trigger for GitHub Actions to ensure reliable, on-time delivery.

## Requirements

- Python 3.11+
- Dependencies listed in `requirements.txt`
- An SMTP-enabled email account for sending to Kindle
- API Keys configured for specific content fetchers as needed

---

## GitHub Actions Deployment (Recommended)

The workflow file is located at [.github/workflows/daily-gather.yml](.github/workflows/daily-gather.yml). It runs daily on a schedule or can be triggered manually. The workflow sets up dependencies, constructs `config.json`, executes `python src/main.py`, commits the deduplication ledger, and retains the generated EPUB as an artifact for 7 days.

### Deployment Steps

**1. Fork the Repository**

Click the `Fork` button on GitHub to copy the project to your own account.

**2. Configure Content Sources & Environment Variables**

[Visual Config Editor](https://liusonwood.github.io/OughtGather/)

See the [Secrets Configuration](#secrets-configuration) section below.

**3. Manually Run Once to Verify**

```text
Actions -> Daily Gather -> Run workflow
```

Once successful:

- The EPUB is created in `output/` and uploaded as an artifact (retained for 7 days).
- The EPUB is sent via email to your `KINDLE_EMAIL`.
- `data/fetched_urls.txt` is updated in the GitHub Actions cache for deduplication on the next run.

### Customizing Run Schedules

We recommend triggering the workflow via Cloudflare Workers for precise cron executions (typically within 1 minute accuracy). The built-in GitHub Actions `schedule` serves as a fallback and automatically skips itself if an external run happened within the previous 12 hours to prevent duplicate deliveries.

#### Configure External Trigger (Recommended)

**Step 1: Modify Trigger Cron**

Change the Cron timing in `wrangler.toml` to your desired delivery time (UTC):

```toml
[triggers]
crons = ["30 23 * * *"]  # UTC 23:30, i.e., 07:30 Beijing Time (GMT+8)
```

**Step 2: Connect Repository on Cloudflare Dashboard**

1. Log into the [Cloudflare Dashboard](https://dash.cloudflare.com), go to **Workers & Pages** → **Create** → **Connect to Git**.
2. Authorize GitHub, select this repository.
3. Set **Root directory** to `/cloudflare-worker`, and leave the **Build command** empty.
4. Click **Save and Deploy**.

**Step 3: Add Environment Variables**

In the Worker **Settings** → **Variables** tab, add the following three variables:

| Variable Name | Description |
|:---|:---|
| `GITHUB_OWNER` | Your GitHub Username |
| `GITHUB_REPO` | Repository Name (e.g., `oughtgather`) |
| `GITHUB_PAT` | GitHub Personal Access Token (Requires `repo` scope; store as an Encrypted Secret) |

> Note: Generate your `GITHUB_PAT` at the [GitHub Token Creation Page](https://github.com/settings/tokens/new) with the `repo` scope checked.

**Verification**: Visit your Worker URL (`https://<worker-name>.<subdomain>.workers.dev/`). If it displays `GitHub Actions trigger sent successfully!`, the connection is successful.

#### GitHub Actions Schedule Trigger

You can also use the default trigger configured via the `cron` field under `on.schedule` inside the workflow YAML (using UTC):

```yaml
on:
  schedule:
    - cron: '0 0 * * *'   # UTC 00:00, approx. 08:00 Beijing Time
  workflow_dispatch:
```

> **Note**: The environment variable `TZ: Asia/Shanghai` inside the workflow only dictates the internal time calculations and log timestamps; it does not change the cron scheduler's UTC-based execution. Actual execution times depend on GitHub Actions queue states.

### Deduplication Cache Mechanism (Zero Write Permissions Required)

By leveraging the `actions/cache` mechanism, the deduplication tracker data (`data/fetched_urls.txt`) is automatically saved securely in the GitHub cache servers.

### Troubleshooting Failures

<details>
<summary><b>Expand: Delivery Failures</b></summary>

| Symptom | Common Causes |
| --- | --- |
| Configuration setup step fails | `CONFIG_JSON` is not valid JSON |
| SMTP Login fails | Incorrect host, username, password, port, or missing app-specific password |
| Mail sent but Kindle doesn't receive | Sender email is not added to the approved "Personal Document Approved Email List" in your Amazon Kindle account settings |
| "Send to Kindle" Web platform shows a failure | EPUB generation compliance issue, please open an issue with the file details |
| No EPUB generated | No new articles/updates found from any configured sources |
</details>

---

## Secrets Configuration

Configure these in your GitHub repository under `Settings -> Secrets and variables -> Actions`. For local development, set them as environment variables.

### Required Variables

| Secret / Env Var | Description |
| --- | --- |
| `CONFIG_JSON` | A complete `config.json` string representation. This overrides the root directory's `config.json` file. Highly recommended for GitHub Actions deployment to avoid hardcoding feed secrets into the codebase. |
| `KINDLE_EMAIL` | Your Kindle device email address (`@kindle.com`) |
| `SMTP_HOST` | Outgoing SMTP server address (e.g., `smtp.gmail.com`) |
| `SMTP_PASSWORD` | Outgoing mail account password or app-specific token |
| `SMTP_PORT` | SMTP port; use `465` for SSL, or `587` for STARTTLS |
| `SMTP_USERNAME` | SMTP account username |
| `WEBDAV_ENABLED` | Set to `true` to enable WebDAV uploading |
| `WEBDAV_PASSWORD` | WebDAV account password |
| `WEBDAV_REMOTE_PATH` | WebDAV remote storage path, default is `/` |
| `WEBDAV_URL` | WebDAV server endpoint URL |
| `WEBDAV_USERNAME` | WebDAV account username |

### Fetcher Custom Variables

| Secret / Env Var | Description |
| --- | --- |
| `OPENROUTER_API_ENDPOINT` | Custom OpenRouter-compatible endpoint (defaults to `https://openrouter.ai/api/v1/chat/completions`) |
| `OPENROUTER_API_KEY` | OpenRouter API key, used for calling LLMs to extract trending summaries |
| `OPENROUTER_MODEL` | Custom LLM model name |
| `QWEATHER_HOST` | QWeather (HeWeather) API host endpoint |
| `QWEATHER_KEY` | QWeather API key for pulling meteorological forecasts |
| `RAINDROPIO_API_KEY` | Raindrop.io API key for fetching saved read-later articles |
| `TAVILY_API_KEY` | Tavily API search engine key for trending news |
| `TESTMAIL_APP_API_KEY` | testmail.app API key used for parsing and fetching newsletters |

- **[SEND TO KINDLE](https://www.amazon.com/sendtokindle)**: You must register your SMTP sender email in Amazon's "Approved Personal Document E-mail List" under Kindle settings, or Amazon will reject the emails.
- **WebDAV**: Highly useful for non-Kindle devices. Successfully generated EPUBs are automatically synced to services like Jianguoyun, Nextcloud, or your local NAS.

---

## config.json Schema

For detailed documentation, refer to [docs/CONFIG.md](docs/CONFIG.md).

<details>
<summary>Core Structure Quick Reference</summary>

### Top-Level Fields

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `title` | object | ✓ | EPUB title & cover configuration |
| `limit` | int | | Default maximum articles fetched per source (defaults to `15`) |
| `load_images` | string | | Global image toggle: `"Y"` (default) or `"N"` (disable all images) |
| `body` | array | ✓ | List of content sources |

`title` Subfields:

| Field | Description |
| --- | --- |
| `text` | Book title, supports `{time}` placeholder (formatted date) and `</br>` for line breaks |
| `img` | Cover image URL. If left blank, it falls back to Bing Daily Wallpaper¹ or solid colors |

> ¹ **Copyright Note**: Bing Daily Wallpapers are copyrighted by Microsoft and their respective photographers. Automated fetching by this program is intended strictly for personal, non-commercial use and research. Do not publicly distribute or share generated EPUBs containing these cover images.

### Content Source Common Fields

| Field | Description |
| --- | --- |
| `title` | Chapter title displayed inside the EPUB |
| `type` | Source type (`rss`, `web`, `mail`, `trending`, or custom plugin type) |
| `src` | URL, keyword query, or query path depending on type. Required for all types. |
| `priority` | Ordering priority (higher values appear earlier). Defaults to `0`. Ties preserve config sequence. |
| `load_images` | `Y` (default) to download images. `N` to strip all `<img>` tags for this source. |
| `keep_link` | `Y` (default) preserves `<a>` tags. `N` strips tags and leaves plain text. |
| `exclude` | Custom HTML cleanup rules. Supports `start`, `end`, and `exact` modes. |
| `delete` | Comma-separated list of title exclusion keywords. Skips articles matching any keyword. |
| `metadata` | Fetcher-specific extended configurations. |

### Minimum Configuration Example

```json
{
  "title": {
    "text": "{Daily News {time}}",
    "img": ""
  },
  "limit": 15,
  "body": [
    {
      "type": "rss",
      "src": "https://hnrss.org/frontpage",
      "title": "Hacker News",
      "priority": 10,
      "keep_link": "Y",
      "full_text": "N"
    }
  ]
}
```
</details>

---

## Config Editor

We provide a zero-dependency visual configuration editor.

**Online Version** (Recommended):

```text
https://liusonwood.github.io/OughtGather/
```

**Offline Version**: Download and open the `config-editor.html` file locally in any browser.

<details>
<summary><b>Key Features</b></summary>

- Full support for all content source types (`rss`, `web`, `mail`, `trending`, and plugins), complete with helpful reminders on which environment variables are required.
- Import existing `config.json` configurations, add, delete, and drag-and-drop to reorder feeds.
- Quickly import RSS subscriptions using OPML (`opml.xml`) files.
- Visual editor for cleanup rules (`exclude`) and fetcher parameters (`metadata`).
- Export and download your completed JSON configuration or copy it directly to your clipboard.
- Automatic persistence in `localStorage`, protecting your setup across page refreshes.
</details>

---

## Local Development & Deployment

<details>
<summary><b>Expand Guide:</b></summary>

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Prepare Configuration

```bash
cp config.template.json config.json
# Edit config.json manually or copy visual-config outputs here
```

### 3. Set Up Environment Variables

```bash
export SMTP_HOST="smtp.example.com"
export SMTP_PORT="587"
export SMTP_USERNAME="sender@example.com"
export SMTP_PASSWORD="app-password"
export KINDLE_EMAIL="name@kindle.com"
```

### 4. Run the Application

```bash
python3.11 src/main.py
```

If new content is found, the script generates an EPUB under `output/` and triggers delivery to `KINDLE_EMAIL`. Log outputs are written to `logs/`.

### 5. Running Tests

```bash
# Execute entire test suite
python3.11 -m pytest tests/
```

**EPUBCheck Compliance Verification**:

Validate that generated EPUB outputs are strictly compliant with international EPUB 3 standards using [epubcheck](https://github.com/w3c/epubcheck).

Place your `epubcheck.jar` inside the `epubcheck/epubcheck.jar` folder and execute:

```bash
python3.11 -m pytest tests/test_integration.py::TestEpubcheckValidation -v
```

Refer to [docs/TESTING.md](docs/TESTING.md) and [docs/EPUB_COMPLIANCE.md](docs/EPUB_COMPLIANCE.md) for more details.
</details>

---

## Developing a New Fetcher

The project is structured with a modular, plugin-based architecture. To add a new content source, simply drop a file in the `src/fetchers/` directory.

### Development Guidelines

- Inherit from `BaseFetcher` (`from src.fetchers.base import BaseFetcher`).
- Declare a unique `type_name` class attribute to map back to the `"type"` field in `config.json`.
- Implement the `fetch(self) -> FetchResult` method returning a standard `FetchResult` object.
- File naming convention: `src/fetchers/<type_name>_fetcher.py`.
- Discovery is fully automatic; no registration boilerplate is required.

</br>
<details>
<summary><b>Rapid Code Generation via LLM</b></summary>

Use the prompt guidelines provided in [docs/new_fetcher_prompt_template.md](docs/new_fetcher_prompt_template.md). Answer the following 5 questions before feeding it to your favorite LLM:

1. What is the target content source (website, API, RSS, etc.)?
2. What are the expected fields inside `config.json`? (meaning of `src`, `metadata` options, etc.)
3. Are credentials (API Keys, etc.) required?
4. How should the article HTML be extracted/parsed?
5. Are there special cleanups or retry needs?
</details>

<details>
<summary><b>Key Superclass Helper Methods</b></summary>

| Method | Description |
| --- | --- |
| `self._make_request(url, ...)` | Safe HTTP requests with built-in retries |
| `self._extract_images(html)` | Extracts all img URLs inside HTML payload |
| `self._should_delete(title)` | Matches article titles against `delete` exclusion keywords |
| `self._restore_img_tags(html)` | Normalizes non-compliant images returned from Trafilatura |
</details>

<details>
<summary><b>Code Template</b></summary>

```python
from src.config import ContentSource, get_secret
from src.fetchers.base import BaseFetcher, FetchResult, Article

class MyFetcher(BaseFetcher):
    type_name = "my_type"                    # Value mapped in config.json's "type"
    src_placeholder = "Input placeholder text" # Hint displayed in config-editor
    config_schema = {                        # Visual-editor-specific options
        "metadata.my_param": {
            "type": "text",
            "label": "Custom parameter",
            "placeholder": "Enter value..."
        }
    }

    def fetch(self) -> FetchResult:
        result = FetchResult(source=self.source, articles=[])
        try:
            url = self.source.src
            response = self._make_request(url)
            # ... Parse body and content ...
            article = Article(title="Title", content="<p>Body</p>", url=url)
            if not self._should_delete(article.title):
                result.articles.append(article)
        except Exception as e:
            result.success = False
            result.error = str(e)
        return result
```
</details>

### Syncing Editor, Documents, and Workflows

**Option 1**: Automated Actions Sync (Recommended)

Managed automatically on push by [.github/workflows/sync-project-docs.yml](.github/workflows/sync-project-docs.yml).

**Option 2**: Manual Script Synchronization

Run helper utility scripts under the `scripts/` directory:

```bash
python3.11 scripts/update_editor.py
python3.11 scripts/update_readme_secrets.py
python3.11 scripts/update_workflow_secrets.py
```

---

## 📚 Project Documentation

To help you better install, configure, maintain, and contribute to this project, please refer to the complete set of documentation below:

- **Core Usage & Configuration**
  - [📖 Configuration Guide (CONFIG.md)](docs/CONFIG.md) — Detailed description of `config.json` fields, filtering rules, and source-specific settings.
- **Development & Community**
  - [🏗️ Design Document (design.md)](docs/design.md) — System architecture, content cleaning pipelines, and EPUB generation logic.
  - [✅ Testing Guide (TESTING.md)](docs/TESTING.md) — How to run automated tests, write test cases, and check coverage.
  - [🤝 Contributing Guidelines (CONTRIBUTING.md)](.github/CONTRIBUTING.md) — Code style, plugin development mandates, and timezone constraints.
  - [📜 Code of Conduct (CODE_OF_CONDUCT.md)](.github/CODE_OF_CONDUCT.md) — Standards for community interaction.
  - [🛡️ Security Policy (SECURITY.md)](.github/SECURITY.md) — How to report vulnerabilities and protect your private credentials.
  - [🙋 Support Guidelines (SUPPORT.md)](.github/SUPPORT.md) — Official channels for technical support.

---

## Directory Structure

```text
.
├── LICENSE
├── README.md           # Chinese Documentation
├── README_EN.md        # English Documentation
├── cloudflare-worker/  # Worker deployment triggers
├── config-editor.html  # Configuration utility
├── config.json
├── config.template.json
├── GEMINI.md
├── requirements.txt
├── data/               # Persistent deduplication store
│   └── fetched_urls.txt
├── docs/               # Technical guides and architectures
├── epubcheck/          # EPUB Check Validation CLI
│   └── epubcheck.jar
├── img/                # Demo and device screenshots
├── Fonts/              # Emitted and loaded resources (e.g., NotoEmoji-Medium.ttf)
├── scripts/            # Management and synchronization utils
├── src/                # Project Source Directory
│   ├── main.py
│   ├── config.py
│   ├── dedup/          # URL deduplication trackers
│   ├── epub/           # EPUB generator logic
│   ├── fetchers/       # Source-specific fetchers
│   ├── mailer/         # Delivery and SMTP modules
│   ├── processors/     # Content and image processors
│   ├── uploader/       # Cloud storage synchronizers
│   └── utils/          # Logging and shared helpers
└── tests/              # Comprehensive test suites
```

**Directory breakdown:**
- `src/`: Core implementation logic.
- `docs/`: In-depth documentation on formats, architectures, and testing.
- `tests/`: End-to-end integration and units confirming EPUB structures and extraction.
- `epubcheck/`: Off-grid validation package matching strict W3C standards.
- `data/`: Ephemeral deduplication cache.

---

## Disclaimer

This project supports automatically fetching Bing Daily Wallpaper as a cover image, including cropping, scaling, and adding text/date overlays. The copyright for these wallpapers belongs entirely to Microsoft Corporation or their respective photographers.

Users must comply with applicable national copyright laws and the Microsoft Services Agreement, **using the generated EPUB files strictly for personal, non-commercial study, reading, or research purposes**. Publicly sharing, redistributing, or commercializing generated e-books featuring copyrighted covers is strictly prohibited. Users assume all legal liabilities arising from any improper or copyright-infringing use; the project and its authors shall not be held liable for any claims.

## License

GNU AGPLv3.0, see [LICENSE](LICENSE).
