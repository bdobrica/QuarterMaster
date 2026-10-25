"""Knowledge drafts cannot change policy until explicit, current owner approval."""

import asyncio
import json
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from quartermaster import knowledge_editing as editing
from quartermaster import teaching
from quartermaster.app import create_app
from quartermaster.config import Settings
from quartermaster.contracts.knowledge import (
    ArticleContent,
    KnowledgeDraft,
    KnowledgeReplay,
    KnowledgeRequest,
    KnowledgeReview,
    KnowledgeSend,
)
from quartermaster.contracts.teaching import TestInput as AdviceInput
from quartermaster.db import connect
from quartermaster.errors import DomainError
from quartermaster.knowledge import citation, current_knowledge, knowledge_history, search
from quartermaster.projects import get_adviser
from quartermaster.sources import source_bytes
from tests.legacy_print import seed
from tests.test_teaching import draft as advice_draft


@pytest.fixture
def demo(settings):
    project, suite = seed(settings)
    revision = current_knowledge(settings, project.id)
    return project, suite, revision


def manual(
    settings, project, revision, *, new=False, text="Portal e-signatures count as sign-off."
):
    return editing.draft(
        settings,
        project.id,
        KnowledgeDraft(
            source_id=None if new else revision.source_ids[0],
            expected_revision=revision.id,
            title="Proof policy",
            text=text,
        ),
    )


def review(settings, proposal, action="apply"):
    return editing.review(
        settings,
        proposal.project_id,
        proposal.id,
        KnowledgeReview(expected_revision=proposal.revision, action=action),
    )


def test_manual_approval_replaces_current_policy_preserves_history(settings, demo):
    project, suite, old = demo
    old_excerpts = search(settings, project.id, "portal")
    old_source = old_excerpts[0]["source"]
    before_bytes = source_bytes(settings, old_source)
    proposal = manual(
        settings, project, old, text="# Proof policy\nPortal e-signatures count as sign-off."
    )
    assert current_knowledge(settings, project.id) == old
    assert proposal.before == before_bytes.decode()
    assert proposal.origin == "OWNER_DRAFT" and proposal.status == "pending"
    applied = review(settings, proposal)
    current = current_knowledge(settings, project.id)
    assert current.id == applied.applied_revision != old.id
    assert old_source.id not in current.source_ids
    assert get_adviser(settings.database_path, project.id).knowledge_revision == current.id
    assert all(
        item["source"].id == applied.applied_source
        for item in search(settings, project.id, "portal")
    )
    # Superseded chunks cannot resolve against the current selection, but historic links work.
    with pytest.raises(DomainError, match="CITATION_MISSING"):
        citation(settings, project.id, old_excerpts[0]["chunk"].citation_id)
    assert citation(settings, project.id, old_excerpts[0]["chunk"].citation_id, old.id)
    assert source_bytes(settings, old_source) == before_bytes
    assert len(knowledge_history(settings, project.id)) == 2
    with connect(settings.database_path) as connection:
        assert connection.execute("SELECT count(*) FROM knowledge_proposals").fetchone()[0] == 2
        assert connection.execute("SELECT count(*) FROM training_examples").fetchone()[0] == 0
        assert connection.execute("SELECT count(*) FROM evaluation_holdouts").fetchone()[0] == len(
            suite.cases
        )
    with pytest.raises(DomainError, match="PROPOSAL_CHANGED"):
        review(settings, proposal)


def test_reject_and_stale_approval_do_not_change_active_knowledge(settings, demo):
    project, _, old = demo
    rejected = manual(settings, project, old)
    assert review(settings, rejected, "reject").status == "rejected"
    assert current_knowledge(settings, project.id) == old
    first = manual(settings, project, old)
    stale = manual(settings, project, old)
    review(settings, first)
    current = current_knowledge(settings, project.id)
    with pytest.raises(DomainError, match="KNOWLEDGE_CHANGED"):
        review(settings, stale)
    assert current_knowledge(settings, project.id) == current
    assert len(knowledge_history(settings, project.id)) == 2
    # New article adds to the active set rather than replacing other articles.
    extra = manual(settings, project, current, new=True)
    review(settings, extra)
    assert len(current_knowledge(settings, project.id).source_ids) == 2


def test_atomic_approval_failure_leaves_pending_and_current_unchanged(settings, demo, monkeypatch):
    project, _, old = demo
    proposal = manual(settings, project, old)
    real_append = editing.append

    def fail(connection, proposal, **changes):
        if changes.get("status") == "applied":
            raise DomainError("TEST_ROLLBACK")
        return real_append(connection, proposal, **changes)

    monkeypatch.setattr(editing, "append", fail)
    with pytest.raises(DomainError, match="TEST_ROLLBACK"):
        review(settings, proposal)
    assert current_knowledge(settings, project.id) == old
    assert editing.proposals(settings, project.id)[0].status == "pending"
    assert len(knowledge_history(settings, project.id)) == 1


