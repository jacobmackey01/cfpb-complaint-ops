from __future__ import annotations

from cfpb_triage.data.snapshot import CFPBSnapshotClient


def test_default_cfpb_headers_are_waf_compatible_and_traceable() -> None:
    client = CFPBSnapshotClient(retries=0)
    try:
        user_agent = client.client.headers["user-agent"]
        assert user_agent.startswith("Mozilla/5.0 (compatible; CFPBComplaintResearch/")
        assert "github.com/jacobmackey01" in user_agent
        assert client.client.headers["referer"].startswith(
            "https://www.consumerfinance.gov/data-research/consumer-complaints/"
        )
    finally:
        client.close()
