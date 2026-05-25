use std::collections::HashMap;
use std::fmt::Write as _;
use std::path::PathBuf;
use std::sync::Mutex;
use tauri::{AppHandle, Manager, State};
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;

use crate::hub_state::{HubState, HubStateCell};

#[derive(Default)]
pub struct SidecarUrl(pub Mutex<Option<String>>);

pub struct SidecarToken(pub Mutex<String>);

impl Default for SidecarToken {
    fn default() -> Self {
        Self(Mutex::new(String::new()))
    }
}

pub struct SidecarChild(pub Mutex<Option<CommandChild>>);

impl Default for SidecarChild {
    fn default() -> Self {
        Self(Mutex::new(None))
    }
}

#[derive(serde::Serialize, Clone)]
pub struct SidecarInfo {
    pub url: Option<String>,
    pub token: String,
}

#[tauri::command]
pub fn sidecar_url(
    url_state: State<SidecarUrl>,
    token_state: State<SidecarToken>,
) -> SidecarInfo {
    SidecarInfo {
        url: url_state.0.lock().unwrap().clone(),
        token: token_state.0.lock().unwrap().clone(),
    }
}

fn generate_token() -> String {
    // 32 bytes of OS randomness → 64 hex chars. Enough entropy that a local
    // attacker cannot brute-force the token during the app lifetime.
    let mut bytes = [0u8; 32];
    getrandom::getrandom(&mut bytes).expect("getrandom failed");
    let mut s = String::with_capacity(64);
    for b in bytes.iter() {
        write!(s, "{:02x}", b).unwrap();
    }
    s
}

/// Pick a free loopback port for the Tauri webview ↔ sidecar HTTP
/// channel when hub mode is on.
///
/// Hub mode binds the sidecar to HTTPS on `0.0.0.0:<hub.port>` for LAN
/// devices, but WebKit / WebView2 reject the self-signed cert if the
/// webview itself dials that socket. The sidecar therefore additionally
/// serves plain HTTP on `127.0.0.1:<loopback>` for the desktop UI; this
/// helper picks an OS-assigned port for it.
///
/// Race window: we bind, read the port, then drop the listener so the
/// sidecar can bind it itself. Another process could in theory grab the
/// port in between — vanishingly unlikely on a desktop machine, and the
/// failure mode (sidecar fails to start) is loud.
fn pick_free_loopback_port() -> Result<u16, String> {
    use std::net::TcpListener;
    let listener = TcpListener::bind("127.0.0.1:0")
        .map_err(|e| format!("bind loopback port failed: {e}"))?;
    let port = listener
        .local_addr()
        .map_err(|e| format!("local_addr failed: {e}"))?
        .port();
    drop(listener);
    Ok(port)
}

fn locate_bundled_models(app: &AppHandle) -> Option<PathBuf> {
    let mut candidates: Vec<PathBuf> = Vec::new();
    if let Ok(resource_dir) = app.path().resource_dir() {
        candidates.push(resource_dir.join("resources").join("models"));
        candidates.push(resource_dir.join("_up_").join("resources").join("models"));
        candidates.push(resource_dir.join("models"));
    }
    // Dev fallback: tauri-cli runs the binary out of target/debug; resources
    // are only copied into the bundle for release builds. Use the compile-time
    // source dir to reach them in dev.
    let manifest_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    candidates.push(manifest_dir.join("resources").join("models"));

    for c in candidates {
        if c.is_dir() {
            return Some(c);
        }
    }
    None
}

