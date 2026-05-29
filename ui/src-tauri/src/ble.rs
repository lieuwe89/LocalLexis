use std::sync::OnceLock;
use std::time::Duration;

use btleplug::api::{
    Central, Characteristic, Manager as _, Peripheral as _, ScanFilter, WriteType,
};
use btleplug::platform::{Adapter, Manager, Peripheral};
use serde::{Deserialize, Serialize};
use tokio::sync::Mutex;
use uuid::Uuid;

const SCAN_SECONDS: u64 = 4;
const RESOLVE_POLL_MS: u64 = 250;
const RECORDER_NAME_PREFIX: &str = "LocalLexis Recorder";
const PROVISION_FRAME_BYTES: usize = 20;
const PROVISION_FRAME_DATA_BYTES: usize = 14;
const PROVISION_FRAME_VERSION: u8 = 1;
const PROTOCOL: &str = "locallexis.recorder.provision.v1";
static SCAN_LOCK: OnceLock<Mutex<()>> = OnceLock::new();

fn recorder_service_uuid() -> Uuid {
    Uuid::from_u128(0x8f0d_1b0a_1e5c_4d0c_9ad0_f0c4_f5e9_d001)
}

fn hello_char_uuid() -> Uuid {
    Uuid::from_u128(0x8f0d_1b0a_1e5c_4d0c_9ad0_f0c4_f5e9_d002)
}

fn provision_rx_char_uuid() -> Uuid {
    Uuid::from_u128(0x8f0d_1b0a_1e5c_4d0c_9ad0_f0c4_f5e9_d003)
}

