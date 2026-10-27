from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager

from fastapi import APIRouter, Depends, HTTPException, Query

from cerebrum.api.deps import get_db, require_writable_vault
from cerebrum.index.indexer import sync_note_in_index
from cerebrum.notes.parser import InvalidNoteContentError
from cerebrum.notes.service import InvalidNotePathError, NoteNotFoundError
from cerebrum.settings import get_settings
from cerebrum.tasks.models import (
    AddTaskRequest,
    IsoDay,
    SetTaskDoneRequest,
    TaskItem,
    TaskWriteResponse,
)
from cerebrum.tasks.service import (
    EmptyTaskTextError,
    TaskConflictError,
    add_task,
    list_done_tasks,
    list_open_tasks,
    set_task_done,
)

router = APIRouter()


@router.get("/tasks", response_model=list[TaskItem])
def tasks_endpoint(db: sqlite3.Connection = Depends(get_db)) -> list[TaskItem]:
    return list_open_tasks(db, get_settings().cerebrum_templates_folder)


@router.get("/tasks/done", response_model=list[TaskItem])
def done_tasks_endpoint(
    since: IsoDay = Query(
        description="The earliest done date to list, as YYYY-MM-DD.",
    ),
    db: sqlite3.Connection = Depends(get_db),
) -> list[TaskItem]:
    return list_done_tasks(db, since, get_settings().cerebrum_templates_folder)


@router.post(
    "/tasks",
    response_model=TaskWriteResponse,
    status_code=201,
    dependencies=[Depends(require_writable_vault)],
)
def add_task_endpoint(
    body: AddTaskRequest, db: sqlite3.Connection = Depends(get_db)
) -> TaskWriteResponse:
    settings = get_settings()
    with _refusals_as_http_errors():
        note, task = add_task(
            settings.cerebrum_vault_path,
            settings.cerebrum_daily_note_folder,
            body.date,
            body.text,
            body.heading,
        )
    sync_note_in_index(db, settings.cerebrum_vault_path, note.path)
    return TaskWriteResponse(note=note, task=task)


@router.post(
    "/tasks/done",
    response_model=TaskWriteResponse,
    dependencies=[Depends(require_writable_vault)],
)
def set_task_done_endpoint(
    body: SetTaskDoneRequest, db: sqlite3.Connection = Depends(get_db)
) -> TaskWriteResponse:
    settings = get_settings()
    with _refusals_as_http_errors():
        try:
            note, task = set_task_done(
                settings.cerebrum_vault_path,
                body.path,
                body.line,
                body.text,
                done=body.done,
                day=body.date,
            )
        except (TaskConflictError, NoteNotFoundError):
            # The index listed the task where it no longer is: bring the
            # note's rows up to date, so the list the client fetches next
            # is right.
            sync_note_in_index(db, settings.cerebrum_vault_path, body.path)
            raise
    sync_note_in_index(db, settings.cerebrum_vault_path, body.path)
    return TaskWriteResponse(note=note, task=task)


@contextmanager
def _refusals_as_http_errors() -> Iterator[None]:
    """A task write's refusals as HTTP errors, with the same statuses and
    messages the notes routes use for the note-level ones."""
    try:
        yield
    except TaskConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except EmptyTaskTextError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except InvalidNotePathError as exc:
        raise HTTPException(status_code=400, detail="Invalid note path") from exc
    except NoteNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Note not found") from exc
    except InvalidNoteContentError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
