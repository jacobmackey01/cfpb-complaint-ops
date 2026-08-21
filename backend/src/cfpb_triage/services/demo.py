from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from cfpb_triage.schemas import CaseRecord, SourceKind

DEMO_NOTICE = (
    "Synthetic offline demonstration data. These records are not CFPB complaints "
    "and must not be presented as live or public-source observations."
)


def synthetic_cases(as_of: date | None = None) -> list[CaseRecord]:
    as_of = as_of or datetime.now(timezone.utc).date()
    rows = [
        (
            "DEMO-001",
            2,
            "Credit reporting or other personal consumer reports",
            "Incorrect information on your report",
            "I found an account on my credit report that I do not recognize. I disputed it twice and the entry remains.",
            False,
            0.54,
            True,
        ),
        (
            "DEMO-002",
            4,
            "Checking or savings account",
            "Managing an account",
            "My direct deposit was available two days late and scheduled payments were returned.",
            True,
            0.91,
            False,
        ),
        (
            "DEMO-003",
            6,
            "Credit card",
            "Problem with a purchase shown on your statement",
            "A purchase I cancelled is still on the statement. The merchant confirmed cancellation but the charge remains.",
            False,
            0.78,
            True,
        ),
        (
            "DEMO-004",
            9,
            "Mortgage",
            "Trouble during payment process",
            "The servicer applied my payment to fees instead of principal and has not supplied a corrected statement.",
            True,
            0.86,
            False,
        ),
        (
            "DEMO-005",
            12,
            "Debt collection",
            "Attempts to collect debt not owed",
            "A collector continues to call about a debt belonging to another person with a similar name.",
            None,
            0.49,
            True,
        ),
        (
            "DEMO-006",
            16,
            "Vehicle loan or lease",
            "Managing the loan or lease",
            "The portal shows a late balance even though my bank records show the payment cleared on time.",
            True,
            0.74,
            True,
        ),
        (
            "DEMO-007",
            20,
            "Money transfer, virtual currency, or money service",
            "Money was not available when promised",
            "A transfer is marked complete but the recipient has not received the funds after five business days.",
            False,
            0.83,
            True,
        ),
        (
            "DEMO-008",
            25,
            "Student loan",
            "Dealing with your lender or servicer",
            "My income-driven repayment documents were acknowledged but the payment amount was not updated.",
            True,
            0.89,
            False,
        ),
    ]
    return [
        CaseRecord(
            complaint_id=complaint_id,
            date_received=as_of - timedelta(days=days_ago),
            product=product,
            issue=issue,
            company="Synthetic Demo Company",
            state="NA",
            submitted_via="Synthetic demo",
            timely=timely,
            narrative=narrative,
            has_narrative=True,
            predicted_product=product,
            confidence=confidence,
            abstained=abstained,
            requires_manual_attention=abstained or timely is False,
            attention_reasons=(
                (["uncertain_model_route"] if abstained else [])
                + (["untimely_company_response"] if timely is False else [])
            ),
            source_kind=SourceKind.SYNTHETIC_DEMO,
        )
        for complaint_id, days_ago, product, issue, narrative, timely, confidence, abstained in rows
    ]
