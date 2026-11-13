# Changelog

All notable changes to this project are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres
to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## Unreleased

## [v0.10.0] - 2026-11-13

### Added

- Add `messy` and `injection` evaluation ticket sets, each with gold labels.
- Add `scripts/measure_latency.py` to measure single-call API latency when choosing a timeout.
- Add a data-handling section and a synthetic benchmark section to the README.

### Changed

- Name gold labels `data/<input file>_gold_labels.csv`, one per input file, instead of
  `data/gold_labels.csv`.
- Bring the README up to date with the code: the required `--mode` flag, the `--input` option, the run folder and
  manifest, the `model_reason` column, and the configuration constants.

### Fixed

- Correct the minimum Python version in the README to 3.10 (tested on 3.10), instead of 3.14.

## [v0.9.0] - 2026-11-13

### Added

- Process every CSV in an input directory, or a single file, chosen with `--input` (default `data/input`). Each file
  gets its own run and manifest, and the remaining files are skipped if a run aborts.
- Triage tickets concurrently with `asyncio`: at most `MAX_CONCURRENCY` (5) API requests are in flight at once, and
  results are written in input order.
- Record `max_concurrency` in the manifest config.
- Add tests for the concurrency limit and the result order.

### Changed

- Run every CSV in `data/input` by default instead of one fixed file.
- `TriageProcessor.triage_ticket()` and `triage_tickets()` are now coroutines, and `main()` and
  `run_pipeline()` are async.
- Write the output files in a `finally` block so partial results are saved when a run fails, and catch specific errors
  before the generic `Exception`.
- Reset the manifest version to 1; the manifest changes were made during evaluation, before any release.

### Fixed

- Stop `unattempted.csv` listing tickets that were skipped as already triaged when a run aborts.

## [v0.8.2] - 2026-11-13

### Fixed

- Set a 10 second API timeout and turn off SDK retries, so tenacity controls all retrying. The client previously used
  the SDK defaults, a 600 second timeout plus 2 retries.

## [v0.8.1] - 2026-11-13

### Changed

- Tell the model that spam always has low urgency.

## [v0.8.0] - 2026-11-13

### Changed

- Send only `sender`, `subject` and `body` to the model, serialised as JSON, instead of the whole ticket.
- Tell the model to treat ticket contents as untrusted data.
- Move the system prompt to `system_prompt.md`.

## [v0.7.0] - 2026-11-13

### Changed

- Deduplicate tickets, and skip already-triaged ones, by `ticket_id` plus a hash of the ticket content instead of by
  `ticket_id` alone.

## [v0.6.0] - 2026-11-13

### Added

- Add `requirements-dev.txt` for test dependencies.
- Validate sender addresses against the email RFCs with `email-validator` (syntax only, no DNS lookups).

### Changed

- Limit `requirements.txt` to direct dependencies.

### Fixed

- Reject sender addresses that the old `@` check let through, such as `Name <a@b.com>`.
- Stop a missing sender from crashing sender validation.
- Update the outdated triage tests.

## [v0.5.0] - 2026-11-07

### Added

- Select the run mode with a command-line flag instead of a module constant.

### Fixed

- Restore `invalid_tickets.csv` output, which was missing due to a regression in v0.3.1.

## [v0.4.0] - 2026-11-07

### Added

- Validate that input and output ticket counts reconcile.
- Write unattempted tickets for every run.
- Retry rate-limit and internal server errors.

### Changed

- Consolidate ticket writing into a single function.

### Fixed

- Ensure `manifest.json` records a final status after aborted or failed runs. The error field now stores the exception
  message as a string, rather than the exception object.

## [v0.3.1] - 2026-11-06

### Added

- Write a manifest every run

## [v0.2.1] - 2026-11-04

### Changed

- Improve system prompt.

## [v0.2.0] - 2026-11-04

### Added

- Skip previously triaged tickets
- Create a UTC-timestamped output directory for each run.

## [v0.1.6] - 2026-11-02

### Fixed

- Always write `triaged.csv`, `needs_review.csv`, and `invalid_tickets.csv` with headers, even when a file has no rows,
  preventing scores from including stale data.
- Restricted `category` and `urgency` fields in `TriageSchema` model to their supported values.

### Changed

- Write ticket fields as separate CSV columns instead of serializing tickets as Python dictionaries.
- Store invalid-ticket reasons as a semicolon-separated string instead of a list.

## [v0.1.5] - 2026-09-06

### Changed

- Simplified retry handling by catching the broader `APIConnectionError` base class instead of the previously listed
  `APITimeoutError` subclass.

## [v0.1.4] - 2026-09-06

### Changed

- Moved client instantiation in `triage.py` from the top level into a function.

## [v0.1.3] - 2026-09-06

### Added

- Added pyproject.toml

### Fixed

- Fixed the consecutive-error logic to abort only after `ABORT_COUNT` consecutive failures instead of any failure after
  that threshold.

## [v0.1.2] - 2026-09-06

### Changed

- Refactored the logic for aborting after a set number of consecutive errors to make it more Pythonic.
- Simplified `ensure_valid_sender()` validation to check the shape of the address around the `@` character instead of
  performing full RFC validation.

### Fixed

- Fixed an `AttributeError` in `main.py` and `triage.py` caused by incorrectly calling `.__name__` on an exception
  instance.
- Fixed an issue that prevented the `@retry` decorator from being triggered by applying it to the function that triages
  a single ticket instead of the former batch-processing function.
- Fixed a silent-abort bug in the consecutive-error logic by recomputing the `recent_failures` slice on each loop
  iteration rather than only once before the loop.
- Fixed an issue that caused `invalid_sender_count` to remain stale instead of incrementing when invalid senders were
  encountered.

## [v0.1.1] - 2026-09-03

### Added

- Added success logging to the `write_outputs()` method in `TriageProcessor`.
- Added tests for aborting after a set number of consecutive errors.

### Changed

- Refactored the I/O logic by moving the top-level reading and writing functions from `main.py` to `ticket_io.py`.

## [v0.1.0] - 2026-09-03

### Added

- Added support for loading tickets from a CSV file.
- Added support for validating tickets against the configured validation rules.
- Added support for triaging valid tickets by category, urgency, and reason.
- Added support for exporting triaged, invalid, and needs-review tickets to separate CSV files.
- Added tests for retrying after transient errors.
- Added tests for handling refusal responses.