fn scan_lock() -> &'static Mutex<()> {
    SCAN_LOCK.get_or_init(|| Mutex::new(()))
}

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
pub struct RecorderBleDevice {
    pub id: String,
    pub name: Option<String>,
    pub rssi: Option<i16>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct RecorderHello {
    pub protocol: String,
    pub device_pubkey_b64: String,
    pub device_name: Option<String>,
    pub firmware: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct RecorderProvisioning {
    pub protocol: String,
    pub hub_url: String,
    pub workspace_id: String,
    pub device_id: String,
    pub workspace_key_sealed_b64: String,
    pub lamport_observed: u64,
    pub tls_spki_b64: Option<String>,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
struct RecorderResolveHint {
    name: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct RecorderCandidate {
    name: Option<String>,
}

fn is_locallexis_recorder(
    name: Option<&str>,
    services: &[Uuid],
) -> bool {
    services.iter().any(|uuid| *uuid == recorder_service_uuid())
        || name
            .map(|n| n.starts_with(RECORDER_NAME_PREFIX))
            .unwrap_or(false)
}

fn provision_frames(payload: &[u8]) -> Result<Vec<Vec<u8>>, String> {
    if payload.is_empty() {
        return Err("provisioning payload cannot be empty".to_string());
    }
    let total = payload.len().div_ceil(PROVISION_FRAME_DATA_BYTES);
    if total > u16::MAX as usize {
        return Err("provisioning payload is too large".to_string());
    }

    Ok(payload
        .chunks(PROVISION_FRAME_DATA_BYTES)
        .enumerate()
        .map(|(seq, chunk)| {
            debug_assert!(6 + chunk.len() <= PROVISION_FRAME_BYTES);
            let mut frame = vec![0_u8; 6 + chunk.len()];
            frame[0] = PROVISION_FRAME_VERSION;
            frame[1..3].copy_from_slice(&(seq as u16).to_be_bytes());
            frame[3..5].copy_from_slice(&(total as u16).to_be_bytes());
            frame[5] = chunk.len() as u8;
            frame[6..].copy_from_slice(chunk);
            frame
        })
        .collect())
}

async fn first_adapter() -> Result<Adapter, String> {
    let manager = Manager::new().await.map_err(|e| e.to_string())?;
    let adapters = manager.adapters().await.map_err(|e| e.to_string())?;
    adapters
        .into_iter()
        .next()
        .ok_or_else(|| "no Bluetooth adapter found".to_string())
}

trait PeripheralDiscovery {
    type Peripheral: Clone;

    async fn discovered_peripherals(&self) -> Result<Vec<Self::Peripheral>, String>;
    async fn start_discovery_scan(&self) -> Result<(), String>;
    async fn stop_discovery_scan(&self) -> Result<(), String>;
    fn peripheral_id(peripheral: &Self::Peripheral) -> String;
    async fn recorder_candidate(
        &self,
        peripheral: &Self::Peripheral,
    ) -> Result<Option<RecorderCandidate>, String>;
}

impl PeripheralDiscovery for Adapter {
    type Peripheral = Peripheral;

    async fn discovered_peripherals(&self) -> Result<Vec<Self::Peripheral>, String> {
        Central::peripherals(self).await.map_err(|e| e.to_string())
    }

    async fn start_discovery_scan(&self) -> Result<(), String> {
        Central::start_scan(self, ScanFilter { services: vec![] })
            .await
            .map_err(|e| e.to_string())
    }

    async fn stop_discovery_scan(&self) -> Result<(), String> {
        Central::stop_scan(self).await.map_err(|e| e.to_string())
    }

    fn peripheral_id(peripheral: &Self::Peripheral) -> String {
        peripheral.id().to_string()
    }

    async fn recorder_candidate(
        &self,
        peripheral: &Self::Peripheral,
    ) -> Result<Option<RecorderCandidate>, String> {
        let Some(properties) = peripheral.properties().await.map_err(|e| e.to_string())? else {
            return Ok(None);
        };
        if !is_locallexis_recorder(properties.local_name.as_deref(), &properties.services) {
            return Ok(None);
        }
        Ok(Some(RecorderCandidate {
            name: properties.local_name,
        }))
    }
}

async fn find_cached_peripheral<D>(
    discovery: &D,
    peripheral_id: &str,
) -> Result<Option<D::Peripheral>, String>
where
    D: PeripheralDiscovery,
{
    Ok(discovery
        .discovered_peripherals()
        .await?
        .into_iter()
        .find(|peripheral| D::peripheral_id(peripheral) == peripheral_id))
}

fn candidate_matches_hint(candidate: &RecorderCandidate, hint: &RecorderResolveHint) -> bool {
    // RSSI deliberately ignored: real-world BLE swings ±30+ dBm and
    // earlier ±25 tolerance produced spurious "recorder not found".
    // Name + single-candidate uniqueness (enforced by caller) is enough.
    match (&hint.name, &candidate.name) {
        (Some(expected), Some(actual)) => expected == actual,
        _ => false,
    }
}

async fn find_single_recorder_candidate<D>(
    discovery: &D,
    hint: &RecorderResolveHint,
) -> Result<Option<D::Peripheral>, String>
where
    D: PeripheralDiscovery,
{
    let mut candidates = Vec::new();
    for peripheral in discovery.discovered_peripherals().await? {
        if let Ok(Some(candidate)) = discovery.recorder_candidate(&peripheral).await {
            if candidate_matches_hint(&candidate, hint) {
                candidates.push(peripheral);
            }
        }
    }

    match candidates.len() {
        0 => Ok(None),
        1 => Ok(candidates.pop()),
        count => Err(format!(
            "multiple matching LocalLexis recorders visible ({count}); scan again and choose one"
        )),
    }
}

async fn find_peripheral_with_rescan<D>(
    discovery: &D,
    peripheral_id: &str,
    hint: &RecorderResolveHint,
    scan_duration: Duration,
    poll_interval: Duration,
) -> Result<D::Peripheral, String>
where
    D: PeripheralDiscovery,
{
    if let Some(peripheral) = find_cached_peripheral(discovery, peripheral_id).await? {
        return Ok(peripheral);
    }

    discovery.start_discovery_scan().await?;
    let deadline = tokio::time::Instant::now() + scan_duration;
    let peripheral: Result<Option<D::Peripheral>, String> = async {
        loop {
            if let Some(peripheral) = find_cached_peripheral(discovery, peripheral_id).await? {
                return Ok(Some(peripheral));
            }
            let now = tokio::time::Instant::now();
            if now >= deadline {
                return Ok(None);
            }
            tokio::time::sleep(poll_interval.min(deadline - now)).await;
        }
    }
    .await;
    let _ = discovery.stop_discovery_scan().await;

    if let Some(peripheral) = peripheral? {
        return Ok(peripheral);
    }
    if let Some(peripheral) = find_single_recorder_candidate(discovery, hint).await? {
        return Ok(peripheral);
    }

    Err(format!("recorder not found: {peripheral_id}"))
}

async fn scan_recorders_for(
    duration: Duration,
) -> Result<Vec<RecorderBleDevice>, String> {
    let _guard = scan_lock().lock().await;
    let adapter = first_adapter().await?;
    adapter
        .start_scan(ScanFilter { services: vec![] })
        .await
        .map_err(|e| e.to_string())?;
    tokio::time::sleep(duration).await;

    let peripherals = adapter.peripherals().await.map_err(|e| e.to_string())?;
    let _ = adapter.stop_scan().await;
    let mut devices = Vec::new();
    for peripheral in peripherals {
        let properties = peripheral.properties().await.map_err(|e| e.to_string())?;
        let Some(properties) = properties else {
            continue;
        };
        if !is_locallexis_recorder(
            properties.local_name.as_deref(),
            &properties.services,
        ) {
            continue;
        }
        devices.push(RecorderBleDevice {
            id: peripheral.id().to_string(),
            name: properties.local_name,
            rssi: properties.rssi,
        });
    }
    Ok(devices)
}

async fn find_peripheral(
    adapter: &Adapter,
    peripheral_id: &str,
    hint: &RecorderResolveHint,
) -> Result<Peripheral, String> {
    let _guard = scan_lock().lock().await;
    find_peripheral_with_rescan(
        adapter,
        peripheral_id,
        hint,
        Duration::from_secs(SCAN_SECONDS),
        Duration::from_millis(RESOLVE_POLL_MS),
    )
    .await
}

async fn connect_and_discover(
    peripheral_id: &str,
    hint: &RecorderResolveHint,
) -> Result<Peripheral, String> {
    let adapter = first_adapter().await?;
    let peripheral = find_peripheral(&adapter, peripheral_id, hint).await?;
    if !peripheral.is_connected().await.map_err(|e| e.to_string())? {
        peripheral.connect().await.map_err(|e| e.to_string())?;
    }
    peripheral.discover_services().await.map_err(|e| e.to_string())?;
    Ok(peripheral)
}

async fn disconnect_quietly(peripheral: &Peripheral) {
    if matches!(peripheral.is_connected().await, Ok(true)) {
        let _ = peripheral.disconnect().await;
    }
}

fn find_characteristic(
    peripheral: &Peripheral,
    uuid: Uuid,
) -> Result<Characteristic, String> {
    peripheral
        .characteristics()
        .into_iter()
        .find(|c| c.uuid == uuid)
        .ok_or_else(|| format!("recorder characteristic not found: {uuid}"))
}

#[tauri::command]
pub async fn ble_scan_recorders() -> Result<Vec<RecorderBleDevice>, String> {
    scan_recorders_for(Duration::from_secs(SCAN_SECONDS)).await
}

#[tauri::command]
pub async fn ble_read_recorder_hello(
    peripheral_id: String,
    expected_name: Option<String>,
) -> Result<RecorderHello, String> {
    let hint = RecorderResolveHint { name: expected_name };
    let peripheral = connect_and_discover(&peripheral_id, &hint).await?;
    let result = async {
        let hello_char = find_characteristic(&peripheral, hello_char_uuid())?;
        let bytes = peripheral
            .read(&hello_char)
            .await
            .map_err(|e| e.to_string())?;
        let hello: RecorderHello =
            serde_json::from_slice(&bytes).map_err(|e| e.to_string())?;
        if hello.protocol != PROTOCOL {
            return Err(format!("unsupported recorder protocol: {}", hello.protocol));
        }
        Ok(hello)
    }
    .await;
    disconnect_quietly(&peripheral).await;
    result
}

#[tauri::command]
pub async fn ble_send_recorder_provisioning(
    peripheral_id: String,
    expected_name: Option<String>,
    provisioning: RecorderProvisioning,
) -> Result<(), String> {
    if provisioning.protocol != PROTOCOL {
        return Err(format!(
            "unsupported recorder protocol: {}",
            provisioning.protocol
        ));
    }
    let hint = RecorderResolveHint { name: expected_name };
    let peripheral = connect_and_discover(&peripheral_id, &hint).await?;
    let result = async {
        let rx_char = find_characteristic(&peripheral, provision_rx_char_uuid())?;
        let payload = serde_json::to_vec(&provisioning).map_err(|e| e.to_string())?;
        for frame in provision_frames(&payload)? {
            peripheral
                .write(&rx_char, &frame, WriteType::WithResponse)
                .await
                .map_err(|e| e.to_string())?;
        }
        Ok(())
    }
    .await;
    disconnect_quietly(&peripheral).await;
    result
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::Mutex as StdMutex;

    #[derive(Clone, Debug, PartialEq, Eq)]
    struct FakePeripheral {
        id: String,
        candidate: Option<RecorderCandidate>,
    }

    #[derive(Debug)]
    struct FakeDiscovery {
        before_scan: Vec<FakePeripheral>,
        after_scan: Vec<FakePeripheral>,
        scan_starts: StdMutex<usize>,
        scan_stops: StdMutex<usize>,
    }

    impl FakeDiscovery {
        fn new(before_scan: Vec<FakePeripheral>, after_scan: Vec<FakePeripheral>) -> Self {
            Self {
                before_scan,
                after_scan,
                scan_starts: StdMutex::new(0),
                scan_stops: StdMutex::new(0),
            }
        }

        fn scan_starts(&self) -> usize {
            *self.scan_starts.lock().unwrap()
        }

        fn scan_stops(&self) -> usize {
            *self.scan_stops.lock().unwrap()
        }
    }

    impl PeripheralDiscovery for FakeDiscovery {
        type Peripheral = FakePeripheral;

        async fn discovered_peripherals(&self) -> Result<Vec<Self::Peripheral>, String> {
            if self.scan_starts() > 0 {
                Ok(self.after_scan.clone())
            } else {
                Ok(self.before_scan.clone())
            }
        }

        async fn start_discovery_scan(&self) -> Result<(), String> {
            *self.scan_starts.lock().unwrap() += 1;
            Ok(())
        }

        async fn stop_discovery_scan(&self) -> Result<(), String> {
            *self.scan_stops.lock().unwrap() += 1;
            Ok(())
        }

        fn peripheral_id(peripheral: &Self::Peripheral) -> String {
            peripheral.id.clone()
        }

        async fn recorder_candidate(
            &self,
            peripheral: &Self::Peripheral,
        ) -> Result<Option<RecorderCandidate>, String> {
            Ok(peripheral.candidate.clone())
        }
    }

    #[test]
    fn recognises_name_or_service_uuid() {
        assert!(is_locallexis_recorder(
            Some("LocalLexis Recorder A"),
            &[]
        ));
        assert!(is_locallexis_recorder(None, &[recorder_service_uuid()]));
        assert!(!is_locallexis_recorder(Some("Other Device"), &[]));
    }

    #[test]
    fn frames_payload_for_default_ble_writes() {
        let payload = vec![b'a'; 205];
        let frames = provision_frames(&payload).unwrap();

        assert_eq!(frames.len(), 15);
        assert!(frames.iter().all(|frame| frame.len() <= PROVISION_FRAME_BYTES));
        assert_eq!(frames[0][0], PROVISION_FRAME_VERSION);
        assert_eq!(u16::from_be_bytes([frames[0][1], frames[0][2]]), 0);
        assert_eq!(u16::from_be_bytes([frames[0][3], frames[0][4]]), 15);
        assert_eq!(u16::from_be_bytes([frames[14][1], frames[14][2]]), 14);
        assert_eq!(u16::from_be_bytes([frames[14][3], frames[14][4]]), 15);
        let reassembled: Vec<u8> = frames
            .iter()
            .flat_map(|frame| {
                let len = frame[5] as usize;
                frame[6..6 + len].to_vec()
            })
            .collect();
        assert_eq!(reassembled, payload);
    }

    #[test]
    fn rejects_empty_provision_payload() {
        assert_eq!(
            provision_frames(&[]).unwrap_err(),
            "provisioning payload cannot be empty"
        );
    }

    #[test]
    fn rescans_when_requested_peripheral_is_not_cached() {
        let discovery = FakeDiscovery::new(
            vec![],
            vec![FakePeripheral {
                id: "recorder-1".to_string(),
                candidate: Some(RecorderCandidate {
                    name: Some("LocalLexis Recorder".to_string()),
                }),
            }],
        );

        let found = tauri::async_runtime::block_on(find_peripheral_with_rescan(
            &discovery,
            "recorder-1",
            &RecorderResolveHint::default(),
            Duration::ZERO,
            Duration::ZERO,
        ))
        .unwrap();

        assert_eq!(found.id, "recorder-1");
        assert_eq!(discovery.scan_starts(), 1);
        assert_eq!(discovery.scan_stops(), 1);
    }

    #[test]
    fn uses_cached_peripheral_without_rescanning() {
        let discovery = FakeDiscovery::new(
            vec![FakePeripheral {
                id: "recorder-1".to_string(),
                candidate: None,
            }],
            vec![],
        );

        let found = tauri::async_runtime::block_on(find_peripheral_with_rescan(
            &discovery,
            "recorder-1",
            &RecorderResolveHint::default(),
            Duration::ZERO,
            Duration::ZERO,
        ))
        .unwrap();

        assert_eq!(found.id, "recorder-1");
        assert_eq!(discovery.scan_starts(), 0);
        assert_eq!(discovery.scan_stops(), 0);
    }

    #[test]
    fn falls_back_to_single_visible_recorder_when_id_changes_after_scan() {
        let discovery = FakeDiscovery::new(
            vec![],
            vec![FakePeripheral {
                id: "recorder-2".to_string(),
                candidate: Some(RecorderCandidate {
                    name: Some("LocalLexis Recorder".to_string()),
                }),
            }],
        );

        let found = tauri::async_runtime::block_on(find_peripheral_with_rescan(
            &discovery,
            "recorder-1",
            &RecorderResolveHint {
                name: Some("LocalLexis Recorder".to_string()),
            },
            Duration::ZERO,
            Duration::ZERO,
        ))
        .unwrap();

        assert_eq!(found.id, "recorder-2");
        assert_eq!(discovery.scan_starts(), 1);
        assert_eq!(discovery.scan_stops(), 1);
    }

    #[test]
    fn name_only_fallback_ignores_rssi_drift() {
        let candidate = RecorderCandidate {
            name: Some("LocalLexis Recorder".to_string()),
        };
        let hint = RecorderResolveHint {
            name: Some("LocalLexis Recorder".to_string()),
        };

        assert!(candidate_matches_hint(&candidate, &hint));
    }

    #[test]
    fn fallback_rejects_mismatched_name() {
        let candidate = RecorderCandidate {
            name: Some("Other Recorder".to_string()),
        };
        let hint = RecorderResolveHint {
            name: Some("LocalLexis Recorder".to_string()),
        };

        assert!(!candidate_matches_hint(&candidate, &hint));
    }

    #[test]
    fn does_not_fallback_without_selected_recorder_hint() {
        let discovery = FakeDiscovery::new(
            vec![],
            vec![FakePeripheral {
                id: "recorder-2".to_string(),
                candidate: Some(RecorderCandidate {
                    name: Some("LocalLexis Recorder".to_string()),
                }),
            }],
        );

        let err = tauri::async_runtime::block_on(find_peripheral_with_rescan(
            &discovery,
            "recorder-1",
            &RecorderResolveHint::default(),
            Duration::ZERO,
            Duration::ZERO,
        ))
        .unwrap_err();

        assert_eq!(err, "recorder not found: recorder-1");
        assert_eq!(discovery.scan_starts(), 1);
        assert_eq!(discovery.scan_stops(), 1);
    }

    #[test]
    fn does_not_guess_when_multiple_recorders_are_visible_after_scan() {
        let discovery = FakeDiscovery::new(
            vec![],
            vec![
                FakePeripheral {
                    id: "recorder-2".to_string(),
                    candidate: Some(RecorderCandidate {
                        name: Some("LocalLexis Recorder".to_string()),
                    }),
                },
                FakePeripheral {
                    id: "recorder-3".to_string(),
                    candidate: Some(RecorderCandidate {
                        name: Some("LocalLexis Recorder".to_string()),
                    }),
                },
            ],
        );

        let err = tauri::async_runtime::block_on(find_peripheral_with_rescan(
            &discovery,
            "recorder-1",
            &RecorderResolveHint {
                name: Some("LocalLexis Recorder".to_string()),
            },
            Duration::ZERO,
            Duration::ZERO,
        ))
        .unwrap_err();

        assert_eq!(
            err,
            "multiple matching LocalLexis recorders visible (2); scan again and choose one"
        );
        assert_eq!(discovery.scan_starts(), 1);
        assert_eq!(discovery.scan_stops(), 1);
    }
}