/// Spawn the sidecar according to the current hub state.
///
/// - hub off (default): localhost-only, random port, stdout JSON
///   handshake parsed for URL discovery. Same behaviour as before
///   block 4.
/// - hub on: `LOCALLEXIS_HEADLESS=1` flips the entry point to
///   `server.headless`, which serves HTTPS on `0.0.0.0:<hub.port>`
///   for LAN devices *and* plain HTTP on `127.0.0.1:<loopback>` for
///   the Tauri webview (WebKit / WebView2 reject the self-signed
///   cert on the LAN socket). No stdout handshake — the loopback
///   port is allocated here and threaded into the sidecar via
///   `LOCALLEXIS_LOOPBACK_PORT`; the URL state is set directly so
///   the frontend can dial without waiting.
pub fn spawn(app: &AppHandle) -> Result<(), String> {
    let hub: HubState = {
        let cell: State<HubStateCell> = app.state();
        let snapshot = cell.0.lock().unwrap().clone();
        snapshot
    };

    // Generate the bearer token first and stash it in state, so the frontend
    // already sees a valid token by the time it polls sidecar_url. The same
    // string goes to the sidecar via LOCALLEXIS_API_TOKEN; the sidecar's
    // FastAPI middleware enforces Authorization: Bearer <token> on every
    // request when that env var is set.
    let token = generate_token();
    {
        let token_state: State<SidecarToken> = app.state();
        *token_state.0.lock().unwrap() = token.clone();
    }

    let mut env: HashMap<String, String> = HashMap::new();
    env.insert("LOCALLEXIS_API_TOKEN".to_string(), token);

    // Hub-mode dual-bind loopback port. Allocated up front so we can
    // (a) inject it into the sidecar env and (b) set the SidecarUrl
    // state below without waiting for any stdout handshake.
    let loopback_port: Option<u16> = if hub.enabled {
        env.insert("LOCALLEXIS_HEADLESS".to_string(), "1".to_string());
        env.insert("LOCALLEXIS_HOST".to_string(), "0.0.0.0".to_string());
        env.insert("LOCALLEXIS_PORT".to_string(), hub.port.to_string());
        env.insert("LOCALLEXIS_TLS_ENABLED".to_string(), "1".to_string());
        let p = pick_free_loopback_port()?;
        env.insert("LOCALLEXIS_LOOPBACK_PORT".to_string(), p.to_string());
        Some(p)
    } else {
        None
    };

    if let Some(models_dir) = locate_bundled_models(app) {
        eprintln!("[locallexis] bundled models: {}", models_dir.display());
        env.insert(
            "LOCALLEXIS_BUNDLED_MODELS".to_string(),
            models_dir.to_string_lossy().to_string(),
        );
    } else {
        eprintln!("[locallexis] bundled models: not found (will download on demand)");
    }

    // GUI-launched macOS apps get a stripped PATH that excludes Homebrew.
    // ffmpeg (required for audio ingest) is usually only on the Homebrew or
    // MacPorts paths. Prepend the common locations so the sidecar's
    // subprocess.run('ffmpeg', ...) can find it.
    let extra_paths = ["/opt/homebrew/bin", "/usr/local/bin", "/opt/local/bin"];
    let current_path = std::env::var("PATH").unwrap_or_default();
    let mut merged_parts: Vec<&str> = extra_paths.to_vec();
    for p in current_path.split(':') {
        if !p.is_empty() && !merged_parts.contains(&p) {
            merged_parts.push(p);
        }
    }
    env.insert("PATH".to_string(), merged_parts.join(":"));

    let sidecar = app
        .shell()
        .sidecar("locallexis-sidecar")
        .map_err(|e| e.to_string())?
        .envs(env);

    let (mut rx, child) = sidecar.spawn().map_err(|e| e.to_string())?;
    let child_state: State<SidecarChild> = app.state();
    *child_state.0.lock().unwrap() = Some(child);

    if let Some(loopback) = loopback_port {
        // Headless sidecar emits no stdout handshake; set the URL
        // directly so the frontend can dial it without waiting. We
        // use the loopback HTTP port (not the LAN HTTPS port) because
        // WebKit / WebView2 reject the self-signed cert on the LAN
        // socket — phones still pin the cert via the pairing QR.
        let url_state: State<SidecarUrl> = app.state();
        *url_state.0.lock().unwrap() =
            Some(format!("http://127.0.0.1:{}", loopback));
    }

    let app_for_task = app.clone();
    tauri::async_runtime::spawn(async move {
        while let Some(event) = rx.recv().await {
            if let CommandEvent::Stdout(line) = event {
                let text = String::from_utf8_lossy(&line);
                if let Ok(parsed) = serde_json::from_str::<serde_json::Value>(&text) {
                    if let Some(p) = parsed
                        .get("locallexis")
                        .and_then(|v| v.get("port"))
                        .and_then(|v| v.as_u64())
                    {
                        // Only the non-headless sidecar emits the
                        // handshake; in headless mode this branch is
                        // never hit, and we've already set the URL
                        // above from the configured port.
                        let state: State<SidecarUrl> = app_for_task.state();
                        *state.0.lock().unwrap() =
                            Some(format!("http://127.0.0.1:{}", p));
                    }
                }
            }
        }
    });

    Ok(())
}

/// Stop the running sidecar and start a fresh one with the current
/// hub state. Invoked by `set_hub_state` so the toggle takes effect
/// immediately.
pub fn restart(app: &AppHandle) -> Result<(), String> {
    {
        let child_state: State<SidecarChild> = app.state();
        if let Some(child) = child_state.0.lock().unwrap().take() {
            let _ = child.kill();
        }
        // Blank the URL so the frontend can show a transient
        // "reconnecting" state rather than dial the old socket.
        let url_state: State<SidecarUrl> = app.state();
        *url_state.0.lock().unwrap() = None;
    }
    spawn(app)
}
