from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.test_tasks_service import BAD_FRONTMATTER, NOT_UTF_8, UNREADABLE_IDS


def test_tasks_returns_open_tasks_with_joined_note_titles(
    authenticated_client: TestClient,
) -> None:
    authenticated_client.put(
        "/api/notes/a.md",
        content="---\ntitle: Groceries\n---\n- [ ] Buy milk\n",
    )
    authenticated_client.put(
        "/api/notes/b.md",
        content="---\ntitle: Chores\n---\n- [ ] Mow lawn\n",
    )

    response = authenticated_client.get("/api/tasks")

    assert response.status_code == 200
    body = response.json()
    assert {(item["title"], item["text"]) for item in body} == {
        ("Groceries", "Buy milk"),
        ("Chores", "Mow lawn"),
    }


def test_tasks_excludes_checked_tasks(authenticated_client: TestClient) -> None:
    authenticated_client.put("/api/notes/a.md", content="- [ ] Open\n- [x] Closed\n")

    response = authenticated_client.get("/api/tasks")

    assert [item["text"] for item in response.json()] == ["Open"]


def test_tasks_orders_by_note_path_then_line(authenticated_client: TestClient) -> None:
    authenticated_client.put("/api/notes/z.md", content="- [ ] Z task\n")
    authenticated_client.put("/api/notes/a.md", content="- [ ] First\n- [ ] Second\n")

    response = authenticated_client.get("/api/tasks")

    assert [(item["path"], item["text"]) for item in response.json()] == [
        ("a.md", "First"),
        ("a.md", "Second"),
        ("z.md", "Z task"),
    ]


def test_tasks_uses_frontmatter_title_override_not_filename(
    authenticated_client: TestClient,
) -> None:
    authenticated_client.put(
        "/api/notes/my-note.md",
        content="---\ntitle: A Custom Title\n---\n- [ ] Task\n",
    )

    response = authenticated_client.get("/api/tasks")

    assert response.json()[0]["title"] == "A Custom Title"


def test_tasks_empty_vault_returns_empty_list(authenticated_client: TestClient) -> None:
    response = authenticated_client.get("/api/tasks")

    assert response.status_code == 200
    assert response.json() == []


def test_tasks_carry_tags_and_done_fields(authenticated_client: TestClient) -> None:
    authenticated_client.put(
        "/api/notes/a.md", content="---\ntags: [garden]\n---\n- [ ] Water\n"
    )

    response = authenticated_client.get("/api/tasks")

    assert response.json() == [
        {
            "path": "a.md",
            "title": "a",
            "line": 8,  # after the rendered frontmatter and a blank line
            "text": "Water",
            "tags": ["garden"],
            "done": False,
            "done_date": None,
        }
    ]


def test_both_lists_leave_out_the_templates_folder(
    authenticated_client: TestClient,
) -> None:
    for path in ("templates/t.md", "templates/sub/t.md", "templatesfoo/t.md"):
        authenticated_client.put(
            f"/api/notes/{path}",
            content="- [ ] Open\n- [x] Done ✅ 2026-10-26\n",
        )

    open_tasks = authenticated_client.get("/api/tasks").json()
    done_tasks = authenticated_client.get(
        "/api/tasks/done", params={"since": "2026-10-01"}
    ).json()

    assert [task["path"] for task in open_tasks] == ["templatesfoo/t.md"]
    assert [task["path"] for task in done_tasks] == ["templatesfoo/t.md"]


def test_done_list_has_dated_ticks_since_the_day_newest_first(
    authenticated_client: TestClient,
) -> None:
    authenticated_client.put(
        "/api/notes/a.md",
        content=(
            "- [x] Older ✅ 2026-10-12\n"
            "- [x] Oldest kept ✅ 2026-10-13\n"
            "- [x] Newest ✅ 2026-10-26 ^id\n"
            "- [x] No date\n"
            "- [ ] Open\n"
        ),
    )
    authenticated_client.put("/api/notes/b.md", content="- [X] Middle ✅️ 2026-10-20\n")

    response = authenticated_client.get(
        "/api/tasks/done", params={"since": "2026-10-13"}
    )

    assert response.status_code == 200
    assert [
        (task["path"], task["line"], task["text"], task["done"], task["done_date"])
        for task in response.json()
    ] == [
        ("a.md", 9, "Newest ^id", True, "2026-10-26"),
        ("b.md", 7, "Middle", True, "2026-10-20"),
        ("a.md", 8, "Oldest kept", True, "2026-10-13"),
    ]


