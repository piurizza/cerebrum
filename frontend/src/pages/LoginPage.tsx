import { type FormEvent, useEffect, useRef, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { errorMessage, startOidc } from "../api/client";
import { AuthMethodsFailedNotice } from "../components/AuthMethodsFailedNotice";
import { useAuth } from "../context/AuthContext";
import { useAuthMethods, useOneShotSearchParams } from "../hooks/useAuthMethods";
import { oidcErrorMessage } from "../lib/oidcErrors";
import { redirectTo } from "../lib/redirect";

const QUERY_PARAMS = ["oidc_error"] as const;
const PASSWORD_FIELDS_ID = "password-sign-in";

export function LoginPage() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const methodsState = useAuthMethods();
  const { oidc_error: oidcError } = useOneShotSearchParams(QUERY_PARAMS);
  const [username, setUsername] = useState(
    (location.state as { username?: string } | null)?.username ?? "",
  );
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [starting, setStarting] = useState(false);
  // A failed provider round trip comes back as `?oidc_error=<code>`; its
  // message is the page's first error, replaced by any later one.
  const [error, setError] = useState<string | null>(() => oidcErrorMessage(oidcError));
  const [passwordOpen, setPasswordOpen] = useState(false);
  const usernameRef = useRef<HTMLInputElement>(null);
  const focusUsernameOnOpen = useRef(false);
  const registered = Boolean(
    (location.state as { registered?: boolean } | null)?.registered,
  );

  const loadingMethods = methodsState.status === "loading";
  const methods = methodsState.status === "ready" ? methodsState.methods : null;
  const provider = methods?.oidc ?? null;
  // With password login switched off, the fields are still needed by
  // admins (break-glass) and by not-yet-linked accounts, so they collapse
  // behind a toggle rather than disappearing.
  const passwordCollapsible = provider !== null && methods?.password_login === false;

  useEffect(() => {
    if (passwordOpen && focusUsernameOnOpen.current) {
      focusUsernameOnOpen.current = false;
      usernameRef.current?.focus();
    }
  }, [passwordOpen]);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await login(username, password);
      navigate("/");
    } catch (err) {
      // No special-casing needed here: the backend's own detail text for
      // a login failure is already the right generic message ("Invalid
      // username or password") for both a wrong password and an unknown
      // username -- see api/auth.py's `login()`. `errorMessage()` surfaces
      // that text as-is.
      setError(errorMessage(err));
    } finally {
      setSubmitting(false);
    }
  }

  // Leaves the logout tombstone alone on purpose (KTD13): only a
  // successful round trip, landing on `/?oidc=1`, may clear it, and
  // AuthContext does that when it mounts there.
  async function handleProviderSignIn() {
    setError(null);
    setStarting(true);
    try {
      const { authorization_url } = await startOidc({ intent: "login" });
      redirectTo(authorization_url);
    } catch (err) {
      setError(errorMessage(err));
      setStarting(false);
    }
  }

  function togglePasswordFields() {
    focusUsernameOnOpen.current = !passwordOpen;
    setPasswordOpen((open) => !open);
  }

  const passwordFields = (
    <>
      <label className="rename-field">
        Username
        <input
          ref={usernameRef}
          type="text"
          autoComplete="username"
          value={username}
          onChange={(event) => setUsername(event.target.value)}
          disabled={loadingMethods}
          required
        />
      </label>
      <label className="rename-field">
        Password
        <input
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          disabled={loadingMethods}
          required
        />
      </label>
      <button
        type="submit"
        className="btn btn-primary btn-block"
        disabled={submitting || loadingMethods}
      >
        {submitting ? "Logging in..." : "Log in"}
      </button>
    </>
  );

  return (
    <div className="auth-page">
      <form className="auth-form" onSubmit={handleSubmit}>
        <h1>Log in</h1>
        {registered && (
          <p className="auth-notice">Account created. Log in to continue.</p>
        )}
        {methodsState.status === "failed" && (
          <AuthMethodsFailedNotice onRetry={methodsState.retry} />
        )}
        {provider && (
          <>
            <button
              type="button"
              className="btn btn-primary btn-block"
              onClick={handleProviderSignIn}
              disabled={starting}
            >
              Sign in with {provider.provider_name}
            </button>
            {passwordCollapsible ? (
              <button
                type="button"
                className="btn btn-block"
                aria-expanded={passwordOpen}
                aria-controls={PASSWORD_FIELDS_ID}
                onClick={togglePasswordFields}
              >
                Sign in with a password
              </button>
            ) : (
              <p className="auth-divider">or</p>
            )}
          </>
        )}
        {passwordCollapsible ? (
          <div
            id={PASSWORD_FIELDS_ID}
            className="auth-password-fields"
            hidden={!passwordOpen}
          >
            {passwordOpen && passwordFields}
          </div>
        ) : (
          passwordFields
        )}
        {error && (
          <p className="error-text" role="alert">
            {error}
          </p>
        )}
        <p className="auth-switch">
          Need an account? <Link to="/register">Register</Link>
        </p>
      </form>
    </div>
  );
}
