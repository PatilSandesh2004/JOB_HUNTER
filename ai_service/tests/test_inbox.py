"""Job-alert emails -> jobs; employer emails -> application status; read-only IMAP access."""

import email.message
import hashlib
import imaplib

import httpx
import pytest

from ai_service.app.database.session import AsyncSessionLocal
from ai_service.app.integrations.mail import imap_reader
from ai_service.app.integrations.mail.imap_reader import ImapReader, MailError, MailMessage
from ai_service.app.schemas.application import ApplicationStatus as S
from ai_service.app.services.inbox.inbox_service import InboxNotConfiguredError, InboxService
from ai_service.app.services.inbox.job_alerts import alert_source, canonical_job_url, parse_job_alert
from ai_service.app.services.inbox.status_updates import company_key, match_application, names_company, next_status
from ai_service.tests.fakes import RESUME

LINKEDIN_ALERT = """<html><head><style>.x{color:red}</style></head><body>
<table>
 <tr><td><a href="https://www.linkedin.com/comm/jobs/view/4012345678/?trackingId=abc&refId=x">
       <img src="logo.png"></a></td>
     <td><a href="https://www.linkedin.com/comm/jobs/view/4012345678/?trackingId=abc">Senior AI Engineer</a>
         <p>Acme</p><p>Bengaluru, Karnataka, India</p><p>Actively recruiting</p><p>3 days ago</p></td></tr>
 <tr><td><a href="https://www.linkedin.com/comm/jobs/view/4099999999/?trackingId=def">Machine Learning Engineer</a>
         <p>Beta Labs &middot; Remote</p><p>Easy Apply</p></td></tr>
 <tr><td><a href="https://www.linkedin.com/comm/jobs/search/?keywords=ai">See all jobs</a>
         <a href="https://www.linkedin.com/comm/psettings/email-unsubscribe">Unsubscribe</a></td></tr>
</table></body></html>"""

NAUKRI_ALERT = """<div><a href="https://www.naukri.com/job-listings-ai-engineer-gamma-bengaluru-3-to-5-years-061025000123?src=jobsearch">
AI Engineer</a><span>Gamma Technologies</span><span>3-5 Yrs</span><span>Bengaluru</span>
<a href="https://click.naukri.com/r?u=abc">Apply</a></div>"""

INDEED_ALERT = """<p><a href="https://cts.indeed.com/v3/H4sIAAAA">Backend Engineer (Python)</a></p>
<p>Delta Corp</p><p>Pune, Maharashtra</p><p>&#8377;12,00,000 a year</p>"""


def indeed_redirects(request: httpx.Request) -> httpx.Response:
    if request.url.host == "cts.indeed.com":
        return httpx.Response(302, headers={"location": "https://in.indeed.com/rc/clk?jk=0a1b2c3d4e5f6a7b&from=ja"})
    if request.url.path == "/rc/clk":
        return httpx.Response(302, headers={"location": "/viewjob?jk=0a1b2c3d4e5f6a7b"})
    return httpx.Response(200)


def test_alert_senders_and_canonical_urls():
    assert alert_source("LinkedIn Job Alerts <jobalerts-noreply@linkedin.com>") == "linkedin"
    assert alert_source("Indeed <alert@indeed.com>") == "indeed"
    assert alert_source("Naukri <info@mailer.naukri.com>") == "naukri"
    assert alert_source("Fake <linkedin.com@phish.example>") is None
    assert (
        canonical_job_url("linkedin", "https://www.linkedin.com/comm/jobs/view/4012345678/?trackingId=abc")
        == "https://www.linkedin.com/jobs/view/4012345678"
    )
    assert (
        canonical_job_url("naukri", "https://www.naukri.com/job-listings-ai-engineer-x-061025000123?src=alert")
        == "https://www.naukri.com/job-listings-ai-engineer-x-061025000123"
    )
    assert (
        canonical_job_url("indeed", "https://in.indeed.com/rc/clk?jk=0a1b2c3d4e5f6a7b&from=ja")
        == "https://in.indeed.com/viewjob?jk=0a1b2c3d4e5f6a7b"
    )
    assert canonical_job_url("linkedin", "https://www.linkedin.com/comm/jobs/search/?keywords=ai") is None


async def test_parses_linkedin_alert():
    jobs = await parse_job_alert("linkedin", LINKEDIN_ALERT, "")
    assert [(j.url, j.title, j.company, j.location) for j in jobs] == [
        ("https://www.linkedin.com/jobs/view/4012345678", "Senior AI Engineer", "Acme", "Bengaluru, Karnataka, India"),
        ("https://www.linkedin.com/jobs/view/4099999999", "Machine Learning Engineer", "Beta Labs · Remote", None),
    ]


