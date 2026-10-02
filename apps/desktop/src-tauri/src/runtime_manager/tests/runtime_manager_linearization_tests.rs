use super::*;
use std::{
    sync::{mpsc, Arc, Barrier},
    thread,
    time::{Duration, Instant},
};

fn install_stop_hook(manager: &RuntimeManager) -> (Arc<Barrier>, Arc<Barrier>) {
    let captured = Arc::new(Barrier::new(2));
    let resume = Arc::new(Barrier::new(2));
    manager.set_stop_wait_test_hook(Some(super::super::StopWaitTestHook {
        captured: Arc::clone(&captured),
        resume: Arc::clone(&resume),
    }));
    (captured, resume)
}

fn release_stop_hook(manager: &RuntimeManager, resume: &Barrier) {
    manager.set_stop_wait_test_hook(None);
    resume.wait();
}

fn race_pair<Left, Right>(
    left: Left,
    right: Right,
) -> (
    Result<RuntimeSnapshot, ManagerError>,
    Result<RuntimeSnapshot, ManagerError>,
)
where
    Left: FnOnce() -> Result<RuntimeSnapshot, ManagerError> + Send + 'static,
    Right: FnOnce() -> Result<RuntimeSnapshot, ManagerError> + Send + 'static,
{
    let barrier = Arc::new(Barrier::new(3));
    let (sender, receiver) = mpsc::channel();
    let left_barrier = Arc::clone(&barrier);
    let left_sender = sender.clone();
    let left_thread = thread::spawn(move || {
        left_barrier.wait();
        left_sender.send((0usize, left())).unwrap();
    });
    let right_barrier = Arc::clone(&barrier);
    let right_thread = thread::spawn(move || {
        right_barrier.wait();
        sender.send((1usize, right())).unwrap();
    });
    barrier.wait();

    let mut results: [Option<Result<RuntimeSnapshot, ManagerError>>; 2] = [None, None];
    for _ in 0..2 {
        let (index, result) = receiver
            .recv_timeout(Duration::from_secs(6))
            .expect("concurrent lifecycle operation completed within timeout");
        assert!(results[index].replace(result).is_none());
    }
    left_thread.join().unwrap();
    right_thread.join().unwrap();
    (results[0].take().unwrap(), results[1].take().unwrap())
}

#[test]
fn stop_and_wait_when_stopped_is_an_immediate_noop() {
    let manager = manager();

    let stopped = manager.stop_and_wait().unwrap();

    assert_eq!(stopped.state, RuntimeState::Stopped);
    assert_eq!(stopped.runtime_instance_id, None);
    assert_clean(&manager);
}

#[test]
fn stopped_stop_does_not_adopt_a_concurrent_future_start() {
    let manager = Arc::new(manager());
    let (captured, resume) = install_stop_hook(&manager);
    let stop_manager = Arc::clone(&manager);
    let stopper = thread::spawn(move || stop_manager.stop_and_wait());

    captured.wait();
    let started = manager.start_test();
    release_stop_hook(&manager, &resume);
    let stopped = stopper.join().unwrap().unwrap();
    let started = started.unwrap();

    assert_eq!(stopped.state, RuntimeState::Stopped);
    assert_eq!(stopped.runtime_instance_id, None);
    assert_eq!(started.state, RuntimeState::Starting);
    assert_eq!(
        manager.snapshot().runtime_instance_id,
        started.runtime_instance_id
    );
    manager.wait_for_state(RuntimeState::Ready, Duration::from_secs(2));
    manager.stop_and_wait().unwrap();
    assert_clean(&manager);
}

