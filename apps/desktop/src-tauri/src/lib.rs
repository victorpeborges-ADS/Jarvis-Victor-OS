use tauri::Manager;

pub mod runtime_manager;
pub mod transport;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let app = tauri::Builder::default()
        .manage(runtime_manager::RuntimeManager::new())
        .invoke_handler(tauri::generate_handler![
            runtime_manager::runtime_status,
            runtime_manager::runtime_transport_status,
            runtime_manager::runtime_transport_probe,
            runtime_manager::g5_session_status,
            runtime_manager::g5_session_open,
            runtime_manager::g5_mission_read_grant_create,
            runtime_manager::g5_mission_read_grant_revoke,
            runtime_manager::g5_session_close,
            runtime_manager::g5_missions_list,
            runtime_manager::runtime_start,
            runtime_manager::runtime_stop,
            runtime_manager::runtime_restart,
        ])
        .build(tauri::generate_context!())
        .expect("error while building tauri application");

    app.run(|app_handle, event| {
        if matches!(event, tauri::RunEvent::Exit) {
            let _ = app_handle
                .state::<runtime_manager::RuntimeManager>()
                .stop_and_wait();
        }
    });
}
