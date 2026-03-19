#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import json
import os
import re
import smtplib
import sys
from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin
from urllib.request import Request, urlopen

NINDO_JOBS_URL = "https://nindo.de/jobs"
JOIN_JOBS_API_URL = "https://join.com/api/widget/jobs"
REQUEST_TIMEOUT_SECONDS = 30
USER_AGENT = "nindo-jobscrape/1.0"
ENV_FILE_PATH = Path(__file__).resolve().parent.parent / ".env"

JOBS_ASSET_PATTERN = re.compile(r"(/assets/jobs-[A-Za-z0-9_-]+\.js)")
JOIN_TOKEN_PATTERN = re.compile(r"https://join\.com/api/widget/bundle/([A-Za-z0-9._-]+)")


class ScrapeError(RuntimeError):
    pass


@dataclass(frozen=True)
class MailConfig:
    host: str
    port: int
    username: str
    password: str
    email_from: str
    email_to: list[str]
    security: str
    subject_prefix: str


@dataclass(frozen=True)
class Job:
    title: str
    url: str
    location: str | None
    employment_type: str | None
    category: str | None
    deadline: str | None

    @classmethod
    def from_api_payload(cls, payload: dict[str, Any]) -> "Job":
        return cls(
            title=str(payload.get("title") or "Untitled job"),
            url=str(payload.get("url") or "").strip(),
            location=format_location(payload),
            employment_type=clean_optional_text(payload.get("employmentType")),
            category=clean_optional_text(payload.get("category")),
            deadline=clean_optional_text(payload.get("deadline")),
        )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check https://nindo.de/jobs and send an email if jobs are available."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the email body instead of sending it.",
    )
    parser.add_argument(
        "--send-test-email",
        action="store_true",
        help="Send a sample email immediately without checking Nindo jobs.",
    )
    args = parser.parse_args()

    try:
        load_dotenv_file()
        if args.send_test_email:
            config = load_mail_config()
            subject, text_body, html_body = build_test_email_content()
            send_email(config, subject, text_body, html_body)
            print(f"Sent test email to {', '.join(config.email_to)}.")
            return 0

        jobs = collect_jobs()
        if not jobs:
            print("No Nindo jobs available.")
            return 0

        subject, text_body, html_body = build_email_content(jobs)

        if args.dry_run:
            print(subject)
            print()
            print(text_body)
            return 0

        config = load_mail_config()
        send_email(config, subject, text_body, html_body)
        print(f"Sent {len(jobs)} job(s) to {', '.join(config.email_to)}.")
        return 0
    except Exception as exc:  # pragma: no cover - top-level error reporting
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


def collect_jobs() -> list[Job]:
    page_html = fetch_text(NINDO_JOBS_URL)
    access_token = discover_access_token(page_html)
    payloads = fetch_all_job_payloads(access_token)
    return [Job.from_api_payload(payload) for payload in payloads]


def discover_access_token(page_html: str) -> str:
    direct_token_match = JOIN_TOKEN_PATTERN.search(page_html)
    if direct_token_match:
        return direct_token_match.group(1)

    asset_paths = list(dict.fromkeys(JOBS_ASSET_PATTERN.findall(page_html)))
    if not asset_paths:
        raise ScrapeError("Could not find the Nindo jobs asset bundle in the page HTML.")

    for asset_path in asset_paths:
        asset_url = urljoin(NINDO_JOBS_URL, asset_path)
        asset_js = fetch_text(asset_url)
        token_match = JOIN_TOKEN_PATTERN.search(asset_js)
        if token_match:
            return token_match.group(1)

    raise ScrapeError("Could not find the Join widget token in the Nindo jobs asset bundle.")


def fetch_all_job_payloads(access_token: str) -> list[dict[str, Any]]:
    headers = {"access-token": access_token}
    first_page = fetch_json(JOIN_JOBS_API_URL, headers=headers)
    jobs = list(first_page.get("jobs") or [])

    pagination = first_page.get("pagination") or {}
    page_count = int(pagination.get("pageCount") or 0)

    for page in range(2, page_count + 1):
        page_payload = fetch_json(JOIN_JOBS_API_URL, headers=headers, params={"page": page})
        jobs.extend(page_payload.get("jobs") or [])

    return jobs


def fetch_text(url: str, headers: dict[str, str] | None = None) -> str:
    response = http_get(url, headers=headers)
    return response.decode("utf-8")


