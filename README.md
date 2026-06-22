# newsmd

`newsmd` fetches recent RSS news, extracts full article text, translates non-Chinese articles to Simplified Chinese, generates Chinese summaries with a local Ollama model, and writes everything as Markdown.

It can run manually or automatically on macOS at 8:00 AM and 8:00 PM every day via `launchd`.

## What It Produces

Each run writes to:

```text
news_raw/MMDDYYYY-8am/
news_raw/MMDDYYYY-8pm/
```

Example output:

```text
news_raw/06212026-8pm/
├── summary.md
├── translated/
│   └── *.md
├── headlines/
│   └── *.md
├── tech/
│   └── *.md
└── finance/
    └── *.md
```

The RSS filter only keeps entries whose `published` or `updated` timestamp is within the last 24 hours.

## Supported Platform

This project is designed for macOS because automatic scheduling uses `launchd`.

Tested assumptions:

- macOS user account with a normal GUI login session.
- Internet access for RSS feeds, Python packages, Homebrew, and Ollama model download.
- Enough disk space for the Ollama model.
- Enough memory to run the selected local model. The default is an 8B model.

## Fresh Mac Setup

### 1. Install Apple's command line tools

Open Terminal and run:

```bash
xcode-select --install
```

Finish the system installer window before continuing.

### 2. Clone the repo

Use HTTPS on a fresh Mac because it does not require GitHub SSH key setup:

```bash
git clone https://github.com/chuxuanfu/newsmd.git
cd newsmd
```

If SSH is already configured:

```bash
git clone git@github.com:chuxuanfu/newsmd.git
cd newsmd
```

### 3. Run the installer

```bash
./scripts/install.sh
```

The installer will:

- Install Homebrew if missing.
- Install Python and Ollama through Homebrew if missing.
- Create `.venv/`.
- Install Python dependencies from `requirements.txt`.
- Start Ollama if needed.
- Pull the default model: `qwen3:8b`.
- Write the selected local model to `config.local.env`.
- Create `~/Library/LaunchAgents/com.newsmd.twicedaily.plist`.
- Load and enable the LaunchAgent.

Homebrew and model download can take a while on a fresh Mac. Homebrew may ask for your macOS password.

If you want a different Ollama model:

```bash
NEWSMD_MODEL=qwen3:8b ./scripts/install.sh
```

The same model name must be used for later manual runs if you do not want the default.
The installer writes it into `config.local.env`, which is ignored by git.

## Manual Test

Run only a few articles to verify the full flow:

```bash
NEWSMD_TOTAL_LIMIT=3 ./scripts/run_news_twice_daily.sh
```

Check output:

```bash
find news_raw -maxdepth 3 -type f | sort
```

You should see:

- `summary.md`
- article markdown files under `headlines/`, `tech/`, or `finance/`
- translated markdown files under `translated/` when English articles were processed

Check the latest log:

```bash
ls -lt logs | head
```

Then inspect the newest `news_*.log`:

```bash
tail -80 logs/news_MMDDYYYY-8am_HHMMSS.log
```

## Automatic Schedule

After `./scripts/install.sh`, macOS runs the project at:

```text
08:00 every day
20:00 every day
```

The LaunchAgent label is:

```text
com.newsmd.twicedaily
```

Check whether it is loaded:

```bash
launchctl print gui/$(id -u)/com.newsmd.twicedaily
```

Healthy signs:

```text
state = not running
program = /path/to/newsmd/scripts/run_news_twice_daily.sh
last exit code = 0
event triggers include Hour 8 Minute 0 and Hour 20 Minute 0
```

`RunAtLoad` is false, so the job does not run immediately at login. After reboot and login, macOS loads the LaunchAgent and waits for the next 8:00 AM or 8:00 PM trigger.

## Manual Backfill

Run a specific date and slot:

```bash
NEWSMD_DATE=06212026 NEWSMD_SLOT=8pm ./scripts/run_news_twice_daily.sh
```

Run a small backfill test:

