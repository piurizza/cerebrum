use tauri::menu::{Menu, MenuItem, PredefinedMenuItem, Submenu};
use tauri::{AppHandle, Manager, Runtime, Url};

/// Menu item that sends the window back to the bundled server-address
/// screen. The window otherwise shows the server's own page, which has no
/// access to the app (no `remote` capability, by design), so switching
/// servers has to start from the native side.
const CHANGE_SERVER_ID: &str = "change-server";

/// A page bundled with the app. Tauri serves them from `tauri://localhost`
/// on Linux and macOS and from `http://tauri.localhost` on Windows.
fn bundled_url(path: &str) -> Option<Url> {
    let base = if cfg!(windows) {
        "http://tauri.localhost/"
    } else {
        "tauri://localhost/"
    };
    Url::parse(base).and_then(|url| url.join(path)).ok()
}

fn app_menu<R: Runtime>(app: &AppHandle<R>) -> tauri::Result<Menu<R>> {
    let change_server =
        MenuItem::with_id(app, CHANGE_SERVER_ID, "Change server…", true, None::<&str>)?;
    let cerebrum = Submenu::with_items(
        app,
        "Cerebrum",
        true,
        &[
            &change_server,
            &PredefinedMenuItem::separator(app)?,
            &PredefinedMenuItem::quit(app, None)?,
        ],
    )?;
    // Replacing the default menu would drop its Edit menu, and with it
    // copy, paste and undo shortcuts on macOS.
    let edit = Submenu::with_items(
        app,
        "Edit",
        true,
        &[
            &PredefinedMenuItem::undo(app, None)?,
            &PredefinedMenuItem::redo(app, None)?,
            &PredefinedMenuItem::separator(app)?,
            &PredefinedMenuItem::cut(app, None)?,
            &PredefinedMenuItem::copy(app, None)?,
            &PredefinedMenuItem::paste(app, None)?,
            &PredefinedMenuItem::select_all(app, None)?,
        ],
    )?;
    Menu::with_items(app, &[&cerebrum, &edit])
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_store::Builder::new().build())
        .plugin(tauri_plugin_http::init())
        .menu(app_menu)
        .on_menu_event(|app, event| {
            if event.id() != CHANGE_SERVER_ID {
                return;
            }
            let (Some(window), Some(url)) = (
                app.get_webview_window("main"),
                bundled_url("index.html?change-server=1"),
            ) else {
                return;
            };
            let _ = window.navigate(url);
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
