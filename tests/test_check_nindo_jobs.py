from __future__ import annotations

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.check_nindo_jobs import (
    Job,
    build_email_content,
    build_test_email_content,
    discover_access_token,
    format_location,
    load_dotenv_file,
)


class DiscoverAccessTokenTests(unittest.TestCase):
    def test_extracts_token_from_jobs_asset(self) -> None:
        page_html = '<link rel="modulepreload" href="/assets/jobs-ABC123.js">'

        def fake_fetch_text(_url: str) -> str:
            return (
                "const x = "
                '"https://join.com/api/widget/bundle/header.payload.signature";'
            )

        from scripts import check_nindo_jobs

        original_fetch_text = check_nindo_jobs.fetch_text
        check_nindo_jobs.fetch_text = fake_fetch_text
        try:
            self.assertEqual(
                discover_access_token(page_html),
                "header.payload.signature",
            )
        finally:
            check_nindo_jobs.fetch_text = original_fetch_text


class FormatLocationTests(unittest.TestCase):
    def test_formats_remote_country_jobs(self) -> None:
        payload = {
            "workplaceType": "REMOTE",
            "remoteType": "COUNTRY",
            "city": {"countryName": "Germany"},
        }
        self.assertEqual(format_location(payload), "Remote (Germany)")

    def test_formats_hybrid_jobs(self) -> None:
        payload = {
            "workplaceType": "HYBRID",
            "city": {"cityName": "Berlin", "countryName": "Germany"},
        }
        self.assertEqual(format_location(payload), "Berlin, Germany (hybrid)")


class BuildEmailContentTests(unittest.TestCase):
    def test_includes_job_fields(self) -> None:
        jobs = [
            Job(
                title="Backend Engineer",
                url="https://example.com/jobs/backend",
                location="Berlin, Germany",
                employment_type="Full-time",
                category="Engineering",
                deadline="2026-04-01",
            )
        ]
        subject, text_body, html_body = build_email_content(jobs)

        self.assertEqual(subject, "1 Nindo job(s) available")
        self.assertIn("Backend Engineer", text_body)
        self.assertIn("Berlin, Germany", text_body)
        self.assertIn("Engineering", text_body)
        self.assertIn("https://example.com/jobs/backend", html_body)


class LoadDotenvFileTests(unittest.TestCase):
    def test_loads_values_from_dotenv_file(self) -> None:
        with TemporaryDirectory() as temp_dir:
            dotenv_path = Path(temp_dir) / ".env"
            dotenv_path.write_text(
                "\n".join(
                    [
                        "# Comment",
                        "NINDO_JOBS_EMAIL_TO=julian@dammdesign.de",
                        'NINDO_JOBS_SUBJECT_PREFIX="[Nindo Jobs]"',
                    ]
                ),
                encoding="utf-8",
            )

            original_email_to = os.environ.get("NINDO_JOBS_EMAIL_TO")
            original_prefix = os.environ.get("NINDO_JOBS_SUBJECT_PREFIX")
            try:
                os.environ.pop("NINDO_JOBS_EMAIL_TO", None)
                os.environ.pop("NINDO_JOBS_SUBJECT_PREFIX", None)

                load_dotenv_file(dotenv_path)

                self.assertEqual(os.environ["NINDO_JOBS_EMAIL_TO"], "julian@dammdesign.de")
                self.assertEqual(os.environ["NINDO_JOBS_SUBJECT_PREFIX"], "[Nindo Jobs]")
            finally:
                restore_env("NINDO_JOBS_EMAIL_TO", original_email_to)
                restore_env("NINDO_JOBS_SUBJECT_PREFIX", original_prefix)

    def test_does_not_override_existing_environment_variables(self) -> None:
        with TemporaryDirectory() as temp_dir:
            dotenv_path = Path(temp_dir) / ".env"
            dotenv_path.write_text(
                "NINDO_JOBS_EMAIL_TO=from-dotenv@example.com\n",
                encoding="utf-8",
            )

            original_email_to = os.environ.get("NINDO_JOBS_EMAIL_TO")
            try:
                os.environ["NINDO_JOBS_EMAIL_TO"] = "from-env@example.com"

                load_dotenv_file(dotenv_path)

                self.assertEqual(os.environ["NINDO_JOBS_EMAIL_TO"], "from-env@example.com")
            finally:
                restore_env("NINDO_JOBS_EMAIL_TO", original_email_to)


class BuildTestEmailContentTests(unittest.TestCase):
    def test_builds_sample_email(self) -> None:
        subject, text_body, html_body = build_test_email_content()

        self.assertEqual(subject, "SMTP test email")
        self.assertIn("test email", text_body.lower())
        self.assertIn("smtp delivery is working", text_body.lower())
        self.assertIn("<strong>Nindo Job Watcher</strong>", html_body)


def restore_env(name: str, value: str | None) -> None:
    if value is None:
        os.environ.pop(name, None)
        return
    os.environ[name] = value


if __name__ == "__main__":
    unittest.main()
