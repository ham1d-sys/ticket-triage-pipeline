# Changelog

All notable changes to this project are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres
to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## Unreleased

## [v0.1.5] - 2026-09-06

### Changed

- Simplified retry handling by catching the broader `APIConnectionError` base class instead of the previously listed `APITimeoutError` subclass.

## [v0.1.4] - 2026-09-06

### Changed

- Moved client instantiation in `triage.py` from the top level into a function.

## [v0.1.3] - 2026-09-06

### Added

- Added pyproject.toml

### Fixed

- Fixed the consecutive-error logic to abort only after `abort_count` consecutive failures instead of any failure after that threshold.

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