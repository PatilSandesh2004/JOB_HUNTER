"""Real headless-Chromium runs against the local fixture site."""

import pytest

from ai_service.app.integrations.browser.form_filler import (
    ANSWER_BANK,
    ApplicantPacket,
    FillOutcome,
    classify_field,
    fill_application,
)
from ai_service.app.services.screening.answer_bank import AnswerBook, normalize_question
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
    assert result.screenshot_path == str(tmp_path / "shot-filled.png") and (tmp_path / "shot-filled.png").exists()
    steps = [e["step"] for e in result.events]
    assert steps == ["Opened the application page", "Found the application form", "Filled the form"]
    assert result.events[-1]["screenshot"] == "shot-filled.png"


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


async def test_screening_questions_are_reported_then_answered_from_the_bank(packet, tmp_path):
    with FixtureSite() as site:
        first = await fill_application(
            f"{site.base}/apply-screening", packet, submit=True, screenshot_path=tmp_path / "a.png"
        )
        assert site.submissions == []  # unanswered required questions block auto-submit
        assert first.outcome == FillOutcome.NEEDS_MANUAL
        questions = {q["label"]: q for q in first.unanswered}
        assert set(questions) == {"Are you legally authorized to work in India? *", "How did you hear about us? *"}
        assert questions["Are you legally authorized to work in India? *"]["kind"] == "radio"
        assert questions["Are you legally authorized to work in India? *"]["options"] == ["Yes", "No"]
        # The sponsorship radio is answered from the profile, gender is declined, both without the bank.
        assert first.filled_fields["Will you require visa sponsorship? *"] == "requires_sponsorship"
        assert first.filled_fields["Gender (voluntary)"] == ANSWER_BANK

        # The user answers once; the next run fills everything and submits.
        packet.answers = AnswerBook(
            saved={
                normalize_question("Are you legally authorized to work in India?"): "Yes",
                normalize_question("How did you hear about us?"): "LinkedIn",
            }
        )
        second = await fill_application(
            f"{site.base}/apply-screening", packet, submit=True, screenshot_path=tmp_path / "b.png"
        )
        body = site.submissions[0]
    assert second.outcome == FillOutcome.SUBMITTED, second.message
    assert second.unanswered == []
    assert b'name="auth"\r\n\r\ny' in body
    assert b'name="sponsor_radio"\r\n\r\nno' in body
    assert b'name="gender"\r\n\r\nDecline to self-identify' in body
    assert b'name="hear"\r\n\r\nLinkedIn' in body
    steps = [e["step"] for e in second.events]
    assert steps[-2:] == ["Clicked Submit", "Confirmation received"]
    assert (tmp_path / "b-submitted.png").exists()
