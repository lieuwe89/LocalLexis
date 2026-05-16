//! Smoke test: the sidecar binary starts, reports a port via JSON handshake,
//! responds to /health, and exits cleanly on kill.
//!
//! Run with:
//!     cargo test --manifest-path ui/src-tauri/Cargo.toml --release -- --test-threads=1
//!
//! Requires the binary at:
//!     ui/src-tauri/binaries/localscribe-sidecar-<host-triple>

use std::io::{BufRead, BufReader};
use std::process::{Command, Stdio};
use std::time::{Duration, Instant};

fn target_triple() -> &'static str {
    if cfg!(target_arch = "aarch64") && cfg!(target_os = "macos") { "aarch64-apple-darwin" }
    else if cfg!(target_arch = "x86_64") && cfg!(target_os = "macos") { "x86_64-apple-darwin" }
    else if cfg!(target_os = "linux") && cfg!(target_arch = "x86_64") { "x86_64-unknown-linux-gnu" }
    else if cfg!(target_os = "windows") { "x86_64-pc-windows-msvc" }
    else { panic!("unsupported host") }
}

fn binary_path() -> std::path::PathBuf {
    let triple = target_triple();
    let name = if cfg!(windows) {
        format!("localscribe-sidecar-{}.exe", triple)
    } else {
        format!("localscribe-sidecar-{}", triple)
    };
    let here = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    here.join("binaries").join(name)
}

#[test]
fn sidecar_starts_responds_to_health_then_exits() {
    let binary = binary_path();
    assert!(
        binary.exists(),
        "sidecar binary missing at {} — build it with `pyinstaller packaging/localscribe-sidecar.spec --clean` then copy into ui/src-tauri/binaries/",
        binary.display()
    );

    let mut child = Command::new(&binary)
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()
        .expect("failed to spawn sidecar");

    let stdout = child.stdout.take().expect("captured stdout");
    let reader = BufReader::new(stdout);

    // 120s timeout: pyannote model initialisation is slow (up to ~90s on first run
    // with the PyInstaller binary on Apple Silicon).
    let timeout = Duration::from_secs(120);
    let start = Instant::now();
    let mut url: Option<String> = None;
    for line in reader.lines() {
        if start.elapsed() > timeout {
            let _ = child.kill();
            panic!("sidecar didn't emit JSON handshake within {}s", timeout.as_secs());
        }
        let Ok(line) = line else { continue };
        if let Ok(parsed) = serde_json::from_str::<serde_json::Value>(&line) {
            if let Some(port) = parsed.get("localscribe").and_then(|v| v.get("port")).and_then(|v| v.as_u64()) {
                url = Some(format!("http://127.0.0.1:{}", port));
                break;
            }
        }
    }
    let url = url.expect("no handshake line on stdout");

    // Hit /health — retry briefly since the server may not be accepting connections
    // the instant it emits the handshake line.
    let health_url = format!("{}/health", url);
    let mut body_ok = false;
    let health_deadline = Instant::now() + Duration::from_secs(10);
    loop {
        let resp = ureq::get(&health_url)
            .timeout(Duration::from_secs(5))
            .call();
        match resp {
            Ok(r) => {
                let text = r.into_string().unwrap_or_default();
                body_ok = text.contains("\"ok\"") && text.contains("true");
                break;
            }
            Err(ureq::Error::Transport(ref t))
                if t.kind() == ureq::ErrorKind::ConnectionFailed =>
            {
                if Instant::now() >= health_deadline {
                    let _ = child.kill();
                    panic!("GET /health still connection-refused after 10s");
                }
                std::thread::sleep(Duration::from_millis(250));
            }
            Err(e) => {
                let _ = child.kill();
                panic!("GET /health failed: {}", e);
            }
        }
    }

    let _ = child.kill();
    let _ = child.wait();
    assert!(body_ok, "GET /health did not return ok:true");
}
