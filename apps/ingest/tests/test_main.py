"""Unit tests for the ACA Job entrypoint (T066).

Mocks the Storage Queue client + the deferred dispatcher import to verify:

  (a) ``Microsoft.Storage.BlobCreated`` is dispatched to ``handle_blob_event``
      with the validated CloudEvent payload, the constructed pipeline,
      and a ``Repos`` bundle.
  (b) Lifecycle records (``running`` → ``completed``) are written to the
      ``ingestion-runs`` repo on a successful outcome and the queue
      message is deleted.
  (c) An uncaught exception in the dispatcher marks the run ``failed``,
      causes ``main()`` to return a non-zero exit code, and *does not*
      delete the queue message (so KEDA's retry path takes over).
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src import main as main_mod
from src.handlers.shared import Repos
from src.pipeline import RunOutcome
from src.runs import IngestionRunsClient, SharedDocumentsClient


def _sample_blob_created_payload() -> dict[str, Any]:
    return {
        "specversion": "1.0",
        "type": "Microsoft.Storage.BlobCreated",
        "source": "https://stexample.blob.core.windows.net/shared-corpus",
        "id": "evt-1",
        "time": "2026-05-09T14:00:00Z",
        "subject": "/blobServices/default/containers/shared-corpus/blobs/policy.pdf",
        "datacontenttype": "application/cloudevents+json",
        "data": {
            "url": "https://stexample.blob.core.windows.net/shared-corpus/policy.pdf",
            "contentType": "application/pdf",
            "contentLength": 1234,
            "eTag": "0xABC",
        },
    }


class _FakeQueueMessage:
    def __init__(self, body: dict[str, Any]) -> None:
        self.id = "msg-1"
        self.content = json.dumps(body)


class _FakeAsyncIter:
    """Minimal async iterator yielding the supplied messages once."""

    def __init__(self, messages: list[_FakeQueueMessage]) -> None:
        self._messages = list(messages)

    def __aiter__(self) -> _FakeAsyncIter:
        return self

    async def __anext__(self) -> _FakeQueueMessage:
        if not self._messages:
            raise StopAsyncIteration
        return self._messages.pop(0)


def _make_fake_queue(messages: list[_FakeQueueMessage]) -> MagicMock:
    q = MagicMock()
    q.receive_messages = MagicMock(return_value=_FakeAsyncIter(messages))
    q.delete_message = AsyncMock()
    q.close = AsyncMock()
    return q


def _make_fake_runs() -> MagicMock:
    runs = MagicMock(spec=IngestionRunsClient)
    runs.start = AsyncMock()
    runs.complete = AsyncMock()
    runs.close = AsyncMock()
    return runs


def _make_fake_docs() -> MagicMock:
    docs = MagicMock(spec=SharedDocumentsClient)
    docs.delete = AsyncMock()
    docs.close = AsyncMock()
    return docs


@pytest.fixture
def patched_main(
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, Any]:
    """Wire fakes into ``main`` and return them for assertions."""

    fake_queue = _make_fake_queue([_FakeQueueMessage(_sample_blob_created_payload())])
    fake_runs = _make_fake_runs()
    fake_docs = _make_fake_docs()
    fake_credential = MagicMock()
    fake_credential.close = AsyncMock()

    monkeypatch.setattr(main_mod, "QueueClient", MagicMock(return_value=fake_queue))
    monkeypatch.setattr(
        main_mod, "DefaultAzureCredential", MagicMock(return_value=fake_credential)
    )
    monkeypatch.setattr(
        main_mod, "IngestionRunsClient", MagicMock(return_value=fake_runs)
    )
    monkeypatch.setattr(
        main_mod, "SharedDocumentsClient", MagicMock(return_value=fake_docs)
    )
    # Stable run id so assertions can compare exact values.
    monkeypatch.setattr(main_mod, "_new_run_id", lambda: "r_test")

    return {
        "queue": fake_queue,
        "runs": fake_runs,
        "docs": fake_docs,
        "credential": fake_credential,
    }


def _patch_dispatcher(
    monkeypatch: pytest.MonkeyPatch, fn: Any
) -> list[tuple[dict[str, Any], Any, Repos]]:
    """Replace ``handle_blob_event`` and capture each invocation's args."""
    captured: list[tuple[dict[str, Any], Any, Repos]] = []

    async def wrapper(event: dict[str, Any], pipeline: Any, repos: Repos) -> RunOutcome:
        captured.append((event, pipeline, repos))
        return await fn(event, pipeline, repos)

    import src.handlers.shared as shared_mod

    monkeypatch.setattr(shared_mod, "handle_blob_event", wrapper)
    return captured


