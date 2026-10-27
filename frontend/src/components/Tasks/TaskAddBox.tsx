import { type FormEvent, useId, useRef, useState } from "react";
import { errorMessage } from "../../api/client";

interface TaskAddBoxProps {
  /** Adds the task; rejects when it wasn't added. */
  onAdd: (text: string) => Promise<void>;
  /** Offline: shown, but nothing can be added. */
  disabled?: boolean;
}

/** The box at the top of the Tasks page that adds a task to today's daily
 * note. It keeps focus after each add, so several tasks go in one after
 * another; a failed add keeps the text, with the reason beneath. */
export function TaskAddBox({ onAdd, disabled = false }: TaskAddBoxProps) {
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const busy = useRef(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const errorId = useId();

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    // Whitespace alone adds nothing, and says nothing either.
    const submitted = text.trim();
    if (busy.current || disabled || !submitted) return;
    busy.current = true;
    setAdding(true);
    setError(null);
    try {
      await onAdd(submitted);
      // Only the text sent goes: what was typed meanwhile is the next task.
      setText((current) => (current.trim() === submitted ? "" : current));
    } catch (err) {
      setError(`The task wasn't added: ${errorMessage(err)}`);
    } finally {
      busy.current = false;
      setAdding(false);
      inputRef.current?.focus();
    }
  }

  return (
    <form className="task-add" onSubmit={handleSubmit}>
      <div className="task-add-row">
        <input
          ref={inputRef}
          type="text"
          className="task-add-input"
          aria-label="New task"
          placeholder="Add a task to today's note"
          enterKeyHint="done"
          value={text}
          disabled={disabled}
          aria-invalid={error !== null}
          aria-describedby={error ? errorId : undefined}
          onChange={(event) => {
            setText(event.target.value);
            setError(null);
          }}
        />
        {/* Not disabled while an add is in flight: the box keeps focus
            and a second Enter is simply ignored until the first lands. */}
        <button
          type="submit"
          className="btn btn-primary task-add-button"
          disabled={disabled}
          aria-busy={adding}
        >
          Add
        </button>
      </div>
      {error && (
        <p id={errorId} className="error-text task-add-error" role="alert">
          {error}
        </p>
      )}
    </form>
  );
}
