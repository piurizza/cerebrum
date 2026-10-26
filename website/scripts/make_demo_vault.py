"""Write the demo vault the documentation's screenshots are taken from.

Every note is invented for the docs: generic topics, no real people, no
quoted or copied text. The output is identical on every run on the same day,
so screenshots can be regenerated after a UI change without the content
shifting. Only the done dates of ticked tasks follow the day it runs (see
`_done`), so the Tasks page's Done tab, which lists the last 14 days, always
has something to show.

Never point this at a real vault: it refuses a folder that is not empty.

Usage: make_demo_vault.py <empty-or-missing-folder>
"""

from __future__ import annotations

import re
import struct
import sys
import zlib
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

# Its presence tells the screenshot script it is looking at this vault.
SENTINEL_PATH = "about-this-demo-vault.md"

# Stands for a day counted back from the day the vault is built, filled in
# when a note is written.
_DAYS_AGO = re.compile(r"<days-ago:(\d+)>")


def _done(days_ago: int) -> str:
    """A done marker, as the Tasks page writes one when a task is ticked,
    dated `days_ago` days before the day the vault is built."""
    return f"✅ <days-ago:{days_ago}>"


@dataclass(frozen=True)
class Note:
    path: str
    title: str
    tags: tuple[str, ...]
    updated: str
    body: str
    images: tuple[str, ...] = field(default=())


