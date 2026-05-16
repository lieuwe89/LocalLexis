use std::sync::Mutex;
use tauri::{AppHandle, Manager, State};
use tauri_plugin_shell::ShellExt;
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use std::collections::HashMap;

#[derive(Default)]
pub struct SidecarUrl(pub Mutex<Option<String>>);

pub struct SidecarChild(pub Mutex<Option<CommandChild>>);

impl Default for SidecarChild {
    fn default() -> Self {
        Self(Mutex::new(None))
    }
}

#[tauri::command]
pub fn sidecar_url(state: State<SidecarUrl>) -> Option<String> {
    state.0.lock().unwrap().clone()
}

pub fn spawn(app: &AppHandle) -> Result<(), String> {
    let mut env: HashMap<String, String> = HashMap::new();
    if let Ok(resource_dir) = app.path().resource_dir() {
        let models_dir = resource_dir.join("resources").join("models");
        if models_dir.is_dir() {
            env.insert(
                "LOCALSCRIBE_BUNDLED_MODELS".to_string(),
                models_dir.to_string_lossy().to_string(),
            );
        }
    }

    let sidecar = app
        .shell()
        .sidecar("localscribe-sidecar")
        .map_err(|e| e.to_string())?
        .envs(env);

    let (mut rx, child) = sidecar.spawn().map_err(|e| e.to_string())?;
    let child_state: State<SidecarChild> = app.state();
    *child_state.0.lock().unwrap() = Some(child);

    let app_for_task = app.clone();
    tauri::async_runtime::spawn(async move {
        while let Some(event) = rx.recv().await {
            if let CommandEvent::Stdout(line) = event {
                let text = String::from_utf8_lossy(&line);
                if let Ok(parsed) = serde_json::from_str::<serde_json::Value>(&text) {
                    if let Some(p) = parsed
                        .get("localscribe")
                        .and_then(|v| v.get("port"))
                        .and_then(|v| v.as_u64())
                    {
                        let state: State<SidecarUrl> = app_for_task.state();
                        *state.0.lock().unwrap() = Some(format!("http://127.0.0.1:{}", p));
                    }
                }
            }
        }
    });

    Ok(())
}
