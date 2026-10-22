// @vitest-environment node
import { describe, expect, it } from "vitest";
import { GENERIC_OIDC_ERROR, oidcErrorMessage } from "./oidcErrors";

describe("oidcErrorMessage", () => {
  it("returns null when there is no error parameter", () => {
    expect(oidcErrorMessage(null)).toBeNull();
  });

  it.each([
    "not_linked",
    "inactive",
    "invite_invalid",
    "username_taken",
    "already_linked",
    "provider_error",
    "expired",
  ])("maps the known code %s to its own message", (code) => {
    const message = oidcErrorMessage(code);
    expect(message).toBeTruthy();
    expect(message).not.toBe(GENERIC_OIDC_ERROR);
    expect(message).not.toContain(code);
  });

  it("tells an unlinked person to ask for an invite or link from Settings", () => {
    expect(oidcErrorMessage("not_linked")).toMatch(/invite/);
    expect(oidcErrorMessage("not_linked")).toMatch(/Settings/);
  });

  it.each(["<b>pwned</b>", "toString", "__proto__", ""])(
    "falls back to the generic message for %j, never echoing it",
    (code) => {
      expect(oidcErrorMessage(code)).toBe(GENERIC_OIDC_ERROR);
    },
  );
});