def fetch_json(
    url: str,
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if params:
        url = f"{url}?{urlencode(params, doseq=True)}"
    response = http_get(url, headers=headers)
    return json.loads(response.decode("utf-8"))


def http_get(url: str, headers: dict[str, str] | None = None) -> bytes:
    merged_headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json, text/html;q=0.9, */*;q=0.8",
    }
    if headers:
        merged_headers.update(headers)

    request = Request(url, headers=merged_headers)

    try:
        with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            return response.read()
    except HTTPError as exc:
        raise ScrapeError(f"HTTP {exc.code} while requesting {url}") from exc
    except URLError as exc:
        raise ScrapeError(f"Could not reach {url}: {exc.reason}") from exc


def format_location(payload: dict[str, Any]) -> str | None:
    workplace_type = clean_optional_text(payload.get("workplaceType"))
    remote_type = clean_optional_text(payload.get("remoteType"))
    city = payload.get("city") if isinstance(payload.get("city"), dict) else {}
    city_name = clean_optional_text(city.get("cityName"))
    country_name = clean_optional_text(city.get("countryName"))

    city_bits = [value for value in (city_name, country_name) if value]
    city_label = ", ".join(city_bits) if city_bits else None

    if workplace_type == "REMOTE":
        if remote_type == "COUNTRY" and country_name:
            return f"Remote ({country_name})"
        return "Remote"

    if workplace_type == "HYBRID":
        return f"{city_label} (hybrid)" if city_label else "Hybrid"

    if workplace_type == "ONSITE":
        return city_label or "On-site"

    return city_label or clean_optional_text(workplace_type)


def clean_optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def load_dotenv_file(path: Path = ENV_FILE_PATH) -> None:
    if not path.is_file():
        return

    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        if "=" not in line:
            raise ValueError(f"Invalid line {line_number} in {path}: expected KEY=VALUE")

        name, value = line.split("=", 1)
        name = name.strip()
        if not name:
            raise ValueError(f"Invalid line {line_number} in {path}: missing variable name")

        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]

        os.environ.setdefault(name, value)


def build_email_content(jobs: list[Job]) -> tuple[str, str, str]:
    subject = f"{len(jobs)} Nindo job(s) available"

    text_lines = [
        f"Nindo currently has {len(jobs)} published job(s):",
        "",
    ]
    html_items: list[str] = []

    for index, job in enumerate(jobs, start=1):
        text_lines.append(f"{index}. {job.title}")
        if job.location:
            text_lines.append(f"   Location: {job.location}")
        if job.employment_type:
            text_lines.append(f"   Employment type: {job.employment_type}")
        if job.category:
            text_lines.append(f"   Category: {job.category}")
        if job.deadline:
            text_lines.append(f"   Deadline: {job.deadline}")
        if job.url:
            text_lines.append(f"   URL: {job.url}")
        text_lines.append("")

        details = []
        if job.location:
            details.append(f"Location: {html.escape(job.location)}")
        if job.employment_type:
            details.append(f"Employment type: {html.escape(job.employment_type)}")
        if job.category:
            details.append(f"Category: {html.escape(job.category)}")
        if job.deadline:
            details.append(f"Deadline: {html.escape(job.deadline)}")

        detail_html = "<br>".join(details)
        url_html = (
            f'<div><a href="{html.escape(job.url)}">{html.escape(job.url)}</a></div>'
            if job.url
            else ""
        )
        html_items.append(
            "<li>"
            f"<strong>{html.escape(job.title)}</strong>"
            f"{'<div>' + detail_html + '</div>' if detail_html else ''}"
            f"{url_html}"
            "</li>"
        )

    text_body = "\n".join(text_lines).strip()
    html_body = (
        "<html><body>"
        f"<p>Nindo currently has <strong>{len(jobs)}</strong> published job(s):</p>"
        f"<ul>{''.join(html_items)}</ul>"
        "</body></html>"
    )
    return subject, text_body, html_body


def build_test_email_content() -> tuple[str, str, str]:
    subject = "SMTP test email"
    text_body = (
        "This is a test email from the Nindo Job Watcher.\n\n"
        "If you received this message, SMTP delivery is working."
    )
    html_body = (
        "<html><body>"
        "<p>This is a test email from the <strong>Nindo Job Watcher</strong>.</p>"
        "<p>If you received this message, SMTP delivery is working.</p>"
        "</body></html>"
    )
    return subject, text_body, html_body


def load_mail_config() -> MailConfig:
    security = (os.getenv("NINDO_JOBS_SMTP_SECURITY") or "").strip().lower()
    port = int(os.getenv("NINDO_JOBS_SMTP_PORT") or 587)

    if not security:
        security = "ssl" if port == 465 else "starttls"

    if security not in {"ssl", "starttls", "none"}:
        raise ValueError("NINDO_JOBS_SMTP_SECURITY must be one of: ssl, starttls, none")

    username = require_env("NINDO_JOBS_SMTP_USERNAME")

    email_to = [
        value.strip()
        for value in require_env("NINDO_JOBS_EMAIL_TO").split(",")
        if value.strip()
    ]

    if not email_to:
        raise ValueError("NINDO_JOBS_EMAIL_TO must contain at least one recipient.")

    return MailConfig(
        host=require_env("NINDO_JOBS_SMTP_HOST"),
        port=port,
        username=username,
        password=require_env("NINDO_JOBS_SMTP_PASSWORD"),
        email_from=(os.getenv("NINDO_JOBS_EMAIL_FROM") or username).strip(),
        email_to=email_to,
        security=security,
        subject_prefix=(os.getenv("NINDO_JOBS_SUBJECT_PREFIX") or "[Nindo Jobs]").strip(),
    )


def require_env(name: str) -> str:
    value = os.getenv(name)
    if value is None or not value.strip():
        raise ValueError(f"Missing required environment variable: {name}")
    return value.strip()


def send_email(config: MailConfig, subject: str, text_body: str, html_body: str) -> None:
    message = EmailMessage()
    message["Subject"] = f"{config.subject_prefix} {subject}".strip()
    message["From"] = config.email_from
    message["To"] = ", ".join(config.email_to)
    message.set_content(text_body)
    message.add_alternative(html_body, subtype="html")

    if config.security == "ssl":
        with smtplib.SMTP_SSL(config.host, config.port, timeout=REQUEST_TIMEOUT_SECONDS) as smtp:
            smtp.login(config.username, config.password)
            smtp.send_message(message)
        return

    with smtplib.SMTP(config.host, config.port, timeout=REQUEST_TIMEOUT_SECONDS) as smtp:
        smtp.ehlo()
        if config.security == "starttls":
            smtp.starttls()
            smtp.ehlo()
        smtp.login(config.username, config.password)
        smtp.send_message(message)


if __name__ == "__main__":
    raise SystemExit(main())