#[test]
fn stop_of_ready_generation_does_not_wait_for_or_stop_a_new_generation() {
    let manager = Arc::new(manager());
    let started_a = manager.start_test().unwrap();
    let ready_a = manager.wait_for_state(RuntimeState::Ready, Duration::from_secs(2));
    let instance_a = ready_a.runtime_instance_id.clone().unwrap();
    let (captured, resume) = install_stop_hook(&manager);
    let stop_manager = Arc::clone(&manager);
    let stopper = thread::spawn(move || stop_manager.stop_and_wait());

    captured.wait();
    let stopped_a = manager.wait_for_state(RuntimeState::Stopped, Duration::from_secs(2));
    assert_eq!(
        stopped_a.runtime_instance_id.as_deref(),
        Some(instance_a.as_str())
    );
    let started_b = manager.start_test().unwrap();
    assert_ne!(started_b.runtime_instance_id, started_a.runtime_instance_id);
    let ready_b = manager.wait_for_state(RuntimeState::Ready, Duration::from_secs(2));
    release_stop_hook(&manager, &resume);
    let stop_result = stopper.join().unwrap().unwrap();

    assert_eq!(stop_result.runtime_instance_id, ready_b.runtime_instance_id);
    assert_eq!(stop_result.state, RuntimeState::Ready);
    assert_eq!(
        manager.snapshot().runtime_instance_id,
        ready_b.runtime_instance_id
    );
    assert!(
        manager.has_supervisor(),
        "generation B was reaped by stop(A)"
    );
    manager.stop_and_wait().unwrap();
    assert_clean(&manager);
}

#[test]
fn stop_of_starting_generation_does_not_wait_for_a_new_generation() {
    let manager = Arc::new(manager());
    let started_a = manager.start_mode_for_test(HelperMode::SlowReady).unwrap();
    assert_eq!(started_a.state, RuntimeState::Starting);
    let instance_a = started_a.runtime_instance_id.clone().unwrap();
    let (captured, resume) = install_stop_hook(&manager);
    let stop_manager = Arc::clone(&manager);
    let stopper = thread::spawn(move || stop_manager.stop_and_wait());

    captured.wait();
    let stopped_a = manager.wait_for_state(RuntimeState::Stopped, Duration::from_secs(2));
    assert_eq!(
        stopped_a.runtime_instance_id.as_deref(),
        Some(instance_a.as_str())
    );
    let started_b = manager.start_test().unwrap();
    assert_ne!(started_b.runtime_instance_id, started_a.runtime_instance_id);
    let ready_b = manager.wait_for_state(RuntimeState::Ready, Duration::from_secs(2));
    release_stop_hook(&manager, &resume);
    let stop_result = stopper.join().unwrap().unwrap();

    assert_eq!(stop_result.runtime_instance_id, ready_b.runtime_instance_id);
    assert_eq!(stop_result.state, RuntimeState::Ready);
    assert_eq!(
        manager.snapshot().runtime_instance_id,
        ready_b.runtime_instance_id
    );
    assert!(
        manager.has_supervisor(),
        "generation B was reaped by stop(A)"
    );
    manager.stop_and_wait().unwrap();
    assert_clean(&manager);
}

#[test]
fn concurrent_stop_calls_wait_for_the_same_generation() {
    let manager = Arc::new(manager());
    let started = manager.start_test().unwrap();
    manager.wait_for_state(RuntimeState::Ready, Duration::from_secs(2));
    let left_manager = Arc::clone(&manager);
    let right_manager = Arc::clone(&manager);

    let (left, right) = race_pair(
        move || left_manager.stop_and_wait(),
        move || right_manager.stop_and_wait(),
    );

    assert!(left.is_ok(), "first stop result: {left:?}");
    assert!(right.is_ok(), "second stop result: {right:?}");
    assert_eq!(
        manager.snapshot().runtime_instance_id,
        started.runtime_instance_id
    );
    assert_eq!(manager.snapshot().state, RuntimeState::Stopped);
    assert_clean(&manager);
}

#[test]
fn concurrent_start_calls_create_only_one_child() {
    let manager = Arc::new(manager());
    let left_manager = Arc::clone(&manager);
    let right_manager = Arc::clone(&manager);

    let (left, right) = race_pair(
        move || left_manager.start_test(),
        move || right_manager.start_test(),
    );

    assert_eq!(
        [left.is_ok(), right.is_ok()]
            .into_iter()
            .filter(|ok| *ok)
            .count(),
        1
    );
    assert_eq!(
        [left, right]
            .into_iter()
            .filter(|result| result == &Err(ManagerError::InvalidState))
            .count(),
        1
    );
    let active = manager.wait_for_state(RuntimeState::Ready, Duration::from_secs(2));
    assert!(active.pid.is_some());
    assert!(manager.has_supervisor());
    manager.stop_and_wait().unwrap();
    assert_clean(&manager);
}

