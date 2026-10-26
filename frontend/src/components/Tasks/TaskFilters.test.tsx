import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { TaskFilters } from "./TaskFilters";

function Harness({
  folders,
  onChange,
}: {
  folders: string[];
  onChange: (folder: string, words: string) => void;
}) {
  const [folder, setFolder] = useState("");
  const [words, setWords] = useState("");
  return (
    <TaskFilters
      folders={folders}
      folder={folder}
      words={words}
      onFolderChange={(value) => {
        setFolder(value);
        onChange(value, words);
      }}
      onWordsChange={(value) => {
        setWords(value);
        onChange(folder, value);
      }}
    />
  );
}

describe("TaskFilters", () => {
  it("offers every folder holding tasks after All folders", () => {
    render(<Harness folders={["home", "work", "work/clients"]} onChange={() => {}} />);

    const select = screen.getByRole("combobox", { name: "Folder" });
    expect(
      within(select)
        .getAllByRole("option")
        .map((option) => option.textContent),
    ).toEqual(["All folders", "home", "work", "work/clients"]);
    expect(select).toHaveValue("");
  });

  it("reports the folder picked and the words as they are typed", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<Harness folders={["home", "work"]} onChange={onChange} />);

    await user.selectOptions(screen.getByRole("combobox", { name: "Folder" }), "work");
    expect(onChange).toHaveBeenLastCalledWith("work", "");

    await user.type(screen.getByRole("searchbox", { name: "Filter by words" }), "ti");
    expect(onChange).toHaveBeenNthCalledWith(2, "work", "t");
    expect(onChange).toHaveBeenLastCalledWith("work", "ti");
  });

  it("keeps a picked folder listed after its last task is gone", () => {
    render(
      <TaskFilters
        folders={["home"]}
        folder="work"
        words=""
        onFolderChange={() => {}}
        onWordsChange={() => {}}
      />,
    );

    expect(screen.getByRole("combobox", { name: "Folder" })).toHaveValue("work");
  });
});