class Builder:
    def __init__(self, error=None):
        self.calls = []
        self.error = error

    async def structured(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise DomainError(self.error)
        return ArticleContent(title="Print policy", text="# Print policy\nPortal signature counts.")


def prepared(settings, project, old):
    config = Settings(
        data_dir=settings.data_dir,
        _env_file=None,
        builder_base_url="https://builder.example/v1",
        builder_model="builder",
    )
    proposal = editing.draft(
        config,
        project.id,
        KnowledgeRequest(
            source_id=old.source_ids[0],
            expected_revision=old.id,
            instruction="Portal e-signature counts as sign-off.",
        ),
        ai=True,
    )
    return config, proposal


def consent(proposal, **changes):
    return KnowledgeSend(
        **{
            **dict(
                expected_revision=proposal.revision,
                turn_id=proposal.id,
                disclosure_sha256=proposal.disclosure.disclosure_sha256,
                consent=True,
            ),
            **changes,
        }
    )


def test_ai_exact_disclosure_no_cases_or_outcomes_explicit_consent_and_review(settings, demo):
    project, suite, old = demo
    config, proposal = prepared(settings, project, old)
    payload = json.loads(proposal.disclosure.context)
    assert set(payload) == {"article", "instruction"}
    assert payload["article"]["source_id"] == str(old.source_ids[0])
    assert all(case.rubric.expectation not in proposal.disclosure.context for case in suite.cases)
    assert (
        "Cedar" not in proposal.disclosure.context and "Juniper" not in proposal.disclosure.context
    )
    builder = Builder()
    with pytest.raises(ValidationError):
        consent(proposal, consent=1)
    with pytest.raises(DomainError, match="KNOWLEDGE_CONSENT"):
        asyncio.run(
            editing.send(
                config,
                builder,
                project.id,
                proposal.id,
                consent(proposal, disclosure_sha256="0" * 64),
            )
        )
    assert not builder.calls
    changed = config.model_copy(update={"builder_model": "different"})
    with pytest.raises(DomainError, match="KNOWLEDGE_CONSENT"):
        asyncio.run(editing.send(changed, builder, project.id, proposal.id, consent(proposal)))
    result = asyncio.run(editing.send(config, builder, project.id, proposal.id, consent(proposal)))
    assert len(builder.calls) == 1 and result.status == "pending"
    assert result.consented_at and current_knowledge(settings, project.id) == old
    with pytest.raises(DomainError, match="PROPOSAL_CHANGED"):
        asyncio.run(editing.send(config, builder, project.id, proposal.id, consent(proposal)))
    review(settings, result)
    assert current_knowledge(settings, project.id).id != old.id


def test_failed_and_interrupted_builder_never_retries_or_applies(settings, demo):
    project, _, old = demo
    config, proposal = prepared(settings, project, old)
    builder = Builder(error="BUILDER_TIMEOUT: Retry explicitly.")
    result = asyncio.run(editing.send(config, builder, project.id, proposal.id, consent(proposal)))
    assert result.status == "failed" and len(builder.calls) == 1
    with pytest.raises(DomainError, match="KNOWLEDGE_REVIEW"):
        review(settings, result)
    _, another = prepared(settings, project, old)
    with connect(settings.database_path) as connection:
        editing.append(connection, another, status="sending")
    editing.recover(settings)
    assert all(p.status == "failed" for p in editing.proposals(settings, project.id))
    assert current_knowledge(settings, project.id) == old


class Inference:
    def __init__(self):
        self.calls = []

    async def advise(self, **kwargs):
        self.calls.append(kwargs)
        data = json.loads(kwargs["context"])
        evidence = data["retrieved_evidence"]
        accepted = "Portal e-signatures count" in evidence[0]["text"]
        return advice_draft(
            recommendation="Ready." if accepted else "Hold.",
            refs=[evidence[0]["citation_id"]],
            quotes=[data["case"]["situation"]],
        )


def test_replay_same_model_settings_changes_only_knowledge_and_shows_excerpts(settings, demo):
    project, _, old = demo
    settings = Settings(
        data_dir=settings.data_dir,
        _env_file=None,
        local_base_url="http://localhost:8081/v1",
        local_model_sha256="a" * 64,
    )
    inference = Inference()
    original = asyncio.run(
        teaching.advise(
            settings,
            inference,
            project.id,
            AdviceInput(situation="Original portal signature job with confirmed copy."),
        )
    )
    proposal = review(settings, manual(settings, project, old))
    action = KnowledgeReplay(
        original_test=original.id,
        unseen_situation="Fresh portal signature job with confirmed copy for Friday.",
    )
    pairs = asyncio.run(editing.replay(settings, inference, project.id, proposal.id, action))
    assert len(pairs) == 2 and len(inference.calls) == 5
    for before, after in pairs:
        assert before.error is None and after.error is None
        assert before.advice.recommendation == "Hold."
        assert after.advice.recommendation == "Ready."
        assert before.case == after.case and before.case.observed_outcome is None
        assert before.adviser.knowledge_revision == old.id
        assert after.adviser.knowledge_revision == proposal.applied_revision
        for field in (
            "model_alias",
            "provider",
            "parameters",
            "system",
            "lessons",
        ):
            assert getattr(before, field) == getattr(after, field)
        # Citation allow-lists necessarily change with the source revision.
        before_schema = json.loads(json.dumps(before.response_schema))
        after_schema = json.loads(json.dumps(after.response_schema))
        for schema in (before_schema, after_schema):
            schema["$defs"]["Advice"]["properties"]["evidence_refs"]["items"].pop("enum")
        assert before_schema == after_schema
        assert before.evidence != after.evidence
        assert after.comparison_of == before.id
        assert "Portal e-signatures count" in after.evidence[0].text
    with pytest.raises(DomainError, match="already been tested"):
        asyncio.run(editing.replay(settings, inference, project.id, proposal.id, action))
    with TestClient(create_app(settings, inference=inference)) as client:
        response = client.get(f"/projects/{project.id}/knowledge/replay/{pairs[1][1].id}")
        assert response.status_code == 200
        assert "Supporting sources sent to the adviser" in response.text
        assert str(old.id) in response.text and str(proposal.applied_revision) in response.text


def test_ui_and_contract_errors_cross_project_xss_and_form_origin(settings, demo):
    project, _, old = demo
    other, _ = seed(settings)
    proposal = manual(settings, project, old, text="<script>alert(1)</script>")
    with TestClient(create_app(settings)) as client:
        url = f"/projects/{project.id}/knowledge"
        response = client.get(url)
        assert response.status_code == 200 and "Change our knowledge" in response.text
        assert "&lt;script&gt;" in response.text and "<script>alert(1)" not in response.text
        assert "spreadsheet" in response.text
        endpoint = f"/api/projects/{project.id}/knowledge/proposals"
        for body in ({}, {"unexpected": True}, {"title": "A", "text": ""}):
            assert client.post(endpoint, json=body).status_code == 422
        assert client.post(url + "/proposals", data={}).status_code == 403
        assert (
            client.post(
                f"/api/projects/{other.id}/knowledge/proposals/{proposal.id}/review",
                json={"expected_revision": 1, "action": "apply"},
            ).status_code
            == 404
        )
        assert (
            client.post(
                endpoint,
                json={
                    "source_id": str(uuid4()),
                    "expected_revision": str(old.id),
                    "title": "Bad",
                    "text": "Not a project article",
                },
            ).status_code
            == 409
        )
        result = client.post(
            url + "/proposals",
            headers={"origin": "http://testserver"},
            data={
                "source_id": str(old.source_ids[0]),
                "expected_revision": str(old.id),
                "title": "Policy",
                "text": "Manual edited article",
                "mode": "manual",
            },
        )
        assert result.status_code == 200 and "Manual edited article" in result.text


def test_prepared_request_contract_change_prevents_send(settings, demo, monkeypatch):
    project, _, old = demo
    config, proposal = prepared(settings, project, old)
    builder = Builder()
    monkeypatch.setattr(editing, "check_input", lambda *args, **kwargs: b"changed contract")
    with pytest.raises(DomainError, match="Request contract changed"):
        asyncio.run(editing.send(config, builder, project.id, proposal.id, consent(proposal)))
    assert not builder.calls
    assert editing.proposals(settings, project.id)[0].status == "prepared"


@pytest.mark.parametrize("value", ["   ", "\x00not text", "a" * 12001])
def test_article_contract_rejects_unreadable_and_oversized_text(value):
    with pytest.raises(ValidationError):
        ArticleContent(title="Policy", text=value)


def test_invalid_and_cancelled_builder_save_durable_failure(settings, demo):
    project, _, old = demo

    class Invalid:
        async def structured(self, **kwargs):
            return None

    class Cancelled:
        async def structured(self, **kwargs):
            raise asyncio.CancelledError

    config, proposal = prepared(settings, project, old)
    result = asyncio.run(
        editing.send(config, Invalid(), project.id, proposal.id, consent(proposal))
    )
    assert result.status == "failed" and "KNOWLEDGE_DRAFT" in result.error
    config, proposal = prepared(settings, project, old)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(editing.send(config, Cancelled(), project.id, proposal.id, consent(proposal)))
    assert all(p.status == "failed" for p in editing.proposals(settings, project.id))
    assert current_knowledge(settings, project.id) == old


def test_v7_migration_preserves_historical_documents_and_original_bytes(settings, demo):
    from quartermaster.db import migrate

    project, _, old = demo
    with connect(settings.database_path) as connection:
        before = [tuple(row) for row in connection.execute("SELECT * FROM knowledge_revisions")]
        connection.execute("DROP TABLE answer_reviews")
        connection.execute("DROP TABLE knowledge_proposals")
        connection.execute("DROP TABLE owner_decisions")
        connection.execute("DROP TABLE muster_imports")
        connection.execute("PRAGMA user_version=7")
    migrate(settings.database_path)
    migrate(settings.database_path)
    with connect(settings.database_path) as connection:
        assert [
            tuple(row) for row in connection.execute("SELECT * FROM knowledge_revisions")
        ] == before
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 10
    assert current_knowledge(settings, project.id) == old
    assert search(settings, project.id, "portal", old.id)
