// A full-page navigation to another origin (the sign-in provider). Its own
// module so tests can replace it: jsdom's `window.location` cannot be
// stubbed, and a real assign would try to navigate the test window.
export function redirectTo(url: string): void {
  window.location.assign(url);
}
