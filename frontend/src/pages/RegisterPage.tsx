import { type FormEvent, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { errorMessage, register, startOidc } from "../api/client";
import { useAuthMethods, useOneShotSearchParams } from "../hooks/useAuthMethods";
import { oidcErrorMessage } from "../lib/oidcErrors";
import { redirectTo } from "../lib/redirect";

// A failed provider sign-up comes back as
// `/register?oidc_error=<code>&username=<name>` -- never with the invite
// token, which the person re-enters.
const QUERY_PARAMS = ["oidc_error", "username"] as const;

type InvalidField = "username" | "token" | null;

export function RegisterPage() {
  const navigate = useNavigate();
  const methodsState = useAuthMethods();
  const { oidc_error: oidcError, username: returnedUsername } =
    useOneShotSearchParams(QUERY_PARAMS);
  const [username, setUsername] = useState(returnedUsername ?? "");
  const [password, setPassword] = useState("");
  const [token, setToken] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(() => oidcErrorMessage(oidcError));
  const [invalidField, setInvalidField] = useState<InvalidField>(null);
  const usernameRef = useRef<HTMLInputElement>(null);
  const tokenRef = useRef<HTMLInputElement>(null);

  const loadingMethods = methodsState.status === "loading";
  const methods = methodsState.status === "ready" ? methodsState.methods : null;
  const provider = methods?.oidc ?? null;
  // No provider, or the methods call failed: the password form as it was.
  const showPassword = provider === null || methods?.password_login !== false;

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (!showPassword) {
      await handleProviderSignUp();
      return;
    }
    setError(null);
    setInvalidField(null);
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

  // A `type="button"`, so the form's own `required` checks (which include
  // the password) don't apply; the two fields the provider route needs are
  // checked here instead. The server validates both again before the round
  // trip (KTD5), so a bad invite or a taken username shows on this form.
  async function handleProviderSignUp() {
    if (!username.trim()) {
      setInvalidField("username");
      setError("Choose a username.");
      usernameRef.current?.focus();
      return;
    }
    if (!token.trim()) {
      setInvalidField("token");
      setError("Enter your invite token.");
      tokenRef.current?.focus();
      return;
    }
    setError(null);
    setInvalidField(null);
    setStarting(true);
    try {
      const { authorization_url } = await startOidc({
        intent: "register",
        username,
        invite_token: token,
      });
      redirectTo(authorization_url);
    } catch (err) {
      setError(errorMessage(err));
      setStarting(false);
    }
  }

  const usernameField = (
    <label className="rename-field">
      Username
      <input
        ref={usernameRef}
        type="text"
        autoComplete="username"
        value={username}
        onChange={(event) => {
          setUsername(event.target.value);
          if (invalidField === "username") setInvalidField(null);
        }}
        disabled={loadingMethods}
        aria-invalid={invalidField === "username" || undefined}
        required
      />
    </label>
  );
  const passwordField = (
    <label className="rename-field">
      Password
      <input
        type="password"
        autoComplete="new-password"
        value={password}
        onChange={(event) => setPassword(event.target.value)}
        disabled={loadingMethods}
        required
      />
    </label>
  );
  const tokenField = (
    <label className="rename-field">
      Invite token
      <input
        ref={tokenRef}
        type="text"
        value={token}
        onChange={(event) => {
          setToken(event.target.value);
          if (invalidField === "token") setInvalidField(null);
        }}
        disabled={loadingMethods}
        aria-invalid={invalidField === "token" || undefined}
        required
      />
    </label>
  );
  const registerButton = (
    <button
      type="submit"
      className="btn btn-primary btn-block"
      disabled={submitting || loadingMethods}
    >
      {submitting ? "Registering..." : "Register"}
    </button>
  );

  return (
    <div className="auth-page">
      <form className="auth-form" onSubmit={handleSubmit}>
        <h1>Register</h1>
        {methodsState.status === "failed" && (
          <p className="auth-notice auth-notice-action">
            Could not load sign-in options
            <button type="button" className="btn btn-sm" onClick={methodsState.retry}>
              Retry
            </button>
          </p>
        )}
        {provider ? (
          <>
            {usernameField}
            {tokenField}
            <button
              type="button"
              className="btn btn-primary btn-block"
              onClick={handleProviderSignUp}
              disabled={starting}
            >
              Sign up with {provider.provider_name}
            </button>
            {showPassword && (
              <>
                <p className="auth-divider">or</p>
                {passwordField}
                {registerButton}
              </>
            )}
          </>
        ) : (
          <>
            {usernameField}
            {passwordField}
            {tokenField}
            {registerButton}
          </>
        )}
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