#[test]
fn restart_racing_stop_has_explicit_results_and_cleans_its_target() {
    let manager = Arc::new(manager());
    manager
        .start_mode_for_test(HelperMode::CrashAfterReady)
        .unwrap();
    manager.wait_for_state(RuntimeState::Crashed, Duration::from_secs(2));
    let restart_manager = Arc::clone(&manager);
    let stop_manager = Arc::clone(&manager);

    let (restart, stop) = race_pair(
        move || restart_manager.restart_test(),
        move || stop_manager.stop_and_wait(),
    );

    assert!(stop.is_ok(), "stop result: {stop:?}");
    match restart {
        Ok(restarted) => {
            assert_eq!(
                manager.snapshot().runtime_instance_id,
                restarted.runtime_instance_id
            );
            assert_eq!(manager.snapshot().state, RuntimeState::Stopped);
        }
        Err(ManagerError::InvalidState) => {
            assert_eq!(manager.snapshot().state, RuntimeState::Stopped);
        }
        Err(error) => panic!("unexpected restart result: {error:?}"),
    }
    assert_clean(&manager);
}

#[test]
fn concurrent_restarts_allow_exactly_one_new_generation() {
    let manager = Arc::new(manager());
    manager
        .start_mode_for_test(HelperMode::CrashAfterReady)
        .unwrap();
    manager.wait_for_state(RuntimeState::Crashed, Duration::from_secs(2));
    let left_manager = Arc::clone(&manager);
    let right_manager = Arc::clone(&manager);

    let (left, right) = race_pair(
        move || left_manager.restart_test(),
        move || right_manager.restart_test(),
    );

    assert_eq!(
        [left.is_ok(), right.is_ok()]
            .into_iter()
            .filter(|ok| *ok)
            .count(),
        1
    );
    assert_eq!(
        [left, right]
            .into_iter()
            .filter(|result| result == &Err(ManagerError::InvalidState))
            .count(),
        1
    );
    manager.wait_for_state(RuntimeState::Ready, Duration::from_secs(2));
    manager.stop_and_wait().unwrap();
    assert_clean(&manager);
}

#[test]
fn late_events_from_generation_a_cannot_change_generation_b() {
    let manager = manager();
    let started_a = manager
        .start_mode_for_test(HelperMode::CrashAfterReady)
        .unwrap();
    let crashed_a = manager.wait_for_state(RuntimeState::Crashed, Duration::from_secs(2));
    let instance_a = crashed_a.runtime_instance_id.unwrap();
    manager.request_stop().unwrap();

    let started_b = manager.start_test().unwrap();
    let instance_b = started_b.runtime_instance_id.clone().unwrap();
    assert_ne!(instance_a, instance_b);
    let before_late_events = manager.snapshot();
    assert!(!mark_ready(&manager.shared, &instance_a));
    finish_start_failure(&manager.shared, &instance_a, "late_old_start_failure", None);
    finish_after_ready_failure(
        &manager.shared,
        &instance_a,
        "late_old_runtime_failure",
        None,
    );
    finish_stopped(&manager.shared, &instance_a, None, None);
    #[cfg(unix)]
    {
        use std::os::unix::process::ExitStatusExt;
        finish_child_exit(&manager.shared, &instance_a, ExitStatus::from_raw(0));
    }
    assert_eq!(manager.snapshot(), before_late_events);

    let ready_b = manager.wait_for_state(RuntimeState::Ready, Duration::from_secs(2));
    assert_eq!(
        ready_b.runtime_instance_id.as_deref(),
        Some(instance_b.as_str())
    );
    assert_eq!(ready_b.state, RuntimeState::Ready);
    manager.stop_and_wait().unwrap();
    assert_clean(&manager);
    assert_ne!(started_a.runtime_instance_id, Some(instance_b));
}