def _png(width: int, height: int, stripe: tuple[int, int, int]) -> bytes:
    """A small striped PNG, built by hand so the output never varies."""
    rows = []
    for y in range(height):
        color = stripe if (y // 8) % 2 == 0 else (245, 240, 230)
        rows.append(b"\x00" + bytes(color) * width)

    def chunk(kind: bytes, data: bytes) -> bytes:
        payload = kind + data
        return (
            struct.pack(">I", len(data))
            + payload
            + struct.pack(">I", zlib.crc32(payload) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(b"".join(rows), 9))
        + chunk(b"IEND", b"")
    )


def _recipe(slug: str, title: str, kind: str, day: str, ingredients: str) -> Note:
    items = "\n".join(f"- {item.strip()}" for item in ingredients.split(","))
    return Note(
        f"recipes/{slug}.md",
        title,
        ("cooking", f"cooking/{kind}"),
        f"2026-{day}",
        f"# {title}\n\n## Ingredients\n\n{items}\n\n"
        "## Method\n\nPrepare everything first, then cook gently and taste as you "
        "go. See [[meal-plan]] for the week this goes into.\n",
    )


def _book(slug: str, title: str, kind: str, day: str, rating: int, note: str) -> Note:
    return Note(
        f"reading/{slug}.md",
        title,
        ("reading", f"reading/{kind}"),
        f"2026-{day}",
        f"# {title}\n\nRating: {rating}/5\n\n{note}\n\n"
        "Back to the [reading list](reading-list.md).\n",
    )


def _daily(day: int, tasks: str, links: str) -> Note:
    date = f"2026-10-{day:02d}"
    return Note(
        f"daily/{date}.md",
        date,
        ("daily",),
        f"{date}T18:00:00+00:00",
        f"# {date}\n\n## Tasks\n\n{tasks}\n\n## Notes\n\n{links}\n",
    )


NOTES: tuple[Note, ...] = (
    Note(
        SENTINEL_PATH,
        "About this demo vault",
        ("meta",),
        "2026-10-26",
        "---DEMO---\n# About this demo vault\n\nEvery note here was written for "
        "Cerebrum's documentation. Start at [[welcome]].\n",
    ),
    Note(
        "welcome.md",
        "Welcome",
        ("meta", "inbox"),
        "2026-10-26",
        "# Welcome\n\nThis vault holds projects, recipes, a reading list, travel "
        "plans and daily notes.\n\n- Projects: [[home-server]], [[garden-shed]], "
        "[[website-redesign]]\n- Today's note: [[2026-10-26]]\n- Reading: "
        "[reading list](reading/reading-list.md)\n",
    ),
    # Projects
    Note(
        "projects/home-server.md",
        "Home server",
        ("project/home-server", "homelab"),
        "2026-10-25T20:10:00+01:00",
        "# Home server\n\nA small always-on machine for backups and notes.\n\n"
        "## Tasks\n\n- [x] Install the operating system\n- [x] Set up "
        "[[docker-notes|Docker]]\n- [ ] Schedule nightly backups\n- [ ] Write down "
        "the restore steps\n\nRelated: [[backup-plan]]\n",
    ),
    Note(
        "projects/backup-plan.md",
        "Backup plan",
        ("project/home-server", "homelab"),
        "2026-10-22",
        "# Backup plan\n\nKeep three copies on two kinds of storage, one away from "
        "home.\n\n- [ ] Test a restore every month\n- [x] Buy a second disk\n\n"
        "Part of [[home-server]].\n",
    ),
    Note(
        "projects/garden-shed.md",
        "Garden shed",
        ("project/garden", "diy"),
        "2026-10-24T09:30:00+02:00",
        "# Garden shed\n\nPlan for a small shed at the end of the garden.\n\n"
        "![Shed sketch](garden-shed.attachments/sketch.png)\n\n## Tasks\n\n"
        "- [x] Measure the base\n- [ ] Order timber\n- [ ] Paint the door\n\n"
        "See also [[compost]].\n",
        ("garden-shed.attachments/sketch.png",),
    ),
    Note(
        "projects/website-redesign.md",
        "Website redesign",
        ("project/website", "work"),
        "2026-10-21",
        "# Website redesign\n\nRefresh the team site for the new year.\n\n"
        "- [ ] Collect feedback\n- [ ] Draft the new navigation\n- [x] Agree on "
        "goals in the [Q4 planning meeting](../work/q4-planning.md)\n",
    ),
    # Recipes
    Note(
        "recipes/meal-plan.md",
        "Meal plan",
        ("cooking",),
        "2026-10-25",
        "# Meal plan\n\n- Monday: [[lentil-soup]]\n- Wednesday: [[tomato-pasta]]\n"
        "- Saturday: [[sourdough-bread]]\n\n- [ ] Buy flour\n- [ ] Buy lentils\n",
    ),
    _recipe(
        "lentil-soup",
        "Lentil soup",
        "vegetarian",
        "10-20",
        "lentils, carrot, onion, cumin, stock",
    ),
    _recipe(
        "sourdough-bread",
        "Sourdough bread",
        "baking",
        "10-18",
        "flour, water, starter, salt",
    ),
    _recipe(
        "tomato-pasta",
        "Tomato pasta",
        "vegetarian",
        "10-15",
        "pasta, tomatoes, garlic, basil, olive oil",
    ),
    _recipe(
        "banana-bread",
        "Banana bread",
        "baking",
        "10-11",
        "bananas, flour, eggs, butter, sugar",
    ),
    _recipe(
        "vegetable-curry",
        "Vegetable curry",
        "vegetarian",
        "10-08",
        "chickpeas, spinach, coconut milk, curry paste",
    ),
    _recipe(
        "pancakes", "Pancakes", "baking", "10-05", "flour, milk, eggs, a pinch of salt"
    ),
    _recipe(
        "roast-vegetables",
        "Roast vegetables",
        "vegetarian",
        "09-28",
        "squash, peppers, red onion, rosemary",
    ),
    _recipe(
        "apple-crumble",
        "Apple crumble",
        "baking",
        "09-21",
        "apples, oats, butter, brown sugar",
    ),
    _recipe(
        "bean-chili",
        "Bean chili",
        "vegetarian",
        "09-14",
        "kidney beans, tomatoes, peppers, chili",
    ),
    # Reading
    Note(
        "reading/reading-list.md",
        "Reading list",
        ("reading",),
        "2026-10-23",
        f"# Reading list\n\n- [x] [[the-quiet-orchard]] {_done(1)}\n"
        "- [x] [[maps-of-small-rivers]]\n"
        "- [ ] [[a-year-of-bread]]\n- [ ] [[the-lighthouse-keepers-garden]]\n"
        "- [ ] [[notes-on-slow-travel]]\n",
    ),
    _book(
        "the-quiet-orchard",
        "The Quiet Orchard",
        "fiction",
        "10-19",
        4,
        "A gentle novel about a family orchard.",
    ),
    _book(
        "maps-of-small-rivers",
        "Maps of Small Rivers",
        "non-fiction",
        "10-12",
        5,
        "Essays on walking along rivers.",
    ),
    _book(
        "a-year-of-bread",
        "A Year of Bread",
        "non-fiction",
        "10-02",
        3,
        "One loaf a week for a year.",
    ),
    _book(
        "the-lighthouse-keepers-garden",
        "The Lighthouse Keeper's Garden",
        "fiction",
        "09-25",
        4,
        "A short novel set on an island.",
    ),
    _book(
        "notes-on-slow-travel",
        "Notes on Slow Travel",
        "non-fiction",
        "09-18",
        4,
        "Travelling by train and on foot.",
    ),
    _book(
        "the-winter-library",
        "The Winter Library",
        "fiction",
        "09-10",
        3,
        "A mystery in a snowed-in library.",
    ),
    # Travel
    Note(
        "travel/coast-trip.md",
        "Coast trip",
        ("travel", "travel/2026"),
        "2026-10-22",
        "# Coast trip\n\nThree days by the sea in November.\n\n## Packing\n\n"
        f"- [x] Rain jacket {_done(1)}\n- [ ] Walking boots\n"
        "- [ ] Book: [[notes-on-slow-travel]]\n",
    ),
    Note(
        "travel/mountain-weekend.md",
        "Mountain weekend",
        ("travel", "travel/2026"),
        "2026-09-30",
        "# Mountain weekend\n\nA short hike and a night in a hut.\n\n"
        "- [x] Book the hut\n- [x] Check the forecast\n",
    ),
    Note(
        "travel/travel-ideas.md",
        "Travel ideas",
        ("travel",),
        "2026-09-02",
        "# Travel ideas\n\n- A river walk from source to sea\n- A night train trip\n"
        "- Back to the coast: [[coast-trip]]\n",
    ),
    # Learning
    Note(
        "learning/spanish-verbs.md",
        "Spanish verbs",
        ("learning/languages", "spanish"),
        "2026-10-24",
        "# Spanish verbs\n\n| Verb | Meaning |\n|---|---|\n| hablar | to speak |\n"
        "| comer | to eat |\n| vivir | to live |\n\n- [ ] Practise ten minutes a day\n"
        f"- [x] Learn the present tense endings {_done(0)}\n",
    ),
    Note(
        "learning/docker-notes.md",
        "Docker notes",
        ("learning/tech", "homelab"),
        "2026-10-20",
        "# Docker notes\n\n- `docker compose up -d` starts a stack in the background.\n"
        "- `docker compose logs -f` follows its logs.\n\nUsed for [[home-server]].\n",
    ),
    Note(
        "learning/statistics-basics.md",
        "Statistics basics",
        ("learning",),
        "2026-09-27",
        "# Statistics basics\n\nMean, median and mode describe the middle of the "
        "data. Spread is about how far values sit from it.\n",
    ),
    Note(
        "learning/python-tips.md",
        "Python tips",
        ("learning/tech",),
        "2026-09-15",
        "# Python tips\n\n- Prefer `pathlib` for file paths.\n- Use virtual "
        "environments per project.\n",
    ),
    # Work
    Note(
        "work/q4-planning.md",
        "Q4 planning",
        ("work", "work/meetings"),
        "2026-10-21T15:00:00+00:00",
        "# Q4 planning\n\n## Decisions\n\n- Redesign the website: "
        "[[website-redesign]]\n- Move the weekly review to Fridays\n\n## Actions\n\n"
        f"- [ ] Share the plan with the team\n- [x] Book the next meeting {_done(6)}\n",
    ),
    Note(
        "work/weekly-review.md",
        "Weekly review",
        ("work", "work/planning"),
        "2026-10-24",
        "# Weekly review\n\n- What went well\n- What got in the way\n- Next week's "
        "three priorities\n\n- [ ] Clear the [[inbox-notes|inbox]]\n",
    ),
    Note(
        "work/onboarding-checklist.md",
        "Onboarding checklist",
        ("work", "work/planning"),
        "2026-09-12",
        "# Onboarding checklist\n\n- [x] Laptop ready\n"
        f"- [x] Accounts created {_done(9)}\n"
        "- [ ] Walk through the [[ideas-backlog]]\n",
    ),
    Note(
        "work/ideas-backlog.md",
        "Ideas backlog",
        ("work", "ideas"),
        "2026-10-16",
        "# Ideas backlog\n\n- A shared glossary\n- A monthly demo session\n"
        "- Fewer, shorter meetings\n",
    ),
    # Garden and home
    Note(
        "garden/tomatoes.md",
        "Tomatoes",
        ("garden",),
        "2026-08-30",
        "# Tomatoes\n\nSix plants this year; the cherry variety did best.\n\n"
        f"- [x] Save seeds {_done(5)}\n- [ ] Clear the bed before winter\n",
    ),
    Note(
        "garden/herbs.md",
        "Herbs",
        ("garden",),
        "2026-08-20",
        "# Herbs\n\nBasil, parsley and rosemary by the kitchen door. Basil goes "
        "into [[tomato-pasta]].\n",
    ),
    Note(
        "garden/compost.md",
        "Compost",
        ("garden", "project/garden"),
        "2026-10-02",
        "# Compost\n\nTurn the heap every two weeks. Next to the [[garden-shed]].\n\n"
        "- [ ] Turn the heap on Saturday\n- [ ] Buy a second bin\n",
    ),
    Note(
        "home/repairs.md",
        "Repairs",
        ("home",),
        "2026-10-13",
        "# Repairs\n\n- [ ] Fix the dripping tap\n"
        f"- [x] Replace the hall light {_done(2)}\n"
        "- [ ] Oil the gate\n",
    ),
    # Health, finance, music, inbox
    Note(
        "health/running-log.md",
        "Running log",
        ("health", "health/running"),
        "2026-10-25",
        "# Running log\n\n| Date | Distance |\n|---|---|\n| 2026-10-19 | 5 km |\n"
        "| 2026-10-22 | 6 km |\n| 2026-10-25 | 8 km |\n",
    ),
    Note(
        "health/sleep-notes.md",
        "Sleep notes",
        ("health",),
        "2026-10-09",
        "# Sleep notes\n\nScreens off an hour before bed made the biggest "
        "difference.\n",
    ),
    Note(
        "finance/budget-2026.md",
        "Budget 2026",
        ("finance", "finance/planning"),
        "2026-10-01",
        f"# Budget 2026\n\n- [x] Set the monthly savings goal {_done(3)}\n- [ ] Review "
        "subscriptions\n\nTrip money for the [[coast-trip]].\n",
    ),
    Note(
        "music/guitar-practice.md",
        "Guitar practice",
        ("music",),
        "2026-10-17",
        f"# Guitar practice\n\n- [x] Chord changes, five minutes {_done(0)}\n"
        "- [ ] Learn a new "
        "strumming pattern\n",
    ),
    Note(
        "music/playlists.md",
        "Playlists",
        ("music",),
        "2026-09-05",
        "# Playlists\n\n- Calm morning\n- Long drive\n- Cooking: see [[meal-plan]]\n",
    ),
    Note(
        "inbox/inbox-notes.md",
        "Inbox",
        ("inbox",),
        "2026-10-26",
        "# Inbox\n\nQuick captures to sort later:\n\n- [[gift-ideas]]\n"
        "- [[podcast-idea]]\n- [[tool-to-try]]\n",
    ),
    Note(
        "inbox/gift-ideas.md",
        "Gift ideas",
        ("inbox", "ideas"),
        "2026-10-25",
        "# Gift ideas\n\n- A plant for the office\n- A cookbook\n- Concert tickets\n",
    ),
    Note(
        "inbox/podcast-idea.md",
        "Podcast idea",
        ("inbox", "ideas"),
        "2026-10-18",
        "# Podcast idea\n\nShort episodes about one everyday object each.\n",
    ),
    Note(
        "inbox/tool-to-try.md",
        "Tool to try",
        ("inbox",),
        "2026-10-14",
        "# Tool to try\n\nA label printer for the [[home-server]] cables.\n",
    ),
    Note(
        "inbox/movies-to-watch.md",
        "Movies to watch",
        ("inbox",),
        "2026-09-20",
        "# Movies to watch\n\n- [ ] Something with mountains\n- [x] A comedy for "
        f"Friday night {_done(3)}\n",
    ),
    # Daily notes
    _daily(
        20, "- [x] Plan the week\n- [ ] Call the plumber", "Started [[lentil-soup]]."
    ),
    _daily(21, "- [x] Q4 planning meeting", "Notes in [[q4-planning]]."),
    _daily(
        22,
        "- [x] Pack for the coast\n- [ ] Book train tickets",
        "Updated [[coast-trip]].",
    ),
    _daily(23, "- [ ] Finish [[the-quiet-orchard]]", "Quiet day."),
    _daily(24, f"- [x] Weekly review {_done(2)}", "See [[weekly-review]]."),
    _daily(
        25,
        f"- [x] Long run, 8 km {_done(1)}\n- [ ] Order timber for the shed",
        "Logged in [[running-log]].",
    ),
    _daily(
        26,
        "- [ ] Sort the [[inbox-notes|inbox]]\n- [ ] Water the herbs",
        "Reading [[a-year-of-bread]].",
    ),
    # Templates
    Note(
        "templates/meeting.md",
        "Meeting",
        ("template",),
        "2026-09-01",
        "# Meeting\n\n## Agenda\n\n- \n\n## Decisions\n\n- \n\n## Actions\n\n- [ ] \n",
    ),
    Note(
        "templates/recipe.md",
        "Recipe",
        ("template", "cooking"),
        "2026-09-01",
        "# Recipe\n\n## Ingredients\n\n- \n\n## Method\n\n1. \n",
    ),
    Note(
        "templates/book.md",
        "Book",
        ("template", "reading"),
        "2026-09-01",
        "# Book\n\nRating: /5\n\n## Notes\n\n",
    ),
)


def _render(note: Note, today: date) -> str:
    body = _DAYS_AGO.sub(
        lambda days: (today - timedelta(days=int(days[1]))).isoformat(), note.body
    )
    extra = ""
    if body.startswith("---DEMO---\n"):
        body = body.removeprefix("---DEMO---\n")
        extra = "demo_vault: cerebrum-docs\n"
    tags = ", ".join(note.tags)
    return (
        f"---\ntitle: {note.title}\ntags: [{tags}]\nupdated: '{note.updated}'\n"
        f"{extra}---\n{body}"
    )


def build_vault(target: Path, today: date | None = None) -> None:
    """Write the vault into `target`, with done dates counted back from
    `today` (the local date when not given)."""
    if target.exists() and any(target.iterdir()):
        raise SystemExit(f"refusing to write into {target}: it is not empty")
    day = today or date.today()
    for note in NOTES:
        path = target / note.path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_render(note, day), encoding="utf-8")
        for image in note.images:
            image_path = path.parent / image
            image_path.parent.mkdir(parents=True, exist_ok=True)
            image_path.write_bytes(_png(160, 96, (196, 154, 92)))


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    build_vault(Path(argv[1]))
    print(f"Wrote {len(NOTES)} demo notes to {argv[1]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
