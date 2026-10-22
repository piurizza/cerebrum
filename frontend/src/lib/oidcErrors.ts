// The server's OpenID Connect callback reports every failure by redirecting
// to `/login`, `/register` or `/settings` with `?oidc_error=<code>`. The
// codes come from a fixed list on the server; this maps each one to the text
// the page shows. Anything else in the parameter -- a code added later, or a
// hand-edited URL -- gets the generic message, and the raw value is never
// shown, so a crafted link cannot put its own words on the login page.

const MESSAGES: Record<string, string> = {
  not_linked:
    "That account isn't linked to any Cerebrum account. Ask an admin for an invite, or sign in another way and link it from Settings.",
  inactive: "This Cerebrum account has been deactivated.",
  invite_invalid: "That invite token is invalid, expired or already used.",
  username_taken: "That username is already taken. Choose another one.",
  already_linked:
    "That account is already linked to a Cerebrum account, or this Cerebrum account already has one linked.",
  provider_error: "The sign-in provider reported an error. Try again.",
  expired: "The sign-in attempt took too long or was interrupted. Try again.",
};

export const GENERIC_OIDC_ERROR = "Signing in with the provider failed. Try again.";

/** The message for an `oidc_error` query value, or null when there is none. */
export function oidcErrorMessage(code: string | null): string | null {
  if (code === null) return null;
  return Object.hasOwn(MESSAGES, code) ? MESSAGES[code] : GENERIC_OIDC_ERROR;
}
