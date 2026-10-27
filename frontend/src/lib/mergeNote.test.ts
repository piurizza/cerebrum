import { describe, expect, it } from "vitest";
import { mergeNote } from "./mergeNote";

const BASE = "# Shed\n\nMeasure the door\nOrder timber\n";
const TASK = "- [ ] Water the herbs";

describe("mergeNote", () => {
  it("keeps an edit to the first line and a task appended elsewhere", () => {
    const mine = "# Garden shed\n\nMeasure the door\nOrder timber\n";
    const theirs = `${BASE}${TASK}\n`;

    expect(mergeNote(BASE, mine, theirs)).toEqual({
      ok: true,
      text: `# Garden shed\n\nMeasure the door\nOrder timber\n${TASK}\n`,
    });
  });

  it("puts an appended task after an edit to the last line", () => {
    // diff3 alone reports this end region as a conflict.
    const mine = "# Shed\n\nMeasure the door\nOrder timber for the roof\n";
    const theirs = `${BASE}${TASK}\n`;

    expect(mergeNote(BASE, mine, theirs)).toEqual({
      ok: true,
      text: `# Shed\n\nMeasure the door\nOrder timber for the roof\n${TASK}\n`,
    });
  });

  it("puts an appended task after lines both sides appended", () => {
    const mine = `${BASE}Paint it green\n`;
    const theirs = `${BASE}${TASK}\n`;

    expect(mergeNote(BASE, mine, theirs)).toEqual({
      ok: true,
      text: `${BASE}Paint it green\n${TASK}\n`,
    });
  });

  it("refuses when both sides changed the same line", () => {
    const mine = "# Shed\n\nMeasure the door twice\nOrder timber\n";
    const theirs = "# Shed\n\nMeasure the window\nOrder timber\n";

    expect(mergeNote(BASE, mine, theirs)).toEqual({ ok: false });
  });

  it("refuses an overlap even when theirs also appended at the end", () => {
    const mine = "# Shed\n\nMeasure the door twice\nOrder timber\n";
    const theirs = `# Shed\n\nMeasure the window\nOrder timber\n${TASK}\n`;

    expect(mergeNote(BASE, mine, theirs)).toEqual({ ok: false });
  });

  it("combines changes to different lines in the middle", () => {
    const base = "a\nb\nc\nd\ne\n";
    const mine = "A\nb\nc\nd\ne\n";
    const theirs = "a\nb\nc\nd\nE\n";

    expect(mergeNote(base, mine, theirs)).toEqual({
      ok: true,
      text: "A\nb\nc\nd\nE\n",
    });
  });

  it("returns mine when theirs is unchanged", () => {
    expect(mergeNote(BASE, "anything\n", BASE)).toEqual({
      ok: true,
      text: "anything\n",
    });
  });

  it("treats the same edit on both sides as clean", () => {
    const both = "# Shed\n\nMeasure the door twice\nOrder timber\n";

    expect(mergeNote(BASE, both, both)).toEqual({ ok: true, text: both });
  });

  it("adds a trailing newline when theirs appended to a note without one", () => {
    const base = "Measure the door";
    const mine = "Measure the door twice";
    const theirs = `Measure the door\n${TASK}\n`;

    expect(mergeNote(base, mine, theirs)).toEqual({
      ok: true,
      text: `Measure the door twice\n${TASK}\n`,
    });
  });

  it("keeps mine's choice when only mine changed the trailing newline", () => {
    const base = "a\nb\n";
    const mine = "A\nb";
    const theirs = "a\nb\n";

    expect(mergeNote(base, mine, theirs)).toEqual({ ok: true, text: "A\nb" });
  });

  it("appends to an empty note", () => {
    expect(mergeNote("", "Hello\n", `${TASK}\n`)).toEqual({
      ok: true,
      text: `Hello\n${TASK}\n`,
    });
  });
});
