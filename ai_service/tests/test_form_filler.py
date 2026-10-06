"""Real headless-Chromium runs against the local fixture site."""

import pytest

from ai_service.app.integrations.browser.form_filler import (
    ApplicantPacket,
    FillOutcome,
    classify_field,
    fill_application,
)
from ai_service.tests.fixture_site import FixtureSite


@pytest.fixture
def packet(tmp_path) -> ApplicantPacket:
    resume = tmp_path / "resume.pdf"
    resume.write_bytes(b"%PDF-1.4 test resume")
    return ApplicantPacket(
        full_name="Asha Rao",
        first_name="Asha",
        last_name="Rao",
        email="asha@example.com",
        phone="+91 98765 43210",
        linkedin_url="https://linkedin.com/in/asha-rao",
        cover_letter="Dear Hiring Team, ...",
        resume_path=str(resume),
        requires_sponsorship=False,
    )


@pytest.mark.parametrize(
    ("descriptor", "kind", "expected"),
    [
        ("first_name | fn | First Name *", "text", "first_name"),
        ("email | Email *", "email", "email"),
        ("ref_company | Company name of your referrer", "text", None),
        ("username | Username", "text", None),
        ("resume | Resume/CV *", "file", "resume"),
        ("q1 | Will you require visa sponsorship?", "select", "requires_sponsorship"),
        ("cover_letter | Cover Letter", "textarea", "cover_letter"),
        ("name | Full name", "text", "full_name"),
        ("comp | What are your compensation requirements for this location?", "text", "expected_salary"),
        ("ctc | Expected CTC (INR)", "text", "expected_salary"),
        ("np | Notice period", "text", "notice_period"),
        ("city | What city are you located in?", "text", None),
    ],
)
def test_classify_field(descriptor, kind, expected):
    assert classify_field(descriptor, kind) == expected


async def test_fill_without_submit(packet, tmp_path):
    with FixtureSite() as site:
        result = await fill_application(
            f"{site.base}/apply", packet, submit=False, screenshot_path=tmp_path / "shot.png"
        )
        assert site.submissions == []  # never submits in preview mode
    assert result.outcome == FillOutcome.FILLED, result.message
    assert set(result.filled_fields.values()) == {
        "first_name",
        "last_name",
        "email",
        "phone",
        "linkedin_url",
        "resume",
        "cover_letter",
        "requires_sponsorship",
    }
    assert result.missing_required == []
    assert (tmp_path / "shot.png").exists()


async def test_submit_detects_confirmation(packet, tmp_path):
    with FixtureSite() as site:
        result = await fill_application(f"{site.base}/apply", packet, submit=True, screenshot_path=tmp_path / "s.png")
        assert len(site.submissions) == 1
        body = site.submissions[0]
    assert result.outcome == FillOutcome.SUBMITTED, result.message
    assert "Thank you for applying" in result.confirmation
    assert b"asha@example.com" in body and b"Rao" in body
    # The real tel input got the number, not the country-code search box that precedes it.
    assert b'name="phone"\r\n\r\n+91 98765 43210' in body
    assert b'name="phone_country_search"\r\n\r\n\r\n' in body
    assert b'name="comp"\r\n\r\n\r\n' in body


async def test_required_consent_blocks_auto_submit(packet, tmp_path):
    with FixtureSite() as site:
        result = await fill_application(
            f"{site.base}/apply-consent", packet, submit=True, screenshot_path=tmp_path / "s.png"
        )
        assert site.submissions == []
    assert result.outcome == FillOutcome.NEEDS_MANUAL
    assert any("privacy policy" in m for m in result.missing_required)


async def test_follows_apply_link_from_landing_page(packet, tmp_path):
    with FixtureSite() as site:
        result = await fill_application(
            f"{site.base}/landing", packet, submit=False, screenshot_path=tmp_path / "s.png"
        )
    assert result.outcome == FillOutcome.FILLED
    assert "email" in result.filled_fields.values()


async def test_page_without_form_needs_manual(packet, tmp_path):
    with FixtureSite() as site:
        result = await fill_application(f"{site.base}/no-form", packet, submit=True, screenshot_path=tmp_path / "s.png")
    assert result.outcome == FillOutcome.NEEDS_MANUAL
    assert "No application form" in result.message


async def test_fills_salary_from_profile(packet, tmp_path):
    packet.expected_salary = "30 LPA"
    with FixtureSite() as site:
        await fill_application(f"{site.base}/apply", packet, submit=True, screenshot_path=tmp_path / "s.png")
        body = site.submissions[0]
    assert b'name="comp"\r\n\r\n30 LPA' in body
