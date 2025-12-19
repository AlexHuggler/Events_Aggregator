# Events_Aggregator

Scrape DO214 events and build an email-friendly list for the next two months.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
```

## Usage

```bash
python events_email.py --output email.txt
```

The script outputs a formatted email body sorted by date (descending) and ranked by a fun
score within each day. Provide a different URL with `--url` if needed.
