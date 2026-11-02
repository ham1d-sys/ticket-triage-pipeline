# Ticket Triage Pipeline

A pipeline that validates and triages support tickets using the OpenAI API. The pipeline classifies each valid ticket by category and urgency, provides a short explanation of its decision, and exports the results as CSV files.

## How It Works

1. **Load** — Reads support tickets from a CSV file.
2. **Validate and clean up** — Applies the validation rules to each ticket:
    - Ensures all expected fields are present and non-empty.
    - Ensures the body of a valid ticket contains at least 3 characters.
    - Ensures `received_at` is a valid timestamp.
    - Ensures the sender is valid.

   Invalid tickets are removed from the in-memory ticket collection and retained for separate reporting.
3. **Triage** — Sends the remaining valid tickets to the OpenAI API to determine their category, urgency, and triage
   reason.
4. **Write** — Exports triaged tickets, invalid tickets, and valid tickets requiring review to separate CSV files.

## Prerequisites

- Python 3.14 or newer
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
python3 -m venv venv
source venv/bin/activate
```

**Windows:**

```bash
python -m venv venv
venv\Scripts\activate
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
python src/main.py
```

The generated files are saved in:

```text
data/output/
```

Depending on the input data and processing results, the pipeline may generate one or more of the following files:

- `triaged.csv` — Successfully triaged valid tickets
- `invalid_tickets.csv` — Tickets that failed validation
- `needs_review.csv` — Tickets that could not be triaged because the model refused the request or the API request failed

> [!NOTE]
> If API connection errors occur for the configured maximum number of consecutive attempts, processing is aborted for
the batch.

## Output Format

### `triaged.csv`

| ticket_id | sender | subject | body | received_at | category | urgency | reason |
|-----------|---|---|---|---|---|---|---|
| T01       | `maria.k@example.com` | `Can't log in` | `I get invalid credentials every time I try.` | `2026-08-19 07:12:00` | `other` | `medium` | User is unable to log in due to repeated invalid-credentials errors; no evidence of a product bug beyond an authentication issue. |
| T02       | `t.becker@freelance.net` | `Thanks for the help` | `Support resolved my issue fast, appreciate it.` | `2026-08-19 10:22:00` | `other` | `low` | The message is positive feedback thanking support and does not report an issue or request. |
| T03       | `noreply@dealzhub.biz` | `Reward` | `You have been selected for a free gift card.` | `2026-08-19 08:15:00` | `spam` | `low` | Unsolicited free gift card message from a promotional-looking sender, with no support issue described. |

### `invalid_tickets.csv`

| ticket_id | sender | subject | body | received_at | reason |
|-----------|---|---|---|---|---|
| T01       | `j.torres@brightpath.io` |  | `Charged twice this month for the Pro plan.` | `2026-08-19 08:03:00` | `['Empty expected field(s).']` |
| T02       | `info@shopwave.store` | `Billing address update` | `We moved offices, need billing address updated.` |  | `['Empty expected field(s).']` |
| T03       | `priya.n@northline.co` | `Quick one` | `ok` | `2026-08-19 10:05:00` | ``['`body` field is under 3 characters.']`` |

### `needs_review.csv`

| ticket_id | sender | subject | body | received_at | reason |
|-----------|---|---|---|---|---|
| T01       | `a.chen@example.com` | `Request for account access` | `Please provide access to the restricted account settings.` | `2026-08-19 11:14:00` | `['Refusal.']` |
| T02       | `support@brightpath.io` | `Unable to load customer profile` | `The customer profile request failed repeatedly during troubleshooting.` | `2026-08-19 11:37:00` | `['APIConnectionError after 4 triage attempts.']` |

## Testing

Run the test suite with:

```bash
pytest
```

## Known Limitations

- **Aborted batches discard partial results.** When a batch aborts after consecutive transient API failures, `main.py` returns before any output files are written. Tickets already triaged and the invalid-ticket report are not saved, and a re-run processes every ticket again.
- **Retries stack.** The OpenAI SDK retries a failed request twice by default, and `triage_ticket` adds up to 4 attempts on top of that, so a single ticket can make up to 12 HTTP requests. The `after 4 triage attempts` text in `needs_review.csv` counts only the outer attempts. With the 15-minute client timeout, a run of timeouts can take hours in the worst case before the batch aborts.
- **Flex capacity errors are not handled.** Flex processing can return `429 Resource Unavailable` when capacity is short. The SDK raises this as `RateLimitError`, which is not an `APIConnectionError`, so it is neither retried by the pipeline nor counted toward the abort threshold, and it stops the run with an unhandled exception. There is no fallback to the standard tier.