mod hub_state;
mod sidecar;

use tauri::Manager;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .plugin(tauri_plugin_process::init())
        .manage(sidecar::SidecarUrl::default())
        .manage(sidecar::SidecarToken::default())
        .manage(sidecar::SidecarChild::default())
        .manage(hub_state::HubStateCell::default())
        .invoke_handler(tauri::generate_handler![
            sidecar::sidecar_url,
            hub_state::get_hub_state,
            hub_state::set_hub_state,
        ])
        .setup(|app| {
            // Load persisted hub state once at startup so the first
            // sidecar::spawn sees the right mode without an extra
            // restart.
            let initial = hub_state::load(&app.handle());
            {
                let cell: tauri::State<hub_state::HubStateCell> =
                    app.state();
                *cell.0.lock().unwrap() = initial;
            }
            sidecar::spawn(&app.handle()).expect("failed to start sidecar");
            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::CloseRequested { .. } = event {
                let state: tauri::State<sidecar::SidecarChild> = window.state();
                let child = state.0.lock().unwrap().take();
                if let Some(child) = child {
                    let _ = child.kill();
                }
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
