//! Hub mode state — persisted toggle that controls how the sidecar
//! is launched.
//!
//! When `enabled = true`, the Tauri shell spawns the bundled sidecar
//! in headless mode (binds `0.0.0.0` on a stable port, serves HTTPS
//! with the self-signed cert managed by `speechtotext.api.tls`). When
//! `enabled = false`, the original local-only sidecar lifecycle stays
//! in effect (`127.0.0.1` + random port + stdout handshake).
//!
//! State is persisted to `<app-data>/hub_state.json` so the toggle
//! survives across launches.

use serde::{Deserialize, Serialize};
use std::fs;
use std::path::PathBuf;
use std::sync::Mutex;
use tauri::{AppHandle, Manager};

const HUB_STATE_FILE: &str = "hub_state.json";
/// Default LAN port. Mirrors `LOCALLEXIS_PORT`'s default in
/// `speechtotext.api.server.headless` so the Python and Rust sides
/// agree on the wire even before the file exists.
pub const DEFAULT_PORT: u16 = 8765;

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct HubState {
    pub enabled: bool,
    pub port: u16,
}

impl Default for HubState {
    fn default() -> Self {
        Self {
            enabled: false,
            port: DEFAULT_PORT,
        }
    }
}

/// Thread-safe holder; managed by Tauri so commands can `state()`-it.
#[derive(Default)]
pub struct HubStateCell(pub Mutex<HubState>);

fn state_file_path(app: &AppHandle) -> Result<PathBuf, String> {
    let dir = app
        .path()
        .app_data_dir()
        .map_err(|e| format!("app_data_dir lookup failed: {e}"))?;
    Ok(dir.join(HUB_STATE_FILE))
}

/// Load the persisted state. Missing file, unreadable file, and
/// unparseable JSON all degrade silently to `HubState::default()` —
/// hub mode is opt-in, so the safe failure mode is "off".
pub fn load(app: &AppHandle) -> HubState {
    let path = match state_file_path(app) {
        Ok(p) => p,
        Err(_) => return HubState::default(),
    };
    let bytes = match fs::read(&path) {
        Ok(b) => b,
        Err(_) => return HubState::default(),
    };
    serde_json::from_slice(&bytes).unwrap_or_default()
}

/// Atomic write: tmp + rename so a crashed write never produces a
/// half-written file the next launch would silently default away from.
pub fn save(app: &AppHandle, state: &HubState) -> Result<(), String> {
    let path = state_file_path(app)?;
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)
            .map_err(|e| format!("mkdir {} failed: {e}", parent.display()))?;
    }
    let bytes = serde_json::to_vec_pretty(state)
        .map_err(|e| format!("hub state json encode failed: {e}"))?;
    let tmp = path.with_extension("json.tmp");
    fs::write(&tmp, bytes).map_err(|e| format!("write tmp failed: {e}"))?;
    fs::rename(&tmp, &path).map_err(|e| format!("rename failed: {e}"))?;
    Ok(())
}

#[tauri::command]
pub fn get_hub_state(state: tauri::State<HubStateCell>) -> HubState {
    state.0.lock().unwrap().clone()
}

#[tauri::command]
pub fn set_hub_state(
    app: AppHandle,
    state: tauri::State<HubStateCell>,
    enabled: bool,
    port: Option<u16>,
) -> Result<HubState, String> {
    let new_state = HubState {
        enabled,
        port: port.unwrap_or(DEFAULT_PORT),
    };
    save(&app, &new_state)?;
    *state.0.lock().unwrap() = new_state.clone();
    // Bounce the sidecar so the new mode takes effect immediately;
    // the user expects toggling the switch to "do something now"
    // rather than requiring an app restart.
    crate::sidecar::restart(&app)?;
    Ok(new_state)
}
