"""End-to-end API flow: profile -> resume -> search -> apply (preview) -> approve -> submitted."""

from ai_service.tests.fakes import RESUME


async def test_full_application_flow(client):
    # 1. Applying before a profile exists is refused.
    search = await client.post("/api/v1/search", json={"roles": ["Backend Engineer"], "locations": ["Bengaluru"]})
    assert search.status_code == 200
    assert [r["job"]["company"] for r in search.json()["results"]] == ["Acme"]  # only the Bengaluru job
    job_id = search.json()["results"][0]["job"]["id"]
    assert (await client.post("/api/v1/applications", json={"job_id": job_id})).status_code == 409

    # 2. Upload resume -> profile; then set preferences.
    upload = await client.post("/api/v1/candidates/me/resume", files={"file": ("cv.txt", RESUME, "text/plain")})
    assert upload.status_code == 200, upload.text
    profile = upload.json()
    assert profile["email"] == "asha.rao@example.com"
    assert profile["resume_filename"].endswith(".txt")
    profile["preferences"]["preferred_roles"] = ["AI Engineer"]
    assert (await client.put("/api/v1/candidates/me", json=profile)).status_code == 200

    # 3. Search again: results are scored against the profile and persisted.
    search = (await client.post("/api/v1/search", json={"roles": ["AI Engineer"]})).json()
    top = search["results"][0]
    assert top["job"]["title"] == "AI Engineer" and top["match"]["overall_match"] > 60
    stored = (await client.get("/api/v1/jobs")).json()
    assert {j["job"]["id"] for j in stored} >= {r["job"]["id"] for r in search["results"]}

    # 4. Create application -> queued preview fill -> awaiting approval, nothing submitted.
    created = await client.post("/api/v1/applications", json={"job_id": top["job"]["id"]})
    assert created.status_code == 202
    assert created.json()["status"] == "PROCESSING"
    app_id = created.json()["id"]
    assert await client.runner.run_due_once() == 1
    application = (await client.get(f"/api/v1/applications/{app_id}")).json()
    assert application["status"] == "PENDING_APPROVAL"
    assert application["cover_letter_source"] == "template"  # LLM offline in tests
    assert "Asha Rao" in application["cover_letter"]
    assert client.filler.calls[-1]["submit"] is False

    # 5. Edit cover letter, approve -> agent submits with the edited letter.
    await client.patch(f"/api/v1/applications/{app_id}", json={"cover_letter": "Edited letter"})
    approved = await client.post(f"/api/v1/applications/{app_id}/approve")
    assert approved.status_code == 202
    assert approved.json()["status"] == "SUBMITTING"
    await client.runner.run_due_once()
    final = (await client.get(f"/api/v1/applications/{app_id}")).json()
    assert final["status"] == "APPLIED"
    assert final["applied_at"] is not None
    assert client.filler.calls[-1]["submit"] is True
    assert client.filler.calls[-1]["packet"].cover_letter == "Edited letter"

    # 6. Already applied: approving again is a conflict, duplicates are not created.
    assert (await client.post(f"/api/v1/applications/{app_id}/approve")).status_code == 409
    again = await client.post("/api/v1/applications", json={"job_id": top["job"]["id"]})
    assert again.json()["id"] == app_id


