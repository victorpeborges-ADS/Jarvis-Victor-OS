use super::*;
use std::time::{Duration, Instant};

fn expect_pre_ready_exit(mode: HelperMode, code: i32) {
    let manager = manager();
    let started = manager.start_mode_for_test(mode).unwrap();
    let failed = manager.wait_for_state(RuntimeState::Failed, Duration::from_secs(2));
    assert_eq!(failed.runtime_instance_id, started.runtime_instance_id);
    assert_eq!(failed.failure_category, Some("child_exit_before_ready"));
    assert_eq!(failed.exit_code, Some(code));
    assert_clean(&manager);
}

#[test]
fn nonzero_exit_before_ready_is_canonical() {
    expect_pre_ready_exit(HelperMode::CrashBeforeReady, 41);
}

#[test]
fn zero_exit_before_ready_is_canonical() {
    expect_pre_ready_exit(HelperMode::ExitZeroBeforeReady, 0);
}

#[test]
fn stdout_closes_then_process_exits_before_ready() {
    expect_pre_ready_exit(HelperMode::CloseStdoutThenExit, 47);
}

#[test]
fn stdout_closes_while_process_lives_is_distinct() {
    let manager = manager();
    manager
        .start_mode_for_test(HelperMode::CloseStdoutBeforeReady)
        .unwrap();
    let failed = manager.wait_for_state(RuntimeState::Failed, Duration::from_secs(2));
    assert_eq!(failed.failure_category, Some("readiness_channel_closed"));
    assert_clean(&manager);
}

#[test]
fn stop_during_pre_ready_eof_aggregation_is_reaped() {
    let manager = manager();
    let started = manager
        .start_mode_for_test(HelperMode::CloseStdoutBeforeReady)
        .unwrap();
    assert_eq!(
        manager.stop_and_wait().unwrap().state,
        RuntimeState::Stopped
    );
    assert_eq!(
        manager.snapshot().runtime_instance_id,
        started.runtime_instance_id
    );
    assert_clean(&manager);
}

#[test]
fn ready_then_immediate_exit_remains_a_post_ready_crash() {
    let manager = manager();
    manager
        .start_mode_for_test(HelperMode::CrashAfterReady)
        .unwrap();
    let crashed = manager.wait_for_state(RuntimeState::Crashed, Duration::from_secs(2));
    assert_eq!(crashed.failure_category, Some("child_crash"));
    assert_clean(&manager);
}

#[test]
#[ignore = "classification stress; run explicitly for MAC-001.2"]
fn pre_ready_exit_classification_1000_rounds() {
    let started = Instant::now();
    for round in 0..1000 {
        let mode = if round % 2 == 0 {
            HelperMode::CrashBeforeReady
        } else {
            HelperMode::CloseStdoutThenExit
        };
        let code = if round % 2 == 0 { 41 } else { 47 };
        expect_pre_ready_exit(mode, code);
    }
    eprintln!(
        "PASS pre-ready classification rounds=1000 duration_ms={}",
        started.elapsed().as_millis()
    );
}
