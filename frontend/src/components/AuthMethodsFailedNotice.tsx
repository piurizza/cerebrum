/** Shown on the login and register pages when the sign-in methods call
 * failed: the page has fallen back to the password form, and this offers
 * to try again. */
export function AuthMethodsFailedNotice({ onRetry }: { onRetry: () => void }) {
  return (
    <p className="auth-notice auth-notice-action">
      Could not load sign-in options
      <button type="button" className="btn btn-sm" onClick={onRetry}>
        Retry
      </button>
    </p>
  );
}