async def test_manual_apply_flow(client):
    await client.post("/api/v1/candidates/me/resume", files={"file": ("cv.txt", RESUME, "text/plain")})
    results = (
        await client.post("/api/v1/search", json={"roles": ["Backend Engineer"], "strict_location": False})
    ).json()["results"]
    by_company = {r["job"]["company"]: r["job"] for r in results}

    # Remotive pages block automation: agent modes are refused, manual is offered.
    remotive = by_company["Remote First Inc"]
    assert remotive["auto_apply_supported"] is False
    refused = await client.post("/api/v1/applications", json={"job_id": remotive["id"], "mode": "auto"})
    assert refused.status_code == 409 and "Apply manually" in refused.json()["detail"]

    calls_before = len(client.filler.calls)
    manual = await client.post("/api/v1/applications", json={"job_id": remotive["id"], "mode": "manual"})
    assert manual.status_code == 202
    await client.runner.run_due_once()
    app = (await client.get(f"/api/v1/applications/{manual.json()['id']}")).json()
    assert app["status"] == "AWAITING_CONFIRMATION" and app["mode"] == "manual"
    assert app["cover_letter"]  # drafted for pasting into the company form
    assert len(client.filler.calls) == calls_before  # the browser agent never ran

    confirmed = await client.patch(f"/api/v1/applications/{app['id']}", json={"status": "APPLIED"})
    assert confirmed.json()["status"] == "APPLIED" and confirmed.json()["applied_at"]

    # Switching an agent-prepared application to manual keeps the same record.
    acme = by_company["Acme"]
    assert acme["auto_apply_supported"] is True
    prepared = (await client.post("/api/v1/applications", json={"job_id": acme["id"]})).json()
    busy = await client.post("/api/v1/applications", json={"job_id": acme["id"], "mode": "manual"})
    assert busy.status_code == 409  # the agent has not run yet
    await client.runner.run_due_once()
    switched = (await client.post("/api/v1/applications", json={"job_id": acme["id"], "mode": "manual"})).json()
    assert switched["id"] == prepared["id"] and switched["status"] == "AWAITING_CONFIRMATION"
    dismissed = await client.patch(f"/api/v1/applications/{prepared['id']}", json={"status": "DISMISSED"})
    assert dismissed.json()["status"] == "DISMISSED"


async def test_search_from_profile_needs_roles_or_resume(client):
    response = await client.post("/api/v1/search", json={})
    # Either derived from the stored profile (200) or a clear 400 when there is nothing to go on.
    assert response.status_code in (200, 400)
    if response.status_code == 200:
        assert response.json()["roles"]


async def test_health_reports_components(client):
    body = (await client.get("/api/v1/health")).json()
    assert body["components"]["database"]["ok"] is True
    assert body["components"]["llm"]["ok"] is False


async def test_resume_upload_validation(client):
    bad = await client.post(
        "/api/v1/candidates/me/resume", files={"file": ("cv.exe", b"x", "application/octet-stream")}
    )
    assert bad.status_code == 400
    empty = await client.post("/api/v1/candidates/me/resume", files={"file": ("cv.txt", b" ", "text/plain")})
    assert empty.status_code == 422


async def test_api_token_required_when_configured(client, monkeypatch):
    from ai_service.app.core.config import settings

    monkeypatch.setattr(settings, "api_token", "s3cret")
    assert (await client.get("/api/v1/jobs")).status_code == 401
    assert (await client.get("/api/v1/jobs", headers={"Authorization": "Bearer nope"})).status_code == 401
    assert (await client.get("/api/v1/jobs", headers={"Authorization": "Bearer s3cret"})).status_code == 200
    assert (await client.get("/api/v1/jobs", headers={"X-API-Token": "s3cret"})).status_code == 200
    assert (await client.get("/api/v1/health")).status_code == 200  # stays public for monitoring


async def test_clear_jobs_keeps_jobs_with_applications(client):
    await client.post("/api/v1/candidates/me/resume", files={"file": ("cv.txt", RESUME, "text/plain")})
    results = (
        await client.post("/api/v1/search", json={"roles": ["Backend Engineer"], "strict_location": False})
    ).json()["results"]
    job_id = results[0]["job"]["id"]
    app = (await client.post("/api/v1/applications", json={"job_id": job_id, "mode": "manual"})).json()

    cleared = await client.delete("/api/v1/jobs")
    assert cleared.status_code == 200
    assert cleared.json()["deleted"] >= 1 and cleared.json()["kept"] >= 1
    remaining = {j["job"]["id"] for j in (await client.get("/api/v1/jobs")).json()}
    assert job_id in remaining
    assert (await client.get(f"/api/v1/applications/{app['id']}")).status_code == 200
