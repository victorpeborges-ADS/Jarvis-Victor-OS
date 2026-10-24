use tauri::Manager;

pub mod runtime_manager;
pub mod storage_keychain;
pub mod transport;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .manage(runtime_manager::RuntimeManager::new())
        .invoke_handler(tauri::generate_handler![
            runtime_manager::runtime_status,
            runtime_manager::runtime_transport_status,
            runtime_manager::runtime_transport_probe,
            runtime_manager::runtime_storage_unlock,
            runtime_manager::runtime_storage_rotate,
            runtime_manager::runtime_storage_rotate_begin,
            runtime_manager::runtime_storage_lock,
            runtime_manager::g5_session_status,
            runtime_manager::g5_session_open,
            runtime_manager::g5_mission_read_grant_create,
            runtime_manager::g5_mission_read_grant_revoke,
            runtime_manager::g5_session_close,
            runtime_manager::g5_missions_list,
            runtime_manager::g5_capture_create,
            runtime_manager::g5_capture_list,
            runtime_manager::g5_capture_search,
            runtime_manager::g5_capture_open,
            runtime_manager::g5_conversation_ask,
            runtime_manager::g5_conversation_open,
            runtime_manager::g5_conversation_cancel,
            runtime_manager::g5_synthetic_document_generate,
            runtime_manager::g5_capture_clear,
            runtime_manager::g5_capture_edit,
            runtime_manager::g5_capture_delete,
            runtime_manager::g5_memory_page,
            runtime_manager::g5_memory_create,
            runtime_manager::g5_memory_edit,
            runtime_manager::g5_memory_delete,
            runtime_manager::g5_memory_export,
            runtime_manager::g5_connectors_status,
            runtime_manager::g5_review_grant_create,
            runtime_manager::g5_review_grant_revoke,
            runtime_manager::g5_reviews_pending,
            runtime_manager::g5_review_draft,
            runtime_manager::g5_review_detail,
            runtime_manager::g5_review_approve,
            runtime_manager::g5_workflow_submit_draft,
            runtime_manager::g5_workflow_submit_simulation,
            runtime_manager::g5_workflow_list,
            runtime_manager::g5_workflow_page,
            runtime_manager::g5_workflow_detail,
            runtime_manager::g5_workflow_execute_draft,
            runtime_manager::g5_workflow_execute_simulation,
            runtime_manager::g5_workflow_pause,
            runtime_manager::g5_workflow_resume,
            runtime_manager::g5_workflow_cancel,
            runtime_manager::g5_automations_list,
            runtime_manager::g5_automation_detail,
            runtime_manager::g5_automation_history,
            runtime_manager::g5_automation_run,
            runtime_manager::g5_automation_create,
            runtime_manager::g5_automation_timezone,
            runtime_manager::g5_automation_control,
            runtime_manager::runtime_local_config,
            runtime_manager::runtime_start,
            runtime_manager::runtime_stop,
            runtime_manager::runtime_restart,
        ])
        .build(tauri::generate_context!())
        .expect("error while building tauri application");

    app.run(|app_handle, event| {
        if matches!(event, tauri::RunEvent::Ready) {
            let _ = app_handle
                .state::<runtime_manager::RuntimeManager>()
                .start_on_launch();
        }
        if matches!(event, tauri::RunEvent::Exit) {
            let _ = app_handle
                .state::<runtime_manager::RuntimeManager>()
                .stop_and_wait();
        }
    });
}