async def test_parses_naukri_alert_and_skips_unresolvable_trackers():
    jobs = await parse_job_alert("naukri", NAUKRI_ALERT, "")
    assert len(jobs) == 1
    job = jobs[0]
    assert job.url == "https://www.naukri.com/job-listings-ai-engineer-gamma-bengaluru-3-to-5-years-061025000123"
    assert (job.title, job.company, job.location) == ("AI Engineer", "Gamma Technologies", "Bengaluru")


async def test_resolves_indeed_tracking_links():
    assert await parse_job_alert("indeed", INDEED_ALERT, "") == []  # without resolving, the link is opaque
    async with httpx.AsyncClient(transport=httpx.MockTransport(indeed_redirects)) as client:
        jobs = await parse_job_alert("indeed", INDEED_ALERT, "", resolve=client)
    assert [(j.url, j.title, j.company, j.location) for j in jobs] == [
        (
            "https://in.indeed.com/viewjob?jk=0a1b2c3d4e5f6a7b",
            "Backend Engineer (Python)",
            "Delta Corp",
            "Pune, Maharashtra",
        )
    ]


async def test_parses_plain_text_alerts():
    text = (
        "Your job alert for data scientist\n\n"
        "Data Scientist\nOmega Analytics\nHyderabad, India\nView job: https://www.linkedin.com/comm/jobs/view/4055555555/\n\n"
        "ML Engineer\nSigma\nRemote\nView job: https://www.linkedin.com/comm/jobs/view/4066666666/\n"
    )
    jobs = await parse_job_alert("linkedin", "", text)
    assert [(j.title, j.company, j.location) for j in jobs] == [
        ("Data Scientist", "Omega Analytics", "Hyderabad, India"),
        ("ML Engineer", "Sigma", "Remote"),
    ]


class _App:
    def __init__(self, company, status, updated=0):
        from datetime import UTC, datetime, timedelta

        self.company, self.status = company, status
        self.updated_at = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=updated)


def test_status_matching_rules():
    assert company_key("Acme Technologies Pvt. Ltd.") == "acme"
    assert names_company("Acme Corp", "Acme Recruiting <jobs@acme.com>", "Your application")
    assert names_company("Acme Corp", "no-reply@acmecorp.greenhouse-mail.io", "Update")  # squashed domain
    assert not names_company("Acme", "Newsletter <news@example.com>", "This week in tech")
    assert not names_company("AI", "x@ai.com", "hi")  # too short to match safely

    apps = [_App("Acme", "APPLIED"), _App("Beta", "APPLIED"), _App("Acme", "AWAITING_CONFIRMATION", updated=2)]
    assert match_application(apps, "Acme <hr@acme.com>", "Interview invitation").updated_at.day == 3  # latest
    assert match_application(apps, "Talent <hr@acme.com>", "Acme and Beta partnership") is None  # ambiguous
    assert match_application([_App("Acme", "DISMISSED")], "hr@acme.com", "Acme") is None  # not tracked

    assert next_status(S.APPLIED, S.INTERVIEW) == S.INTERVIEW
    assert next_status(S.INTERVIEW, S.APPLIED) is None  # never backwards
    assert next_status(S.REJECTED, S.INTERVIEW) is None
    assert next_status(S.AWAITING_CONFIRMATION, S.APPLIED) == S.APPLIED


def _mail(sender: str, subject: str, html: str = "", text: str = "", key: str | None = None) -> MailMessage:
    return MailMessage(
        key=key or hashlib.sha256(f"{sender}{subject}".encode()).hexdigest(),
        sender=sender,
        subject=subject,
        received_at=None,
        html=html,
        text=text,
    )


class FakeReader:
    """Applies the service's `want` filter like the IMAP reader does, and records what it was asked for."""

    def __init__(self, messages: list[MailMessage]) -> None:
        self.messages, self.downloaded = messages, []

    async def fetch(self, since_days, limit, want):
        chosen = [m for m in self.messages if want(m.key, m.sender, m.subject)]
        self.downloaded.append([m.subject for m in chosen])
        return chosen


