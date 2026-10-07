#[test]
fn production_launcher_supervises_real_fastapi_g5_stop_eof_crash_and_restart() {
    desktop_lib::runtime_manager::run_production_supervisor_integration()
        .unwrap_or_else(|reason| panic!("production supervisor integration failed: {reason}"));
}
