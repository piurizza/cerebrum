import { type FormEvent, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { errorMessage, register } from "../api/client";

export function RegisterPage() {
  const navigate = useNavigate();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [token, setToken] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      // Registration doesn't establish a session by itself -- the backend
      // doesn't return a token here, so the user must log in afterward.
      await register(username, password, token);
      navigate("/login", { state: { registered: true, username } });
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="auth-page">
      <form className="auth-form" onSubmit={handleSubmit}>
        <h1>Register</h1>
        <label className="rename-field">
          Username
          <input
            type="text"
            autoComplete="username"
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            required
          />
        </label>
        <label className="rename-field">
          Password
          <input
            type="password"
            autoComplete="new-password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            required
          />
        </label>
        <label className="rename-field">
          Invite token
          <input
            type="text"
            value={token}
            onChange={(event) => setToken(event.target.value)}
            required
          />
        </label>
        <button
          type="submit"
          className="btn btn-primary btn-block"
          disabled={submitting}
        >
          {submitting ? "Registering..." : "Register"}
        </button>
        {error && (
          <p className="error-text" role="alert">
            {error}
          </p>
        )}
        <p className="auth-switch">
          Already have an account? <Link to="/login">Log in</Link>
        </p>
      </form>
    </div>
  );
}