```bash
NEWSMD_DATE=06212026 NEWSMD_SLOT=8pm NEWSMD_TOTAL_LIMIT=3 ./scripts/run_news_twice_daily.sh
```

Run selected topics:

```bash
NEWSMD_TOPICS="headlines tech" NEWSMD_TOTAL_LIMIT=5 ./scripts/run_news_twice_daily.sh
```

## Runtime Environment Variables

```text
NEWSMD_DATE            Output date, format MMDDYYYY
NEWSMD_SLOT            Output slot, usually 8am or 8pm
NEWSMD_TOPICS          Space-separated topics, default: headlines tech finance
NEWSMD_MAX_PER_FEED    Max RSS entries per feed, default: 10
NEWSMD_TOTAL_LIMIT     Total raw article limit, useful for tests
NEWSMD_MODEL           Ollama model, default: qwen3:8b
NEWSMD_OUTPUT_ROOT     Output root, default: ./news_raw
NEWSMD_LOG_DIR         Log dir, default: ./logs
NEWSMD_OLLAMA_URL      Ollama URL, default: http://localhost:11434
```

## Direct Python Usage

List topics:

```bash
.venv/bin/python3 scripts/rss_news_fetcher.py --list-topics
```

Fetch and summarize a small sample:

```bash
.venv/bin/python3 scripts/rss_news_fetcher.py \
  --topics headlines \
  --max 2 \
  --total-limit 3 \
  --output news_raw/manual-test
```

Regenerate summaries from an existing output folder:

```bash
.venv/bin/python3 scripts/rss_news_fetcher.py \
  --summary-only \
  --output news_raw/06212026-8pm
```

## Reload LaunchAgent

Use this after changing the generated plist or moving the repo:

```bash
launchctl bootout gui/$(id -u) "$HOME/Library/LaunchAgents/com.newsmd.twicedaily.plist" 2>/dev/null || true
launchctl bootstrap gui/$(id -u) "$HOME/Library/LaunchAgents/com.newsmd.twicedaily.plist"
launchctl enable gui/$(id -u)/com.newsmd.twicedaily
```

Command meanings:

- `bootout`: unload the current job from the user's `launchd` domain.
- `bootstrap`: load the plist into the user's `launchd` domain.
- `enable`: make sure the job is not disabled and can be scheduled.

## Logs vs launchctl

Use `launchctl print` to inspect scheduling state:

```bash
launchctl print gui/$(id -u)/com.newsmd.twicedaily
```

Use `tail` to inspect one concrete run:

```bash
tail -f logs/news_MMDDYYYY-8pm_HHMMSS.log
```

Short version:

```text
launchctl print = system scheduling state
tail -f log     = script runtime details for one run
```

## Troubleshooting

### No output at 8:00 or 20:00

Check launchd:

```bash
launchctl print gui/$(id -u)/com.newsmd.twicedaily
```

Check logs:

```bash
ls -lt logs | head -20
```

Common causes:

- The Mac was off or the user was not logged in at the scheduled time.
- The repo was moved after install. Rerun `./scripts/install.sh`.
- The LaunchAgent was disabled. Run the reload commands above.

### Ollama unavailable

Check:

```bash
curl http://localhost:11434/api/tags
```

Start manually:

```bash
ollama serve
```

Pull the model again:

```bash
ollama pull qwen3:8b
```

### Python dependency or certificate errors

Rebuild the venv:

```bash
rm -rf .venv
./scripts/install.sh
```

The runner exports `SSL_CERT_FILE` and `REQUESTS_CA_BUNDLE` from `certifi` to avoid certificate failures under `launchd`.

### A run says another run is active

Check for active processes:

```bash
ps aux | grep -E "rss_news_fetcher.py|run_news_twice_daily.sh" | grep -v grep
```

If there is no active process, remove the stale lock:

```bash
rmdir run/news_pipeline.lock
```

## Uninstall Automatic Schedule

This removes the LaunchAgent only. It does not delete the repo or generated news.

```bash
./scripts/uninstall_launchd.sh
```