@pytest.mark.parametrize("since", [None, "", "2026-10-1", "20261013", "yesterday"])
def test_done_list_needs_a_valid_since(
    authenticated_client: TestClient, since: str | None
) -> None:
    params = {} if since is None else {"since": since}

    response = authenticated_client.get("/api/tasks/done", params=params)

    assert response.status_code == 422


def test_tick_writes_the_line_and_updates_both_lists(
    authenticated_client: TestClient, vault: Path
) -> None:
    authenticated_client.put("/api/notes/a.md", content="- [ ] Water the herbs\n")

    response = authenticated_client.post(
        "/api/tasks/done",
        json={
            "path": "a.md",
            "line": 7,
            "text": "Water the herbs",
            "done": True,
            "date": "2026-10-26",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["task"] == {
        "path": "a.md",
        "title": "a",
        "line": 7,
        "text": "Water the herbs",
        "tags": [],
        "done": True,
        "done_date": "2026-10-26",
    }
    assert body["note"]["content"] == (vault / "a.md").read_text()
    assert "- [x] Water the herbs ✅ 2026-10-26\n" in body["note"]["content"]
    assert authenticated_client.get("/api/tasks").json() == []
    done = authenticated_client.get("/api/tasks/done", params={"since": "2026-10-26"})
    assert [task["text"] for task in done.json()] == ["Water the herbs"]


def test_untick_returns_the_task_to_the_open_list(
    authenticated_client: TestClient, vault: Path
) -> None:
    (vault / "a.md").write_text("- [x] Water ✅ 2026-10-26\n", encoding="utf-8")

    response = authenticated_client.post(
        "/api/tasks/done",
        json={"path": "a.md", "line": 1, "text": "Water", "done": False},
    )

    assert response.status_code == 200
    assert (vault / "a.md").read_text() == "- [ ] Water\n"
    assert [task["text"] for task in authenticated_client.get("/api/tasks").json()] == [
        "Water"
    ]


@pytest.fixture
def _no_watcher(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the watcher from re-indexing a file a test changes behind the
    app's back, so only the route under test can correct the index."""
    monkeypatch.setenv("WATCHER_ENABLED", "false")


@pytest.mark.usefixtures("_no_watcher")
def test_a_stale_tick_is_refused_and_corrects_the_index(
    authenticated_client: TestClient, vault: Path
) -> None:
    authenticated_client.put("/api/notes/a.md", content="- [ ] Call the plumber\n")
    edited = (vault / "a.md").read_bytes().replace(b"Call the plumber", b"Call later")
    (vault / "a.md").write_bytes(edited)

    response = authenticated_client.post(
        "/api/tasks/done",
        json={
            "path": "a.md",
            "line": 7,
            "text": "Call the plumber",
            "done": True,
            "date": "2026-10-26",
        },
    )

    assert response.status_code == 409
    assert response.json() == {"detail": "The note changed since the task was loaded"}
    assert (vault / "a.md").read_bytes() == edited
    assert [task["text"] for task in authenticated_client.get("/api/tasks").json()] == [
        "Call later"
    ]


@pytest.mark.usefixtures("_no_watcher")
def test_ticking_in_a_deleted_note_is_not_found_and_drops_it_from_the_index(
    authenticated_client: TestClient, vault: Path
) -> None:
    authenticated_client.put("/api/notes/a.md", content="- [ ] Water\n")
    (vault / "a.md").unlink()

    response = authenticated_client.post(
        "/api/tasks/done",
        json={
            "path": "a.md",
            "line": 7,
            "text": "Water",
            "done": True,
            "date": "2026-10-26",
        },
    )

    assert response.status_code == 404
    assert authenticated_client.get("/api/tasks").json() == []


@pytest.mark.parametrize(
    "changes",
    [
        {"date": None},  # a tick needs the day it was done
        {"date": "26/10/2026"},
        {"date": "2026-10-26T10:00:00"},
        {"line": "seven"},
    ],
)
def test_a_malformed_tick_is_unprocessable(
    authenticated_client: TestClient, changes: dict[str, object]
) -> None:
    body = {
        "path": "a.md",
        "line": 1,
        "text": "Water",
        "done": True,
        "date": "2026-10-26",
    }

    response = authenticated_client.post("/api/tasks/done", json=body | changes)

    assert response.status_code == 422


def test_tick_outside_the_vault_is_a_bad_request(
    authenticated_client: TestClient,
) -> None:
    response = authenticated_client.post(
        "/api/tasks/done",
        json={"path": "../x.md", "line": 1, "text": "Water", "done": False},
    )

    assert response.status_code == 400


@pytest.mark.parametrize(
    ("content", "line"), [(NOT_UTF_8, 1), (BAD_FRONTMATTER, 4)], ids=UNREADABLE_IDS
)
def test_ticking_in_an_unreadable_note_is_a_bad_request_and_writes_nothing(
    authenticated_client: TestClient, vault: Path, content: bytes, line: int
) -> None:
    (vault / "a.md").write_bytes(content)

    response = authenticated_client.post(
        "/api/tasks/done",
        json={
            "path": "a.md",
            "line": line,
            "text": "Water",
            "done": True,
            "date": "2026-10-26",
        },
    )

    assert response.status_code == 400
    assert (vault / "a.md").read_bytes() == content


def test_add_creates_todays_note_and_lists_the_task(
    authenticated_client: TestClient, vault: Path
) -> None:
    response = authenticated_client.post(
        "/api/tasks",
        json={
            "text": "Order timber for the shed",
            "date": "2026-10-26",
            "heading": "Monday 26 October 2026",
        },
    )

    assert response.status_code == 201
    body = response.json()
    written = (vault / "daily" / "2026-10-26.md").read_text()
    assert written.endswith(
        "\n# Monday 26 October 2026\n\n- [ ] Order timber for the shed\n"
    )
    assert body["note"]["path"] == "daily/2026-10-26.md"
    assert body["note"]["content"] == written
    assert body["task"]["line"] == written.count("\n")
    assert authenticated_client.get("/api/tasks").json() == [body["task"]]


def test_add_appends_to_an_existing_daily_note(
    authenticated_client: TestClient, vault: Path
) -> None:
    authenticated_client.put(
        "/api/notes/daily/2026-10-26.md", content="# Today\n\n- [ ] First\n"
    )
    before = (vault / "daily" / "2026-10-26.md").read_bytes()

    response = authenticated_client.post(
        "/api/tasks",
        json={"text": "- [ ] Second", "date": "2026-10-26", "heading": "x"},
    )

    assert response.status_code == 201
    assert (
        vault / "daily" / "2026-10-26.md"
    ).read_bytes() == before + b"- [ ] Second\n"
    assert [task["text"] for task in authenticated_client.get("/api/tasks").json()] == [
        "First",
        "Second",
    ]


@pytest.mark.parametrize(
    "changes",
    [
        {"text": "  \n "},
        {"date": "../x"},
        {"date": "2026-02-30"},
        {"date": "20261026"},
        {"date": "2026-10-26/../../escape"},
        {"date": None},
    ],
)
def test_a_malformed_add_is_unprocessable_and_writes_nothing(
    authenticated_client: TestClient, vault: Path, changes: dict[str, object]
) -> None:
    body = {"text": "Buy", "date": "2026-10-26", "heading": "Monday"}

    response = authenticated_client.post("/api/tasks", json=body | changes)

    assert response.status_code == 422
    assert not any(path.suffix == ".md" for path in vault.rglob("*"))


@pytest.mark.parametrize("content", [NOT_UTF_8, BAD_FRONTMATTER], ids=UNREADABLE_IDS)
def test_add_to_an_unreadable_daily_note_is_a_bad_request_and_writes_nothing(
    authenticated_client: TestClient, vault: Path, content: bytes
) -> None:
    (vault / "daily").mkdir()
    (vault / "daily" / "2026-10-26.md").write_bytes(content)

    response = authenticated_client.post(
        "/api/tasks",
        json={"text": "Buy", "date": "2026-10-26", "heading": "Monday"},
    )

    assert response.status_code == 400
    assert (vault / "daily" / "2026-10-26.md").read_bytes() == content
