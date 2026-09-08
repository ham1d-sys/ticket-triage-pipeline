# Ticket Triage Agent

An agentic pipeline that validates and triages support tickets using the OpenAI API. Each valid ticket is classified by
category and urgency, with a short explanation of the decision. Results are exported as CSV files.

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
git clone https://github.com/ham1d-sys/ticket-triage-agent.git
cd ticket-triage-agent
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
python src/triage.py
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

| content                                                                                                                                                                  | category | urgency  | reason                                                                                                                            |
|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------|----------|----------|-----------------------------------------------------------------------------------------------------------------------------------|
| `{'sender': 'maria.k@example.com', 'subject': "Can't log in", 'body': 'I get invalid credentials every time I try.', 'received_at': '2026-08-19 07:12:00'}`              | `other`  | `medium` | User is unable to log in due to repeated invalid-credentials errors; no evidence of a product bug beyond an authentication issue. |
| `{'sender': 't.becker@freelance.net', 'subject': 'Thanks for the help', 'body': 'Support resolved my issue fast, appreciate it.', 'received_at': '2026-08-19 10:22:00'}` | `other`  | `low`    | The message is positive feedback thanking support and does not report an issue or request.                                        |
| `{'sender': 'noreply@dealzhub.biz', 'subject': 'Reward', 'body': 'You have been selected for a free gift card.', 'received_at': '2026-08-19 08:15:00'}`                  | `spam`   | `low`    | Unsolicited free gift card message from a promotional-looking sender, with no support issue described.                            |

### `invalid_tickets.csv`

| content                                                                                                                                                | reason                                      |
|--------------------------------------------------------------------------------------------------------------------------------------------------------|---------------------------------------------|
| `{'sender': 'j.torres@brightpath.io', 'subject': '', 'body': 'Charged twice this month for the Pro plan.', 'received_at': '2026-08-19 08:03:00'}`      | `['Empty expected field(s).']`              |
| `{'sender': 'info@shopwave.store', 'subject': 'Billing address update', 'body': 'We moved offices, need billing address updated.', 'received_at': ''}` | `['Empty expected field(s).']`              |
| `{'sender': 'priya.n@northline.co', 'subject': 'Quick one', 'body': 'ok', 'received_at': '2026-08-19 10:05:00'}`                                       | ``['`body` field is under 3 characters.']`` |

### `needs_review.csv`

| content                                                                                                                                                                                                     | reason                                            |
|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|---------------------------------------------------|
| `{'sender': 'a.chen@example.com', 'subject': 'Request for account access', 'body': 'Please provide access to the restricted account settings.', 'received_at': '2026-08-19 11:14:00'}`                      | `['Refusal.']`                                    |
| `{'sender': 'support@brightpath.io', 'subject': 'Unable to load customer profile', 'body': 'The customer profile request failed repeatedly during troubleshooting.', 'received_at': '2026-08-19 11:37:00'}` | `['APIConnectionError after 4 triage attempts.']` |

## Testing

Run the test suite with:

```bash
pytest
```