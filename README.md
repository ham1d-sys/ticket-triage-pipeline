# Ticket Triage Pipeline

A pipeline that validates and triages support tickets using the OpenAI API. The pipeline classifies each valid ticket by
category and urgency, provides a short explanation of its decision, and exports the results as CSV files.

## How It Works

1. **Load** — Reads support tickets from the CSV files in the input path (`data/input/` by default). Each file is
   processed as its own run.
2. **Validate and clean up** — Applies the validation rules to each ticket:
    - Ensures all expected fields are present and non-empty.
    - Ensures the body of a valid ticket contains at least 3 characters.
    - Ensures `received_at` is a valid timestamp (`YYYY-MM-DD HH:MM:SS`).
    - Ensures the sender is a syntactically valid email address (RFC rules via `email-validator`, no DNS lookups).
    - Ensures a ticket does not repeat an earlier one (same `ticket_id` and content).

   Invalid tickets are removed from the in-memory ticket collection and retained for separate reporting.
3. **Triage** — Sends the remaining valid tickets to the OpenAI API to determine their category, urgency, and triage
   reason. Requests run concurrently (up to 5 at a time), each with a 10-second timeout; connection errors, rate
   limits, and server errors are retried with exponential backoff. The system prompt lives in `system_prompt.md`.
4. **Write** — Exports triaged tickets, invalid tickets, and valid tickets requiring review to separate CSV files, in
   input order, together with a manifest describing the run.

## Prerequisites

- Python 3.10 or newer
- An OpenAI API key