def test_blob_created_routes_to_dispatcher_and_records_lifecycle(
    patched_main: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def succeed(event: dict[str, Any], _p: Any, _r: Repos) -> RunOutcome:
        return RunOutcome(
            status="succeeded",
            document_id="doc-abc",
            event_type=event["type"],
            message=None,
        )

    captured = _patch_dispatcher(monkeypatch, succeed)

    rc = main_mod.main()
    assert rc == 0

    # (a) Dispatcher was called with the validated CloudEvent + Repos bundle.
    assert len(captured) == 1
    event_arg, _pipeline_arg, repos_arg = captured[0]
    assert event_arg["type"] == "Microsoft.Storage.BlobCreated"
    assert event_arg["id"] == "evt-1"
    assert isinstance(repos_arg, Repos)
    assert repos_arg.docs_repo is patched_main["docs"]
    assert repos_arg.runs_repo is patched_main["runs"]

    # (b) Lifecycle: start(running) → complete(completed).
    runs = patched_main["runs"]
    runs.start.assert_awaited_once_with(
        run_id="r_test", scope="shared", trigger="eventgrid"
    )
    runs.complete.assert_awaited_once()
    complete_call = runs.complete.await_args
    assert complete_call.args == ("r_test", "shared")
    assert complete_call.kwargs["status"] == "completed"
    assert complete_call.kwargs["per_document"] == [
        {
            "documentId": "doc-abc",
            "outcome": "succeeded",
            "eventType": "Microsoft.Storage.BlobCreated",
        }
    ]

    # Successful processing deletes the queue message.
    patched_main["queue"].delete_message.assert_awaited_once()


def test_dispatcher_exception_marks_run_failed_and_exits_non_zero(
    patched_main: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def boom(_event: dict[str, Any], _p: Any, _r: Repos) -> RunOutcome:
        raise RuntimeError("kaboom")

    _patch_dispatcher(monkeypatch, boom)

    rc = main_mod.main()
    assert rc == 1, "uncaught dispatcher error must produce a non-zero exit code"

    runs = patched_main["runs"]
    runs.start.assert_awaited_once()
    assert runs.complete.await_count == 1
    call = runs.complete.await_args
    assert call.args == ("r_test", "shared")
    assert call.kwargs["status"] == "failed"
    assert "RuntimeError" in call.kwargs["error"]
    assert "kaboom" in call.kwargs["error"]

    # Queue message must NOT be deleted on failure — let KEDA retry / DLQ.
    patched_main["queue"].delete_message.assert_not_awaited()


def test_failed_outcome_marks_run_failed_and_does_not_delete_message(
    patched_main: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fail_outcome(event: dict[str, Any], _p: Any, _r: Repos) -> RunOutcome:
        return RunOutcome(
            status="failed",
            document_id="doc-x",
            event_type=event["type"],
            message="docintel 503",
        )

    _patch_dispatcher(monkeypatch, fail_outcome)

    rc = main_mod.main()
    assert rc == 1

    runs = patched_main["runs"]
    runs.complete.assert_awaited_once()
    call = runs.complete.await_args
    assert call.kwargs["status"] == "failed"
    assert call.kwargs["error"] == "docintel 503"
    assert call.kwargs["per_document"][0]["outcome"] == "failed"
    patched_main["queue"].delete_message.assert_not_awaited()


def test_empty_queue_returns_zero_without_writing_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_queue = _make_fake_queue([])
    fake_runs = _make_fake_runs()
    fake_docs = _make_fake_docs()
    fake_credential = MagicMock()
    fake_credential.close = AsyncMock()

    monkeypatch.setattr(main_mod, "QueueClient", MagicMock(return_value=fake_queue))
    monkeypatch.setattr(
        main_mod, "DefaultAzureCredential", MagicMock(return_value=fake_credential)
    )
    monkeypatch.setattr(
        main_mod, "IngestionRunsClient", MagicMock(return_value=fake_runs)
    )
    monkeypatch.setattr(
        main_mod, "SharedDocumentsClient", MagicMock(return_value=fake_docs)
    )

    rc = main_mod.main()
    assert rc == 0
    fake_runs.start.assert_not_called()
    fake_runs.complete.assert_not_called()
    fake_queue.delete_message.assert_not_called()


def test_poison_message_is_dropped_and_no_run_recorded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    poison = _FakeQueueMessage({"not": "a-cloudevent"})
    fake_queue = _make_fake_queue([poison])
    fake_runs = _make_fake_runs()
    fake_docs = _make_fake_docs()
    fake_credential = MagicMock()
    fake_credential.close = AsyncMock()

    monkeypatch.setattr(main_mod, "QueueClient", MagicMock(return_value=fake_queue))
    monkeypatch.setattr(
        main_mod, "DefaultAzureCredential", MagicMock(return_value=fake_credential)
    )
    monkeypatch.setattr(
        main_mod, "IngestionRunsClient", MagicMock(return_value=fake_runs)
    )
    monkeypatch.setattr(
        main_mod, "SharedDocumentsClient", MagicMock(return_value=fake_docs)
    )

    rc = main_mod.main()
    assert rc == 0
    fake_runs.start.assert_not_called()
    fake_queue.delete_message.assert_awaited_once()
