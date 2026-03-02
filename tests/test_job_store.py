from __future__ import annotations

"""Tests for agent/jobs/store.py — job pipeline database."""


async def test_save_job_new(job_store, sample_job):
    is_new = await job_store.save_job(sample_job)
    assert is_new is True


async def test_save_job_duplicate(job_store, sample_job):
    await job_store.save_job(sample_job)
    is_new = await job_store.save_job(sample_job)
    assert is_new is False


async def test_get_jobs_no_filter(job_store, sample_job):
    await job_store.save_job(sample_job)
    jobs = await job_store.get_jobs()
    assert len(jobs) == 1
    assert jobs[0]["title"] == "ML Engineer"


async def test_get_jobs_filter_by_status(job_store, sample_job):
    await job_store.save_job(sample_job)
    # Default status is "new"
    jobs = await job_store.get_jobs(status="new")
    assert len(jobs) == 1
    jobs = await job_store.get_jobs(status="sent")
    assert len(jobs) == 0


async def test_get_jobs_filter_by_min_score(job_store, sample_job):
    await job_store.save_job(sample_job)  # score 75
    low_job = {**sample_job, "job_id": "low-score", "match_score": 30}
    await job_store.save_job(low_job)

    jobs = await job_store.get_jobs(min_score=50)
    assert len(jobs) == 1
    assert jobs[0]["match_score"] == 75


async def test_get_job_by_id(job_store, sample_job):
    await job_store.save_job(sample_job)
    job = await job_store.get_job_by_id("test-job-001")
    assert job is not None
    assert job["company"] == "TestCo"


async def test_update_status(job_store, sample_job):
    await job_store.save_job(sample_job)
    await job_store.update_status("test-job-001", "notified")
    job = await job_store.get_job_by_id("test-job-001")
    assert job["status"] == "notified"


async def test_set_outreach_draft(job_store, sample_job):
    await job_store.save_job(sample_job)
    await job_store.set_outreach_draft("test-job-001", "Hi, I'm interested...", "email")
    job = await job_store.get_job_by_id("test-job-001")
    assert job["outreach_draft"] == "Hi, I'm interested..."
    assert job["outreach_platform"] == "email"
    assert job["status"] == "drafting"


async def test_mark_outreach_sent(job_store, sample_job):
    await job_store.save_job(sample_job)
    await job_store.mark_outreach_sent("test-job-001")
    job = await job_store.get_job_by_id("test-job-001")
    assert job["status"] == "sent"
    assert job["outreach_sent_at"] is not None


async def test_log_and_get_recent_scan(job_store):
    await job_store.log_scan("linkedin", "ML Engineer", 10, 3)
    scan = await job_store.get_recent_scan("linkedin", "ML Engineer", hours=1)
    assert scan is not None
    assert scan["results_found"] == 10
    assert scan["new_jobs"] == 3


async def test_get_stats(job_store, sample_job):
    await job_store.save_job(sample_job)
    second_job = {**sample_job, "job_id": "job-002", "match_score": 60}
    await job_store.save_job(second_job)
    await job_store.update_status("job-002", "sent")

    stats = await job_store.get_stats()
    assert stats["total_jobs"] == 2
    assert stats["by_status"]["new"] == 1
    assert stats["by_status"]["sent"] == 1
    assert stats["average_match_score"] > 0