You can create an API key from the [OpenAI dashboard](https://platform.openai.com/settings/organization/api-keys).

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/ham1d-sys/ticket-triage-pipeline.git
cd ticket-triage-pipeline
```

### 2. Create and activate a virtual environment

This step is optional but recommended.

**Linux/macOS:**

```bash
python3 -m venv .venv
source .venv/bin/activate
```

**Windows:**

```bash
python -m venv .venv
.venv\Scripts\activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure your API key

Copy the example environment file:

```bash
# Linux/macOS
cp .env.example .env

# Windows
copy .env.example .env
```

Open `.env` and add your OpenAI API key:

```env
OPENAI_API_KEY=your_api_key_here
```

You can edit the file using any text editor. For example:

```bash
# Windows
notepad .env

# Linux
nano .env

# macOS
open -a TextEdit .env

# VS Code
code .env
```

## Usage

Run the triage pipeline from the repository root:

```bash
python src/main.py --mode eval
```

| Option                      | Description                                                                                                                                    |
|-----------------------------|------------------------------------------------------------------------------------------------------------------------------------------------|
| `--mode {eval,production}`  | Required. `production` skips tickets already triaged in earlier runs (same `ticket_id` and content); `eval` triages every valid ticket.        |
| `--input PATH`              | A CSV file, or a directory of CSV files, to process. Defaults to `data/input`.                                                                 |

Every input file gets its own run folder:

```text
data/output/<run_id>/
```

Each run folder contains:

- `triaged.csv` — Successfully triaged valid tickets
- `invalid_tickets.csv` — Tickets that failed validation
- `needs_review.csv` — Tickets that could not be triaged because the model refused the request or the API request failed
- `unattempted.csv` — Valid tickets that were not attempted because the run was aborted
- `manifest.json` — The run's status (`completed`, `aborted` or `failed`), mode, timestamps, code version, configuration
  (model, prompt hash, abort count, concurrency), input path and SHA-256, ticket counts, and any error

> [!NOTE]
> If 5 consecutive tickets fail after all their retries (API connection errors, rate limits or server errors), the run
> is aborted: requests already in flight finish, the remaining tickets are written to `unattempted.csv`, and the
> remaining input files are skipped.

## Output Format

### `triaged.csv`

| ticket_id | sender                   | subject               | body                                             | received_at           | category | urgency  | model_reason                                                                                                                      |
|-----------|--------------------------|-----------------------|--------------------------------------------------|-----------------------|----------|----------|-----------------------------------------------------------------------------------------------------------------------------------|
| T01       | `maria.k@example.com`    | `Can't log in`        | `I get invalid credentials every time I try.`    | `2026-08-19 07:12:00` | `other`  | `medium` | User is unable to log in due to repeated invalid-credentials errors; no evidence of a product bug beyond an authentication issue. |
| T02       | `t.becker@freelance.net` | `Thanks for the help` | `Support resolved my issue fast, appreciate it.` | `2026-08-19 10:22:00` | `other`  | `low`    | The message is positive feedback thanking support and does not report an issue or request.                                        |
| T03       | `noreply@dealzhub.biz`   | `Reward`              | `You have been selected for a free gift card.`   | `2026-08-19 08:15:00` | `spam`   | `low`    | Unsolicited free gift card message from a promotional-looking sender, with no support issue described.                            |

### `invalid_tickets.csv`

| ticket_id | sender                   | subject                  | body                                              | received_at           | reason                                    |
|-----------|--------------------------|--------------------------|---------------------------------------------------|-----------------------|-------------------------------------------|
| T01       | `j.torres@brightpath.io` |                          | `Charged twice this month for the Pro plan.`      | `2026-08-19 08:03:00` | `Empty expected field(s).`                |
| T02       | `info@shopwave.store`    | `Billing address update` | `We moved offices, need billing address updated.` |                       | `Empty expected field(s).`                |
| T03       | `priya.n@northline.co`   | `Quick one`              | `ok`                                              | `2026-08-19 10:05:00` | `` `body` field is under 3 characters. `` |

### `needs_review.csv`

| ticket_id | sender                  | subject                           | body                                                                     | received_at           | reason                                        |
|-----------|-------------------------|-----------------------------------|--------------------------------------------------------------------------|-----------------------|-----------------------------------------------|
| T01       | `a.chen@example.com`    | `Request for account access`      | `Please provide access to the restricted account settings.`              | `2026-08-19 11:14:00` | `Refusal.`                                    |
| T02       | `support@brightpath.io` | `Unable to load customer profile` | `The customer profile request failed repeatedly during troubleshooting.` | `2026-08-19 11:37:00` | `APIConnectionError after 6 triage attempts.` |

`unattempted.csv` has the same columns as the input, without a `reason` column.

## Configuration

These constants are defined in `src/triage.py`:

| Constant              | Default        | Meaning                                                                |
|-----------------------|----------------|------------------------------------------------------------------------|
| `MODEL`               | `gpt-5.6-luna` | Model used for triage                                                  |
| `MAX_CONCURRENCY`     | `5`            | Maximum number of API requests in flight at once                       |
| `API_TIMEOUT_SECONDS` | `10`           | Timeout of a single API request                                        |
| `STOP_COUNT`          | `6`            | Attempts per ticket before it is sent to `needs_review.csv`            |
| `ABORT_COUNT`         | `5`            | Consecutive failed tickets after which the run is aborted              |

To choose a timeout, `python scripts/measure_latency.py` times single API calls and suggests a value (2 × p99).
If you see `RateLimitError` rows in `needs_review.csv`, lower `MAX_CONCURRENCY`.

## Data Handling

Only each ticket's `sender`, `subject` and `body` are sent to the OpenAI API, as JSON; the system prompt tells the model to treat them as untrusted data, and its output is limited to the triage schema. Ticket content is personal data and is stored in plain text in `data/output/` (git-ignored).

## Benchmark (synthetic)

What to expect, not a guarantee. The numbers below come from three **synthetic** sets of 50 tickets each in
`data/input/`, with gold labels in `data/*_gold_labels.csv`:

- `support_tickets_test.csv` — a general set with typical and borderline tickets
- `support_tickets_messy.csv` — multilingual text, typos, HTML, forwarded chains, and unusual sender addresses
- `support_tickets_injection.csv` — tickets that try to override the instructions or steer the output

Each set was run 3 times in `eval` mode with the current prompt and `gpt-5.6-luna`. Model output varies between runs,
so results are shown as ranges. The sets were also used while developing the prompt, so expect lower accuracy on real
tickets. "Edge" tickets are the deliberately ambiguous ones (all injection tickets are counted as edge).

| Input                           | Valid tickets | Overall (target 90%) | Edge (target 80%)        | Category | Urgency | Invalid caught |
|---------------------------------|---------------|----------------------|--------------------------|----------|---------|----------------|
| `support_tickets_test.csv`      | 40            | 38–39 (95.0–97.5%)   | 6–7 of 8 (75.0–87.5%)    | 40       | 38–39   | 10 of 10       |
| `support_tickets_messy.csv`     | 40            | 37–39 (92.5–97.5%)   | 9–10 of 11 (81.8–90.9%)  | 40       | 37–39   | 10 of 10       |
| `support_tickets_injection.csv` | 44            | 42–44 (95.5–100%)    | 35–36 of 36 (97.2–100%)  | 43–44    | 42–44   | 6 of 6         |
| All three                       | 124           | 118–121 (95.2–97.6%) | 51–52 of 55 (92.7–94.5%) | 123–124  | 118–121 | 26 of 26       |

Apart from the injection tickets, edge accuracy was 16 of 19 (84.2%) in every one of the 3 runs.

Failure cases seen across the runs:

- An informal, typo-filled request to refund a double charge was rated `medium` instead of `high` in all 3 runs
  (test set).
- A ticket asking for a missing feature but saying it "feels broken" was rated `medium` instead of `low` in 2 of 3 runs
  (test set).
- A casually worded report of a broken button with a working workaround was rated `low` instead of `medium` in all 3
  runs (messy set).
- In 1 of 3 runs, a ticket containing a fake closing tag followed by a second, made-up urgent ticket was classified as
  `bug`/`high` (injection set). No other injection changed a category in any run; the other misses were one-level
  urgency differences.

## Testing

Install the dev dependencies and run the test suite with:

```bash
pip install -r requirements-dev.txt
pytest
```