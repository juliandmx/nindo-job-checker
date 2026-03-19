# Nindo Job Watcher

This repository contains a GitHub Actions workflow that checks `https://nindo.de/jobs` every day and sends an email when Nindo has published job openings.

Mail is sent to whatever address is configured in `NINDO_JOBS_EMAIL_TO`.

## How it works

The script:

1. Loads the Nindo jobs page.
2. Finds the embedded Join widget bundle used by the site.
3. Extracts the Join access token from that bundle.
4. Fetches the current job list from Join's public widget API.
5. Sends you an email with the published jobs if at least one job exists.

As verified on March 19, 2026, the current public API response is empty, so the workflow will stay quiet until jobs appear.

## Files

- `scripts/check_nindo_jobs.py`: main scraper and mail sender
- `.github/workflows/check-nindo-jobs.yml`: scheduled GitHub Actions workflow
- `tests/test_check_nindo_jobs.py`: basic regression tests for token extraction and email formatting

## GitHub setup

After pushing this repository to GitHub, add these repository secrets:

- `NINDO_JOBS_EMAIL_TO`: your personal email address
- `NINDO_JOBS_SMTP_HOST`: SMTP server host
- `NINDO_JOBS_SMTP_PORT`: SMTP port, for example `587` or `465`
- `NINDO_JOBS_SMTP_USERNAME`: SMTP username
- `NINDO_JOBS_SMTP_PASSWORD`: SMTP password or app password

Optional secrets:

- `NINDO_JOBS_EMAIL_FROM`: sender address, defaults to `NINDO_JOBS_SMTP_USERNAME`
- `NINDO_JOBS_SMTP_SECURITY`: `starttls`, `ssl`, or `none`
- `NINDO_JOBS_SUBJECT_PREFIX`: defaults to `[Nindo Jobs]`

If you use Gmail, use an app password rather than your normal account password.

## Running locally

The script will automatically load a local `.env` file from the repository root if one exists. A `.env.example` template is included.

Set `NINDO_JOBS_EMAIL_TO` in `.env` to choose the recipient address.

Dry run without sending mail:

```bash
python scripts/check_nindo_jobs.py --dry-run
```

Send a sample email immediately to verify SMTP delivery:

```bash
python scripts/check_nindo_jobs.py --send-test-email
```

Run tests:

```bash
python -m unittest discover -s tests
```

## Schedule

The workflow runs daily at `07:00 UTC` and can also be started manually with `workflow_dispatch`.
