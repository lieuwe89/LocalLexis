mod ble;
mod hub_state;
mod sidecar;

use tauri::Manager;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let app = tauri::Builder::default()
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
            ble::ble_scan_recorders,
            ble::ble_read_recorder_hello,
            ble::ble_send_recorder_provisioning,
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
        .build(tauri::generate_context!())
        .expect("error while building tauri application");

    // `RunEvent::ExitRequested` covers Cmd+Q, the dock Quit menu, and
    // programmatic `app.exit()` — paths that `WindowEvent::CloseRequested`
    // misses on macOS, where closing the last window doesn't quit the
    // app by default. `RunEvent::Exit` is the final hook before the
    // process tears down; we run cleanup there so it fires even on
    // unusual exit paths.
    //
    // We deliberately do *not* hook CloseRequested any more: the
    // sidecar must survive a closed window so the app can be re-opened
    // from the dock without restarting the backend. Cleanup runs only
    // when the process is actually about to exit.
    app.run(|app_handle, event| {
        if matches!(event, tauri::RunEvent::Exit) {
            let state: tauri::State<sidecar::SidecarChild> = app_handle.state();
            let child = state.0.lock().unwrap().take();
            if let Some(child) = child {
                sidecar::terminate_child_tree(child);
            }
        }
    });
}
