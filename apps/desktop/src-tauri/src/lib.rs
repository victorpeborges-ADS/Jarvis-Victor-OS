use tauri::Manager;

pub mod runtime_manager;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let app = tauri::Builder::default()
        .manage(runtime_manager::RuntimeManager::new())
        .invoke_handler(tauri::generate_handler![
            runtime_manager::runtime_status,
            runtime_manager::runtime_start_test,
            runtime_manager::runtime_stop,
            runtime_manager::runtime_restart_test,
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