async def test_inbox_check_adds_alert_jobs_and_updates_statuses(client):
    from ai_service.app.services.notifications.alerts import MatchAlertService

    await client.post("/api/v1/candidates/me/resume", files={"file": ("cv.txt", RESUME, "text/plain")})
    results = (
        await client.post("/api/v1/search", json={"roles": ["Backend Engineer"], "strict_location": False})
    ).json()["results"]
    acme = next(r["job"] for r in results if r["job"]["company"] == "Acme")
    app_id = (await client.post("/api/v1/applications", json={"job_id": acme["id"], "mode": "manual"})).json()["id"]

    messages = [
        _mail("LinkedIn Job Alerts <jobalerts-noreply@linkedin.com>", "AI Engineer: 2 new jobs", html=LINKEDIN_ALERT),
        _mail(
            "Acme Talent <talent@acme.com>",
            "Your application to Acme",
            text="Thank you for applying. Unfortunately, we will not be moving forward with your application.",
        ),
        _mail("Weekly digest <news@example.com>", "Top stories", text="Acme raised money. Unfortunately..."),
    ]
    reader = FakeReader(messages)
    service = InboxService(AsyncSessionLocal, reader, notifier=MatchAlertService(85))
    report = await service.check()

    assert reader.downloaded == [["AI Engineer: 2 new jobs", "Your application to Acme"]]  # digest never downloaded
    assert (report["job_alerts"], report["jobs_found"], report["jobs_new"]) == (1, 2, 2)
    assert report["status_updates"] == [
        {
            "application_id": app_id,
            "company": "Acme",
            "job_title": acme["title"],
            "from": "AWAITING_CONFIRMATION",
            "to": "REJECTED",
            "phrase": "Unfortunately",
        }
    ]
    app = (await client.get(f"/api/v1/applications/{app_id}")).json()
    assert app["status"] == "REJECTED" and app["events"][-1]["step"] == "Email: Rejected"

    jobs = {j["job"]["title"]: j for j in (await client.get("/api/v1/jobs")).json()}
    alert_job = jobs["Senior AI Engineer"]
    assert alert_job["job"]["source"] == "email_linkedin" and alert_job["job"]["company"] == "Acme"
    assert alert_job["match"] is not None and alert_job["job"]["auto_apply_supported"] is False

    # Already processed: a second check downloads nothing and changes nothing.
    again = await service.check()
    assert reader.downloaded[-1] == [] and again["jobs_new"] == 0 and again["status_updates"] == []
    status = await service.status()
    assert status["configured"] and {r["kind"] for r in status["recent"]} == {"job_alert", "status_update"}
    assert all(r["subject"] != "Top stories" for r in status["recent"])


async def test_inbox_without_settings_explains_what_to_do(client):
    service = InboxService(AsyncSessionLocal, None)
    assert (await service.status())["configured"] is False
    with pytest.raises(InboxNotConfiguredError, match="IMAP_USER"):
        await service.check()


class FakeImap:
    """Mimics imaplib.IMAP4_SSL's responses for two messages."""

    instances: list["FakeImap"] = []

    def __init__(self, host, port, timeout=None):
        self.calls: list[tuple] = []
        FakeImap.instances.append(self)

    def login(self, user, password):
        if password != "app-password":
            raise imaplib.IMAP4.error("AUTHENTICATIONFAILED")

    def select(self, folder, readonly=False):
        self.calls.append(("select", folder, readonly))
        return "OK", [b"2"]

    def uid(self, command, *args):
        self.calls.append(("uid", command, *args))
        if command == "SEARCH":
            return "OK", [b"101 102"]
        if "HEADER.FIELDS" in args[-1]:
            return "OK", [
                (
                    b"1 (UID 101 BODY[HEADER.FIELDS (MESSAGE-ID FROM SUBJECT DATE)] {80}",
                    _raw("a@linkedin.com", "Alert"),
                ),
                b")",
                (b"2 (UID 102 BODY[HEADER.FIELDS (MESSAGE-ID FROM SUBJECT DATE)] {80}", _raw("friend@x.com", "Hi")),
                b")",
            ]
        return "OK", [(b"1 (UID 101 BODY[] {200}", _raw("a@linkedin.com", "Alert", "<a href='x'>Job</a>")), b")"]

    def logout(self):
        self.calls.append(("logout",))


def _raw(sender: str, subject: str, html: str = "") -> bytes:
    message = email.message.EmailMessage()
    message["From"], message["Subject"], message["Message-ID"] = sender, subject, f"<{subject}@example.com>"
    message["Date"] = "Tue, 06 Oct 2026 10:00:00 +0000"
    message.set_content("plain body")
    if html:
        message.add_alternative(html, subtype="html")
    return message.as_bytes()


async def test_imap_reader_is_read_only_and_downloads_only_wanted_messages(monkeypatch):
    monkeypatch.setattr(imap_reader.imaplib, "IMAP4_SSL", FakeImap)
    reader = ImapReader("imap.example.com", 993, "me@example.com", "app-password")
    messages = await reader.fetch(7, 300, lambda key, sender, subject: "linkedin" in sender)

    assert [(m.sender, m.subject, m.html.strip(), m.text.strip()) for m in messages] == [
        ("a@linkedin.com", "Alert", "<a href='x'>Job</a>", "plain body")
    ]
    assert messages[0].received_at.year == 2026 and len(messages[0].key) == 64
    calls = FakeImap.instances[-1].calls
    assert ("select", '"INBOX"', True) in calls  # read-only
    fetches = [c for c in calls if c[:2] == ("uid", "FETCH")]
    assert fetches[-1][2] == "101" and all("PEEK" in c[3] for c in fetches)  # nothing marked as read
    assert calls[-1] == ("logout",)

    with pytest.raises(MailError, match="app password"):
        await ImapReader("imap.example.com", 993, "me@example.com", "wrong").fetch(7, 300, lambda *a: True)
