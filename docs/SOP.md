# newsmd SOP

## Project Layout

```text
newsmd/
├── README.md
├── requirements.txt
├── scripts/
│   ├── install.sh
│   ├── run_news_twice_daily.sh
│   ├── rss_news_fetcher.py
│   └── uninstall_launchd.sh
├── news_raw/        # generated, ignored by git
├── logs/            # generated, ignored by git
└── run/             # generated, ignored by git
```

## Normal Operation

1. `launchd` triggers `scripts/run_news_twice_daily.sh` at 08:00 and 20:00.
2. The runner loads `config.local.env` if it exists.
3. The runner checks Python, certificates, lock state, and Ollama.
4. The runner calls `scripts/rss_news_fetcher.py`.
5. The fetcher keeps only RSS entries from the last 24 hours.
6. Full article text is extracted, summarized, translated, and written to `news_raw/`.

## Validation Checklist

- `launchctl print gui/$(id -u)/com.newsmd.twicedaily` shows `last exit code = 0`.
- Latest `logs/news_*.log` ends with `newsmd run finished with status 0`.
- The current output folder contains `summary.md`.
- Topic folders contain article markdown files.
- `translated/` contains translated markdown for non-Chinese articles.

## Safe Test Command

```bash
NEWSMD_TOTAL_LIMIT=3 ./scripts/run_news_twice_daily.sh
```

## Safe Backfill Command

```bash
NEWSMD_DATE=06212026 NEWSMD_SLOT=8pm NEWSMD_TOTAL_LIMIT=3 ./scripts/run_news_twice_daily.sh
```