#[test]
fn stop_timeout_remains_an_error_for_its_still_active_target() {
    let mut options = RuntimeOptions::test();
    options.command_timeout = Duration::from_millis(50);
    let manager = RuntimeManager::with_options(options);
    let started = manager
        .start_mode_for_test(HelperMode::HangOnShutdown)
        .unwrap();
    manager.wait_for_state(RuntimeState::Ready, Duration::from_secs(2));
    let target_id = started.runtime_instance_id.unwrap();

    assert_eq!(manager.stop_and_wait(), Err(ManagerError::CommandTimeout));
    let timed_out = manager.snapshot();
    assert_eq!(
        timed_out.runtime_instance_id.as_deref(),
        Some(target_id.as_str())
    );
    assert_eq!(timed_out.state, RuntimeState::Stopping);
    let stopped = manager.wait_for_state(RuntimeState::Stopped, Duration::from_secs(2));
    assert_eq!(
        stopped.runtime_instance_id.as_deref(),
        Some(target_id.as_str())
    );
    assert_eq!(stopped.failure_category, Some("shutdown_timeout"));
    assert_clean(&manager);
}

#[test]
fn stopping_one_manager_does_not_stop_another_managers_child() {
    let manager_a = manager();
    let manager_b = manager();
    let started_a = manager_a.start_test().unwrap();
    let started_b = manager_b.start_test().unwrap();
    let ready_a = manager_a.wait_for_state(RuntimeState::Ready, Duration::from_secs(2));
    let ready_b = manager_b.wait_for_state(RuntimeState::Ready, Duration::from_secs(2));
    assert_ne!(ready_a.pid, ready_b.pid);

    manager_a.stop_and_wait().unwrap();

    let still_ready_b = manager_b.snapshot();
    assert_eq!(
        still_ready_b.runtime_instance_id,
        started_b.runtime_instance_id
    );
    assert_eq!(still_ready_b.state, RuntimeState::Ready);
    assert!(manager_b.has_supervisor());
    assert_eq!(
        manager_a.snapshot().runtime_instance_id,
        started_a.runtime_instance_id
    );
    manager_b.stop_and_wait().unwrap();
    assert_clean(&manager_a);
    assert_clean(&manager_b);
}

#[test]
#[ignore = "stress probe; run explicitly for the MAC-001.1 handoff"]
fn stress_start_stop_race_500_rounds() {
    let started_at = Instant::now();
    for round in 0..500 {
        let manager = Arc::new(manager());
        let start_manager = Arc::clone(&manager);
        let stop_manager = Arc::clone(&manager);
        let (start, stop) = race_pair(
            move || start_manager.start_test(),
            move || stop_manager.stop_and_wait(),
        );
        let start = start.unwrap_or_else(|error| panic!("round {round}: start failed: {error:?}"));
        let stop = stop.unwrap_or_else(|error| panic!("round {round}: stop failed: {error:?}"));

        let current = manager.snapshot();
        assert!(
            current.state.is_terminal() || current.runtime_instance_id == start.runtime_instance_id,
            "round {round}: unexpected generation after race: {current:?}"
        );
        if current.state.is_active() {
            assert_eq!(
                stop.runtime_instance_id, None,
                "round {round}: stop adopted future generation {:?}",
                start.runtime_instance_id
            );
            manager.stop_and_wait().unwrap_or_else(|error| {
                panic!(
                    "round {round}: cleanup of generation {:?} failed: {error:?}",
                    current.runtime_instance_id
                )
            });
        } else {
            assert_eq!(
                stop.runtime_instance_id, start.runtime_instance_id,
                "round {round}: completed stop belongs to an unexpected generation"
            );
        }
        assert_clean(&manager);
    }
    eprintln!(
        "PASS start/stop stress rounds=500 duration_ms={}",
        started_at.elapsed().as_millis()
    );
}
