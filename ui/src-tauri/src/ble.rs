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
) -> Result<Peripheral, String> {
    for peripheral in adapter.peripherals().await.map_err(|e| e.to_string())? {
        if peripheral.id().to_string() == peripheral_id {
            return Ok(peripheral);
        }
    }
    Err(format!("recorder not found: {peripheral_id}"))
}

async fn connect_and_discover(
    peripheral_id: &str,
) -> Result<Peripheral, String> {
    let adapter = first_adapter().await?;
    let peripheral = find_peripheral(&adapter, peripheral_id).await?;
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
) -> Result<RecorderHello, String> {
    let peripheral = connect_and_discover(&peripheral_id).await?;
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
    provisioning: RecorderProvisioning,
) -> Result<(), String> {
    if provisioning.protocol != PROTOCOL {
        return Err(format!(
            "unsupported recorder protocol: {}",
            provisioning.protocol
        ));
    }
    let peripheral = connect_and_discover(&peripheral_id).await?;
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
}
