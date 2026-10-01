use std::{
    env,
    io::{self, BufRead, BufReader, Write},
    process::{Child, Command, ExitStatus, Stdio},
    sync::{
        atomic::{AtomicU64, Ordering},
        mpsc::{self, Receiver, RecvTimeoutError, Sender},
        Arc, Condvar, Mutex, MutexGuard,
    },
    thread,
    time::{Duration, Instant, SystemTime, UNIX_EPOCH},
};

const READY_PREFIX: &str = "JARVIS_RUNTIME_READY ";
const ACK_PREFIX: &str = "JARVIS_RUNTIME_ACK ";
const STOP_PREFIX: &str = "JARVIS_RUNTIME_STOP ";
const TEST_HELPER_SWITCH: &str = "--jarvis-runtime-test-helper";
const STARTUP_TIMEOUT: Duration = Duration::from_secs(5);
const SHUTDOWN_TIMEOUT: Duration = Duration::from_millis(700);
const COMMAND_TIMEOUT: Duration = Duration::from_secs(5);
const POLL_INTERVAL: Duration = Duration::from_millis(10);
#[cfg(test)]
const HELPER_ID_ENV: &str = "JARVIS_RUNTIME_HELPER_ID";
#[cfg(test)]
const HELPER_MODE_ENV: &str = "JARVIS_RUNTIME_HELPER_MODE";
#[cfg(test)]
const HELPER_STALE_ID_ENV: &str = "JARVIS_RUNTIME_HELPER_STALE_ID";

static NEXT_INSTANCE: AtomicU64 = AtomicU64::new(1);

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum RuntimeState {
    Stopped,
    Starting,
    Ready,
    Stopping,
    Failed,
    Crashed,
}

impl RuntimeState {
    fn as_str(self) -> &'static str {
        match self {
            Self::Stopped => "STOPPED",
            Self::Starting => "STARTING",
            Self::Ready => "READY",
            Self::Stopping => "STOPPING",
            Self::Failed => "FAILED",
            Self::Crashed => "CRASHED",
        }
    }

    fn is_terminal(self) -> bool {
        matches!(self, Self::Stopped | Self::Failed | Self::Crashed)
    }

    fn is_active(self) -> bool {
        matches!(self, Self::Starting | Self::Ready | Self::Stopping)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct RuntimeSnapshot {
    state: RuntimeState,
    runtime_instance_id: Option<String>,
    pid: Option<u32>,
    started_at_unix_ms: Option<u128>,
    ready_at_unix_ms: Option<u128>,
    exit_code: Option<i32>,
    failure_category: Option<&'static str>,
}

impl RuntimeSnapshot {
    fn stopped() -> Self {
        Self {
            state: RuntimeState::Stopped,
            runtime_instance_id: None,
            pid: None,
            started_at_unix_ms: None,
            ready_at_unix_ms: None,
            exit_code: None,
            failure_category: None,
        }
    }

    fn json(&self) -> String {
        format!(
            "{{\"state\":{},\"runtime_instance_id\":{},\"pid\":{},\"started_at_unix_ms\":{},\"ready_at_unix_ms\":{},\"exit_code\":{},\"failure_category\":{}}}",
            json_string(self.state.as_str()),
            json_optional_string(self.runtime_instance_id.as_deref()),
            json_optional_number(self.pid.map(u64::from)),
            json_optional_number(self.started_at_unix_ms),
            json_optional_number(self.ready_at_unix_ms),
            json_optional_number(self.exit_code.map(|value| value as i64)),
            json_optional_string(self.failure_category),
        )
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum HelperMode {
    Normal,
    #[cfg(test)]
    SlowReady,
    #[cfg(test)]
    CrashBeforeReady,
    #[cfg(test)]
    CrashAfterReady,
    #[cfg(test)]
    HangOnShutdown,
    #[cfg(test)]
    WrongReadiness,
    #[cfg(test)]
    StaleReadiness,
    #[cfg(test)]
    InvalidReadiness,
    #[cfg(test)]
    DuplicateReadiness,
    #[cfg(test)]
    CloseStdoutBeforeReady,
}

impl HelperMode {
    fn as_str(self) -> &'static str {
        match self {
            Self::Normal => "normal",
            #[cfg(test)]
            Self::SlowReady => "slow-ready",
            #[cfg(test)]
            Self::CrashBeforeReady => "crash-before-ready",
            #[cfg(test)]
            Self::CrashAfterReady => "crash-after-ready",
            #[cfg(test)]
            Self::HangOnShutdown => "hang-on-shutdown",
            #[cfg(test)]
            Self::WrongReadiness => "wrong-readiness",
            #[cfg(test)]
            Self::StaleReadiness => "stale-readiness",
            #[cfg(test)]
            Self::InvalidReadiness => "invalid-readiness",
            #[cfg(test)]
            Self::DuplicateReadiness => "duplicate-readiness",
            #[cfg(test)]
            Self::CloseStdoutBeforeReady => "close-stdout-before-ready",
        }
    }

    fn parse(value: &str) -> Option<Self> {
        Some(match value {
            "normal" => Self::Normal,
            #[cfg(test)]
            "slow-ready" => Self::SlowReady,
            #[cfg(test)]
            "crash-before-ready" => Self::CrashBeforeReady,
            #[cfg(test)]
            "crash-after-ready" => Self::CrashAfterReady,
            #[cfg(test)]
            "hang-on-shutdown" => Self::HangOnShutdown,
            #[cfg(test)]
            "wrong-readiness" => Self::WrongReadiness,
            #[cfg(test)]
            "stale-readiness" => Self::StaleReadiness,
            #[cfg(test)]
            "invalid-readiness" => Self::InvalidReadiness,
            #[cfg(test)]
            "duplicate-readiness" => Self::DuplicateReadiness,
            #[cfg(test)]
            "close-stdout-before-ready" => Self::CloseStdoutBeforeReady,
            _ => return None,
        })
    }
}

#[derive(Clone, Copy)]
struct RuntimeOptions {
    startup_timeout: Duration,
    shutdown_timeout: Duration,
    command_timeout: Duration,
}

impl RuntimeOptions {
    const fn production() -> Self {
        Self {
            startup_timeout: STARTUP_TIMEOUT,
            shutdown_timeout: SHUTDOWN_TIMEOUT,
            command_timeout: COMMAND_TIMEOUT,
        }
    }

    #[cfg(test)]
    const fn test() -> Self {
        Self {
            startup_timeout: Duration::from_millis(450),
            shutdown_timeout: Duration::from_millis(250),
            command_timeout: Duration::from_secs(4),
        }
    }
}

struct Shared {
    inner: Mutex<Inner>,
    changed: Condvar,
    options: RuntimeOptions,
}

struct Inner {
    snapshot: RuntimeSnapshot,
    supervisor: Option<Sender<SupervisorMessage>>,
}

enum SupervisorMessage {
    Output(String),
    StdoutClosed,
    StdoutFailed,
    Stop(Sender<RuntimeSnapshot>),
}

pub struct RuntimeManager {
    shared: Arc<Shared>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum ManagerError {
    InvalidState,
    SupervisorUnavailable,
    CommandTimeout,
    SpawnFailed,
}

impl ManagerError {
    fn message(self, state: RuntimeState, action: &'static str) -> &'static str {
        match self {
            Self::InvalidState => match (action, state) {
                ("start", RuntimeState::Starting) => "O runtime já está iniciando.",
                ("start", RuntimeState::Ready) => "O runtime já está pronto.",
                ("start", RuntimeState::Stopping) => "O runtime está encerrando.",
                ("start", RuntimeState::Failed | RuntimeState::Crashed) => {
                    "Use Reiniciar para iniciar uma nova instância."
                }
                ("restart", _) => "Reiniciar está disponível após falha ou interrupção.",
                ("start", _) => "O runtime não pode ser iniciado neste estado.",
                _ => "A ação não está disponível neste estado.",
            },
            Self::SupervisorUnavailable => "O supervisor local não está disponível.",
            Self::CommandTimeout => "O runtime não confirmou o encerramento dentro do prazo.",
            Self::SpawnFailed => "Não foi possível iniciar o processo de teste.",
        }
    }
}

impl RuntimeManager {
    pub(crate) fn new() -> Self {
        Self::with_options(RuntimeOptions::production())
    }

    fn with_options(options: RuntimeOptions) -> Self {
        Self {
            shared: Arc::new(Shared {
                inner: Mutex::new(Inner {
                    snapshot: RuntimeSnapshot::stopped(),
                    supervisor: None,
                }),
                changed: Condvar::new(),
                options,
            }),
        }
    }

    fn snapshot(&self) -> RuntimeSnapshot {
        lock_inner(&self.shared).snapshot.clone()
    }

    fn status_json(&self) -> String {
        json_envelope(true, &self.snapshot(), None)
    }

    fn start_test(&self) -> Result<RuntimeSnapshot, ManagerError> {
        self.start_mode(HelperMode::Normal, false)
    }

    fn restart_test(&self) -> Result<RuntimeSnapshot, ManagerError> {
        self.start_mode(HelperMode::Normal, true)
    }

    fn start_mode(
        &self,
        mode: HelperMode,
        explicit_restart: bool,
    ) -> Result<RuntimeSnapshot, ManagerError> {
        self.start_mode_with_stale_id(mode, explicit_restart, None)
    }

    fn start_mode_with_stale_id(
        &self,
        mode: HelperMode,
        explicit_restart: bool,
        stale_instance_id: Option<&str>,
    ) -> Result<RuntimeSnapshot, ManagerError> {
        let mut inner = lock_inner(&self.shared);
        let previous = inner.snapshot.state;
        let allowed = if explicit_restart {
            matches!(previous, RuntimeState::Failed | RuntimeState::Crashed)
        } else {
            previous == RuntimeState::Stopped
        };
        if !allowed {
            return Err(ManagerError::InvalidState);
        }

        let instance_id = new_instance_id();
        let mut command = helper_command(&instance_id, mode, stale_instance_id)
            .map_err(|_| ManagerError::SpawnFailed)?;
        transition_log(previous, RuntimeState::Starting, &instance_id);
        inner.snapshot = RuntimeSnapshot {
            state: RuntimeState::Starting,
            runtime_instance_id: Some(instance_id.clone()),
            pid: None,
            started_at_unix_ms: Some(unix_time_ms()),
            ready_at_unix_ms: None,
            exit_code: None,
            failure_category: None,
        };
        inner.supervisor = None;

        command
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::null());

        let mut child = match command.spawn() {
            Ok(child) => child,
            Err(_) => {
                inner.snapshot.state = RuntimeState::Failed;
                inner.snapshot.failure_category = Some("spawn_failed");
                transition_log(RuntimeState::Starting, RuntimeState::Failed, &instance_id);
                self.shared.changed.notify_all();
                return Err(ManagerError::SpawnFailed);
            }
        };
        let pid = child.id();
        inner.snapshot.pid = Some(pid);
        eprintln!("runtime child started instance_id={instance_id} pid={pid}");

        let stdout = child
            .stdout
            .take()
            .expect("stdout is piped for runtime helper");
        let stdin = child.stdin.take();
        let (sender, receiver) = mpsc::channel();
        inner.supervisor = Some(sender.clone());
        let reader_sender = sender.clone();
        thread::spawn(move || read_child_stdout(stdout, reader_sender));

        let shared = Arc::clone(&self.shared);
        let options = self.shared.options;
        let worker_instance_id = instance_id.clone();
        thread::spawn(move || {
            supervise_child(shared, worker_instance_id, child, stdin, receiver, options)
        });

        self.shared.changed.notify_all();
        Ok(inner.snapshot.clone())
    }

    /// Requests a controlled stop and returns immediately. The supervisor owns and reaps the child.
    fn request_stop(&self) -> Result<RuntimeSnapshot, ManagerError> {
        let sender = {
            let mut inner = lock_inner(&self.shared);
            let state = inner.snapshot.state;
            match state {
                RuntimeState::Stopped => return Ok(inner.snapshot.clone()),
                RuntimeState::Failed | RuntimeState::Crashed => {
                    let instance_id = inner
                        .snapshot
                        .runtime_instance_id
                        .clone()
                        .unwrap_or_default();
                    if transition_locked(&mut inner, RuntimeState::Stopped, &instance_id) {
                        inner.supervisor = None;
                    }
                    self.shared.changed.notify_all();
                    return Ok(inner.snapshot.clone());
                }
                RuntimeState::Stopping => return Ok(inner.snapshot.clone()),
                RuntimeState::Starting | RuntimeState::Ready => inner.supervisor.clone(),
            }
        };

        let sender = sender.ok_or(ManagerError::SupervisorUnavailable)?;
        let (reply_tx, _reply_rx) = mpsc::channel();
        if sender.send(SupervisorMessage::Stop(reply_tx)).is_err() {
            let snapshot = self.snapshot();
            if snapshot.state.is_terminal() {
                return Ok(snapshot);
            }
            return Err(ManagerError::SupervisorUnavailable);
        }
        Ok(self.snapshot())
    }

    /// Used during normal application exit and in lifecycle tests; waits until the child is reaped.
    pub(crate) fn stop_and_wait(&self) -> Result<RuntimeSnapshot, ManagerError> {
        self.request_stop()?;
        let deadline = Instant::now() + self.shared.options.command_timeout;
        let mut inner = lock_inner(&self.shared);
        while inner.snapshot.state.is_active() {
            let now = Instant::now();
            if now >= deadline {
                return Err(ManagerError::CommandTimeout);
            }
            let remaining = deadline.saturating_duration_since(now);
            let (guard, result) = self
                .shared
                .changed
                .wait_timeout(inner, remaining)
                .unwrap_or_else(|error| error.into_inner());
            inner = guard;
            if result.timed_out() && inner.snapshot.state.is_active() {
                return Err(ManagerError::CommandTimeout);
            }
        }
        Ok(inner.snapshot.clone())
    }

    #[cfg(test)]
    fn start_mode_for_test(&self, mode: HelperMode) -> Result<RuntimeSnapshot, ManagerError> {
        self.start_mode(mode, false)
    }

    #[cfg(test)]
    fn start_stale_mode_for_test(
        &self,
        stale_instance_id: &str,
    ) -> Result<RuntimeSnapshot, ManagerError> {
        self.start_mode_with_stale_id(HelperMode::StaleReadiness, false, Some(stale_instance_id))
    }

    #[cfg(test)]
    fn wait_for_state(&self, target: RuntimeState, timeout: Duration) -> RuntimeSnapshot {
        let deadline = Instant::now() + timeout;
        let mut inner = lock_inner(&self.shared);
        loop {
            if inner.snapshot.state == target {
                return inner.snapshot.clone();
            }
            let now = Instant::now();
            assert!(
                now < deadline,
                "timeout waiting for {target:?}; current={:?}",
                inner.snapshot
            );
            let (guard, result) = self
                .shared
                .changed
                .wait_timeout(inner, deadline.saturating_duration_since(now))
                .unwrap_or_else(|error| error.into_inner());
            inner = guard;
            assert!(
                !result.timed_out() || inner.snapshot.state == target,
                "timeout waiting for {target:?}; current={:?}",
                inner.snapshot
            );
        }
    }

    #[cfg(test)]
    fn has_supervisor(&self) -> bool {
        lock_inner(&self.shared).supervisor.is_some()
    }
}

impl Default for RuntimeManager {
    fn default() -> Self {
        Self::new()
    }
}

impl Drop for RuntimeManager {
    fn drop(&mut self) {
        let _ = self.stop_and_wait();
    }
}

fn lock_inner(shared: &Shared) -> MutexGuard<'_, Inner> {
    shared
        .inner
        .lock()
        .unwrap_or_else(|error| error.into_inner())
}

fn transition_allowed(from: RuntimeState, to: RuntimeState) -> bool {
    matches!(
        (from, to),
        (RuntimeState::Stopped, RuntimeState::Starting)
            | (RuntimeState::Starting, RuntimeState::Ready)
            | (RuntimeState::Starting, RuntimeState::Stopping)
            | (RuntimeState::Starting, RuntimeState::Failed)
            | (RuntimeState::Ready, RuntimeState::Stopping)
            | (RuntimeState::Ready, RuntimeState::Crashed)
            | (RuntimeState::Stopping, RuntimeState::Stopped)
            | (RuntimeState::Failed, RuntimeState::Starting)
            | (RuntimeState::Failed, RuntimeState::Stopped)
            | (RuntimeState::Crashed, RuntimeState::Starting)
            | (RuntimeState::Crashed, RuntimeState::Stopped)
    )
}

fn transition_locked(inner: &mut Inner, next: RuntimeState, instance_id: &str) -> bool {
    let previous = inner.snapshot.state;
    if !transition_allowed(previous, next) {
        return previous == next;
    }
    if previous != next {
        transition_log(previous, next, instance_id);
        inner.snapshot.state = next;
    }
    true
}

fn transition_log(from: RuntimeState, to: RuntimeState, instance_id: &str) {
    eprintln!(
        "runtime transition instance_id={instance_id} from={} to={}",
        from.as_str(),
        to.as_str()
    );
}

fn mark_ready(shared: &Shared, instance_id: &str) -> bool {
    let mut inner = lock_inner(shared);
    if inner.snapshot.runtime_instance_id.as_deref() != Some(instance_id)
        || inner.snapshot.state != RuntimeState::Starting
    {
        return false;
    }
    if !transition_locked(&mut inner, RuntimeState::Ready, instance_id) {
        return false;
    }
    inner.snapshot.ready_at_unix_ms = Some(unix_time_ms());
    eprintln!(
        "runtime ready instance_id={instance_id} pid={:?}",
        inner.snapshot.pid
    );
    shared.changed.notify_all();
    true
}

fn finish_child_exit(shared: &Shared, instance_id: &str, status: ExitStatus) {
    let mut inner = lock_inner(shared);
    if inner.snapshot.runtime_instance_id.as_deref() != Some(instance_id) {
        return;
    }
    let target = match inner.snapshot.state {
        RuntimeState::Starting => {
            inner.snapshot.failure_category = Some("child_exit_before_ready");
            RuntimeState::Failed
        }
        RuntimeState::Ready => {
            inner.snapshot.failure_category = Some("child_crash");
            RuntimeState::Crashed
        }
        RuntimeState::Stopping => RuntimeState::Stopped,
        _ => return,
    };
    inner.snapshot.exit_code = status.code();
    transition_locked(&mut inner, target, instance_id);
    inner.supervisor = None;
    eprintln!(
        "runtime child exited instance_id={instance_id} exit_code={:?} state={}",
        inner.snapshot.exit_code,
        inner.snapshot.state.as_str()
    );
    shared.changed.notify_all();
}

fn finish_start_failure(
    shared: &Shared,
    instance_id: &str,
    category: &'static str,
    status: Option<ExitStatus>,
) {
    let mut inner = lock_inner(shared);
    if inner.snapshot.runtime_instance_id.as_deref() != Some(instance_id)
        || inner.snapshot.state != RuntimeState::Starting
    {
        return;
    }
    inner.snapshot.failure_category = Some(category);
    inner.snapshot.exit_code = status.and_then(|value| value.code());
    transition_locked(&mut inner, RuntimeState::Failed, instance_id);
    inner.supervisor = None;
    eprintln!("runtime failed instance_id={instance_id} category={category}");
    shared.changed.notify_all();
}

fn finish_after_ready_failure(
    shared: &Shared,
    instance_id: &str,
    category: &'static str,
    status: Option<ExitStatus>,
) {
    let mut inner = lock_inner(shared);
    if inner.snapshot.runtime_instance_id.as_deref() != Some(instance_id)
        || inner.snapshot.state != RuntimeState::Ready
    {
        return;
    }
    inner.snapshot.failure_category = Some(category);
    inner.snapshot.exit_code = status.and_then(|value| value.code());
    transition_locked(&mut inner, RuntimeState::Crashed, instance_id);
    inner.supervisor = None;
    eprintln!("runtime crashed instance_id={instance_id} category={category}");
    shared.changed.notify_all();
}

fn finish_stopped(
    shared: &Shared,
    instance_id: &str,
    status: Option<ExitStatus>,
    failure_category: Option<&'static str>,
) -> RuntimeSnapshot {
    let mut inner = lock_inner(shared);
    if inner.snapshot.runtime_instance_id.as_deref() == Some(instance_id)
        && inner.snapshot.state == RuntimeState::Stopping
    {
        inner.snapshot.exit_code = status.and_then(|value| value.code());
        inner.snapshot.failure_category = failure_category;
        transition_locked(&mut inner, RuntimeState::Stopped, instance_id);
        inner.supervisor = None;
        eprintln!(
            "runtime stopped instance_id={instance_id} exit_code={:?} failure_category={:?}",
            inner.snapshot.exit_code, inner.snapshot.failure_category
        );
        shared.changed.notify_all();
    }
    inner.snapshot.clone()
}

fn supervise_child(
    shared: Arc<Shared>,
    instance_id: String,
    mut child: Child,
    mut stdin: Option<std::process::ChildStdin>,
    receiver: Receiver<SupervisorMessage>,
    options: RuntimeOptions,
) {
    let startup_deadline = Instant::now() + options.startup_timeout;
    loop {
        let state = lock_inner(&shared).snapshot.state;
        if state == RuntimeState::Starting && Instant::now() >= startup_deadline {
            let _ = child.kill();
            let status = child.wait().ok();
            finish_start_failure(&shared, &instance_id, "startup_timeout", status);
            return;
        }

        let timeout = if state == RuntimeState::Starting {
            POLL_INTERVAL.min(startup_deadline.saturating_duration_since(Instant::now()))
        } else {
            POLL_INTERVAL
        };
        let message = match receiver.recv_timeout(timeout) {
            Ok(message) => message,
            Err(RecvTimeoutError::Timeout) => {
                match child.try_wait() {
                    Ok(Some(status)) => finish_child_exit(&shared, &instance_id, status),
                    Ok(None) => continue,
                    Err(_) => {
                        let _ = child.kill();
                        let status = child.wait().ok();
                        if lock_inner(&shared).snapshot.state == RuntimeState::Starting {
                            finish_start_failure(
                                &shared,
                                &instance_id,
                                "child_monitor_failed",
                                status,
                            );
                        } else {
                            finish_after_ready_failure(
                                &shared,
                                &instance_id,
                                "child_monitor_failed",
                                status,
                            );
                        }
                    }
                }
                return;
            }
            Err(RecvTimeoutError::Disconnected) => {
                let _ = child.kill();
                let status = child.wait().ok();
                let state = lock_inner(&shared).snapshot.state;
                if state == RuntimeState::Starting {
                    finish_start_failure(&shared, &instance_id, "supervisor_disconnected", status);
                } else if state == RuntimeState::Ready {
                    finish_after_ready_failure(
                        &shared,
                        &instance_id,
                        "supervisor_disconnected",
                        status,
                    );
                }
                return;
            }
        };

        match message {
            SupervisorMessage::Output(line) => {
                if is_ready_for(&line, &instance_id) && mark_ready(&shared, &instance_id) {
                    let acknowledged = stdin.as_mut().is_some_and(|pipe| {
                        writeln!(pipe, "{ACK_PREFIX}{instance_id}")
                            .and_then(|_| pipe.flush())
                            .is_ok()
                    });
                    if !acknowledged {
                        let _ = child.kill();
                        let status = child.wait().ok();
                        finish_after_ready_failure(
                            &shared,
                            &instance_id,
                            "readiness_ack_failed",
                            status,
                        );
                        return;
                    }
                }
            }
            SupervisorMessage::StdoutClosed => {
                let state = lock_inner(&shared).snapshot.state;
                if state == RuntimeState::Starting {
                    if let Ok(Some(status)) = child.try_wait() {
                        finish_child_exit(&shared, &instance_id, status);
                        return;
                    }
                    let _ = child.kill();
                    let status = child.wait().ok();
                    finish_start_failure(&shared, &instance_id, "readiness_channel_closed", status);
                    return;
                }
            }
            SupervisorMessage::StdoutFailed => {
                let state = lock_inner(&shared).snapshot.state;
                let _ = child.kill();
                let status = child.wait().ok();
                if state == RuntimeState::Starting {
                    finish_start_failure(&shared, &instance_id, "readiness_channel_failed", status);
                } else if state == RuntimeState::Ready {
                    finish_after_ready_failure(
                        &shared,
                        &instance_id,
                        "readiness_channel_failed",
                        status,
                    );
                }
                return;
            }
            SupervisorMessage::Stop(reply) => {
                match child.try_wait() {
                    Ok(Some(status)) => {
                        finish_child_exit(&shared, &instance_id, status);
                        let _ = reply.send(lock_inner(&shared).snapshot.clone());
                        return;
                    }
                    Err(_) => {
                        let _ = child.kill();
                        let status = child.wait().ok();
                        let state = lock_inner(&shared).snapshot.state;
                        if state == RuntimeState::Starting {
                            finish_start_failure(
                                &shared,
                                &instance_id,
                                "child_monitor_failed",
                                status,
                            );
                        } else {
                            finish_after_ready_failure(
                                &shared,
                                &instance_id,
                                "child_monitor_failed",
                                status,
                            );
                        }
                        let _ = reply.send(lock_inner(&shared).snapshot.clone());
                        return;
                    }
                    Ok(None) => {}
                }
                {
                    let mut inner = lock_inner(&shared);
                    if inner.snapshot.runtime_instance_id.as_deref() == Some(instance_id.as_str())
                        && inner.snapshot.state.is_active()
                    {
                        transition_locked(&mut inner, RuntimeState::Stopping, &instance_id);
                        shared.changed.notify_all();
                    }
                }
                if let Some(pipe) = stdin.as_mut() {
                    let _ = writeln!(pipe, "{STOP_PREFIX}{instance_id}");
                    let _ = pipe.flush();
                }
                let shutdown_deadline = Instant::now() + options.shutdown_timeout;
                loop {
                    match child.try_wait() {
                        Ok(Some(status)) => {
                            let snapshot =
                                finish_stopped(&shared, &instance_id, Some(status), None);
                            let _ = reply.send(snapshot);
                            return;
                        }
                        Ok(None) if Instant::now() < shutdown_deadline => {
                            thread::sleep(POLL_INTERVAL);
                        }
                        Ok(None) | Err(_) => {
                            let _ = child.kill();
                            let status = child.wait().ok();
                            let snapshot = finish_stopped(
                                &shared,
                                &instance_id,
                                status,
                                Some("shutdown_timeout"),
                            );
                            let _ = reply.send(snapshot);
                            return;
                        }
                    }
                }
            }
        }
    }
}

fn read_child_stdout(stdout: std::process::ChildStdout, sender: Sender<SupervisorMessage>) {
    let mut reader = BufReader::new(stdout);
    loop {
        let mut line = String::new();
        match reader.read_line(&mut line) {
            Ok(0) => {
                let _ = sender.send(SupervisorMessage::StdoutClosed);
                return;
            }
            Ok(_) => {
                if sender.send(SupervisorMessage::Output(line)).is_err() {
                    return;
                }
            }
            Err(_) => {
                let _ = sender.send(SupervisorMessage::StdoutFailed);
                return;
            }
        }
    }
}

fn is_ready_for(line: &str, expected_instance_id: &str) -> bool {
    let line = line.strip_suffix('\n').unwrap_or(line);
    let line = line.strip_suffix('\r').unwrap_or(line);
    line == format!("{READY_PREFIX}{expected_instance_id}")
}

fn helper_arguments(instance_id: &str, mode: HelperMode) -> Vec<String> {
    vec![
        TEST_HELPER_SWITCH.to_owned(),
        instance_id.to_owned(),
        mode.as_str().to_owned(),
    ]
}

fn helper_command(
    instance_id: &str,
    mode: HelperMode,
    stale_instance_id: Option<&str>,
) -> io::Result<Command> {
    #[cfg(test)]
    {
        let executable = env::current_exe()?;
        let mut command = Command::new(executable);
        command.env_clear();
        command
            .arg("--ignored")
            .arg("--exact")
            .arg("runtime_manager::tests::runtime_helper_entry")
            .arg("--format=terse")
            .arg("--nocapture")
            .arg("--test-threads=1")
            .env(HELPER_ID_ENV, instance_id)
            .env(HELPER_MODE_ENV, mode.as_str());
        if let Some(stale_instance_id) = stale_instance_id {
            command.env(HELPER_STALE_ID_ENV, stale_instance_id);
        }
        return Ok(command);
    }
    #[cfg(not(test))]
    {
        let _ = stale_instance_id;
        let executable = env::current_exe()?;
        let mut command = Command::new(executable);
        command.env_clear();
        command.args(helper_arguments(instance_id, mode));
        Ok(command)
    }
}

fn new_instance_id() -> String {
    let sequence = NEXT_INSTANCE.fetch_add(1, Ordering::Relaxed);
    let timestamp = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_nanos();
    format!("{}-{timestamp}-{sequence}", std::process::id())
}

fn unix_time_ms() -> u128 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis()
}

fn json_string(value: &str) -> String {
    let mut result = String::from("\"");
    for character in value.chars() {
        match character {
            '"' => result.push_str("\\\""),
            '\\' => result.push_str("\\\\"),
            '\n' => result.push_str("\\n"),
            '\r' => result.push_str("\\r"),
            '\t' => result.push_str("\\t"),
            value if value.is_control() => result.push(' '),
            value => result.push(value),
        }
    }
    result.push('"');
    result
}

fn json_optional_string(value: Option<&str>) -> String {
    value.map(json_string).unwrap_or_else(|| "null".to_owned())
}

fn json_optional_number(value: Option<impl std::fmt::Display>) -> String {
    value
        .map(|number| number.to_string())
        .unwrap_or_else(|| "null".to_owned())
}

fn json_envelope(ok: bool, snapshot: &RuntimeSnapshot, error: Option<&str>) -> String {
    format!(
        "{{\"ok\":{ok},\"snapshot\":{},\"error\":{}}}",
        snapshot.json(),
        json_optional_string(error)
    )
}

#[cfg(test)]
fn close_stdout_for_helper() {
    #[cfg(unix)]
    {
        use std::{fs::File, os::fd::FromRawFd};
        // This runs only in the isolated synthetic helper process.
        let stdout = unsafe { File::from_raw_fd(1) };
        drop(stdout);
    }
}

fn wait_for_ack(input: &mut impl BufRead, instance_id: &str) -> bool {
    loop {
        let mut line = String::new();
        if input.read_line(&mut line).unwrap_or(0) == 0 {
            return false;
        }
        let command = line.trim_end_matches(['\r', '\n']);
        if command == format!("{ACK_PREFIX}{instance_id}") {
            return true;
        }
        if command == format!("{STOP_PREFIX}{instance_id}") {
            return false;
        }
    }
}

#[cfg(test)]
fn run_helper(mode: HelperMode, instance_id: &str, stale_instance_id: Option<&str>) -> i32 {
    let stdout = io::stdout();
    let mut output = stdout.lock();
    let mut input = BufReader::new(io::stdin());

    match mode {
        HelperMode::CrashBeforeReady => return 41,
        HelperMode::SlowReady => thread::sleep(Duration::from_millis(900)),
        HelperMode::CloseStdoutBeforeReady => {
            drop(output);
            close_stdout_for_helper();
            let mut line = String::new();
            while input.read_line(&mut line).unwrap_or(0) > 0 {
                if line.trim_end_matches(['\r', '\n']) == format!("{STOP_PREFIX}{instance_id}") {
                    return 0;
                }
                line.clear();
            }
            return 0;
        }
        _ => {}
    }

    let announced_id = match mode {
        HelperMode::WrongReadiness => "wrong-instance",
        HelperMode::StaleReadiness => stale_instance_id.unwrap_or("previous-instance"),
        _ => instance_id,
    };
    let readiness = match mode {
        HelperMode::InvalidReadiness => format!("JARVIS_RUNTIME_READY-ish {instance_id}"),
        _ => format!("{READY_PREFIX}{announced_id}"),
    };
    if writeln!(output, "{readiness}")
        .and_then(|_| output.flush())
        .is_err()
    {
        return 43;
    }
    if mode == HelperMode::DuplicateReadiness {
        if writeln!(output, "{readiness}")
            .and_then(|_| output.flush())
            .is_err()
        {
            return 43;
        }
    }
    drop(output);

    if !wait_for_ack(&mut input, instance_id) {
        return 0;
    }
    if mode == HelperMode::CrashAfterReady {
        return 42;
    }
    if mode == HelperMode::HangOnShutdown {
        loop {
            let mut ignored = String::new();
            if input.read_line(&mut ignored).unwrap_or(0) == 0 {
                thread::sleep(Duration::from_millis(50));
            }
        }
    }

    loop {
        let mut line = String::new();
        if input.read_line(&mut line).unwrap_or(0) == 0 {
            return 0;
        }
        if line.trim_end_matches(['\r', '\n']) == format!("{STOP_PREFIX}{instance_id}") {
            return 0;
        }
    }
}

#[cfg(not(test))]
fn run_helper(_mode: HelperMode, instance_id: &str, _stale_instance_id: Option<&str>) -> i32 {
    let stdout = io::stdout();
    let mut output = stdout.lock();
    if writeln!(output, "{READY_PREFIX}{instance_id}")
        .and_then(|_| output.flush())
        .is_err()
    {
        return 43;
    }
    drop(output);

    let mut input = BufReader::new(io::stdin());
    if !wait_for_ack(&mut input, instance_id) {
        return 0;
    }
    loop {
        let mut line = String::new();
        if input.read_line(&mut line).unwrap_or(0) == 0 {
            return 0;
        }
        if line.trim_end_matches(['\r', '\n']) == format!("{STOP_PREFIX}{instance_id}") {
            return 0;
        }
    }
}

/// The app binary re-enters here only with an internal, fixed helper switch and typed mode.
pub fn run_test_helper_from_args() -> bool {
    let mut args = env::args().skip(1);
    if args.next().as_deref() != Some(TEST_HELPER_SWITCH) {
        return false;
    }
    let Some(instance_id) = args.next() else {
        std::process::exit(64);
    };
    let Some(mode) = args.next().and_then(|value| HelperMode::parse(&value)) else {
        std::process::exit(64);
    };
    if args.next().is_some() {
        std::process::exit(64);
    }
    std::process::exit(run_helper(mode, &instance_id, None));
}

#[tauri::command]
pub fn runtime_status(manager: tauri::State<'_, RuntimeManager>) -> String {
    manager.status_json()
}

#[tauri::command]
pub fn runtime_start_test(manager: tauri::State<'_, RuntimeManager>) -> String {
    let result = manager.start_test();
    command_result(&manager, "start", result)
}

#[tauri::command]
pub fn runtime_stop(manager: tauri::State<'_, RuntimeManager>) -> String {
    let result = manager.request_stop();
    command_result(&manager, "stop", result)
}

#[tauri::command]
pub fn runtime_restart_test(manager: tauri::State<'_, RuntimeManager>) -> String {
    let result = manager.restart_test();
    command_result(&manager, "restart", result)
}

fn command_result(
    manager: &RuntimeManager,
    action: &'static str,
    result: Result<RuntimeSnapshot, ManagerError>,
) -> String {
    match result {
        Ok(snapshot) => json_envelope(true, &snapshot, None),
        Err(error) => {
            let snapshot = manager.snapshot();
            json_envelope(
                false,
                &snapshot,
                Some(error.message(snapshot.state, action)),
            )
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::{
        io::Write,
        process::ChildStdin,
        sync::{Barrier, Mutex as TestMutex},
    };

    fn manager() -> RuntimeManager {
        RuntimeManager::with_options(RuntimeOptions::test())
    }

    fn assert_clean(manager: &RuntimeManager) {
        let snapshot = manager.snapshot();
        assert!(
            snapshot.state.is_terminal(),
            "helper is active: {snapshot:?}"
        );
        assert!(
            !manager.has_supervisor(),
            "supervisor still owns a child: {snapshot:?}"
        );
    }

    #[test]
    #[ignore = "invoked only as a separate synthetic child process"]
    fn runtime_helper_entry() {
        let instance_id = env::var(HELPER_ID_ENV).expect("parent provides the helper instance ID");
        let mode = env::var(HELPER_MODE_ENV)
            .ok()
            .and_then(|value| HelperMode::parse(&value))
            .expect("parent provides a fixed helper mode");
        let stale_instance_id = env::var(HELPER_STALE_ID_ENV).ok();
        std::process::exit(run_helper(mode, &instance_id, stale_instance_id.as_deref()));
    }

    #[test]
    fn stopped_starting_ready_stopping_stopped() {
        let manager = manager();
        assert_eq!(manager.snapshot().state, RuntimeState::Stopped);
        let started = manager.start_test().unwrap();
        assert_eq!(started.state, RuntimeState::Starting);
        let ready = manager.wait_for_state(RuntimeState::Ready, Duration::from_secs(2));
        assert_eq!(ready.runtime_instance_id, started.runtime_instance_id);
        assert!(ready.pid.is_some());
        assert!(ready.ready_at_unix_ms.is_some());
        let stopped = manager.stop_and_wait().unwrap();
        assert_eq!(stopped.state, RuntimeState::Stopped);
        assert_clean(&manager);
    }

    #[test]
    fn slow_readiness_times_out_and_reaps_child() {
        let manager = manager();
        manager.start_mode_for_test(HelperMode::SlowReady).unwrap();
        let failed = manager.wait_for_state(RuntimeState::Failed, Duration::from_secs(2));
        assert_eq!(failed.failure_category, Some("startup_timeout"));
        assert_clean(&manager);
    }

    #[test]
    fn child_exit_before_readiness_is_failed() {
        let manager = manager();
        manager
            .start_mode_for_test(HelperMode::CrashBeforeReady)
            .unwrap();
        let failed = manager.wait_for_state(RuntimeState::Failed, Duration::from_secs(2));
        assert_eq!(failed.failure_category, Some("child_exit_before_ready"));
        assert_eq!(failed.exit_code, Some(41));
        assert_clean(&manager);
    }

    #[test]
    fn child_exit_after_readiness_is_crashed() {
        let manager = manager();
        manager
            .start_mode_for_test(HelperMode::CrashAfterReady)
            .unwrap();
        let crashed = manager.wait_for_state(RuntimeState::Crashed, Duration::from_secs(2));
        assert_eq!(crashed.failure_category, Some("child_crash"));
        assert_eq!(crashed.exit_code, Some(42));
        assert_clean(&manager);
    }

    #[test]
    fn stop_during_starting_and_stop_ready_both_reap() {
        let manager = manager();
        manager.start_mode_for_test(HelperMode::SlowReady).unwrap();
        assert_eq!(
            manager.request_stop().unwrap().state,
            RuntimeState::Starting
        );
        assert_eq!(
            manager.stop_and_wait().unwrap().state,
            RuntimeState::Stopped
        );
        assert_clean(&manager);

        manager.start_test().unwrap();
        manager.wait_for_state(RuntimeState::Ready, Duration::from_secs(2));
        assert_eq!(
            manager.stop_and_wait().unwrap().state,
            RuntimeState::Stopped
        );
        assert_clean(&manager);
    }

    #[test]
    fn duplicate_start_is_rejected_without_second_child() {
        let manager = manager();
        let first = manager.start_test().unwrap();
        let second = manager.start_test();
        assert_eq!(second.unwrap_err(), ManagerError::InvalidState);
        assert_eq!(
            manager.snapshot().runtime_instance_id,
            first.runtime_instance_id
        );
        assert_eq!(manager.snapshot().pid, first.pid);
        manager.stop_and_wait().unwrap();
        assert_clean(&manager);
    }

    #[test]
    fn duplicate_start_while_ready_returns_existing_instance_error() {
        let manager = manager();
        let first = manager.start_test().unwrap();
        manager.wait_for_state(RuntimeState::Ready, Duration::from_secs(2));
        assert_eq!(
            manager.start_test().unwrap_err(),
            ManagerError::InvalidState
        );
        assert_eq!(
            manager.snapshot().runtime_instance_id,
            first.runtime_instance_id
        );
        assert_eq!(manager.snapshot().pid, first.pid);
        manager.stop_and_wait().unwrap();
        assert_clean(&manager);
    }

    #[test]
    fn duplicate_stop_is_idempotent() {
        let manager = manager();
        manager.start_test().unwrap();
        manager.wait_for_state(RuntimeState::Ready, Duration::from_secs(2));
        manager.request_stop().unwrap();
        assert_eq!(
            manager.stop_and_wait().unwrap().state,
            RuntimeState::Stopped
        );
        assert_eq!(
            manager.stop_and_wait().unwrap().state,
            RuntimeState::Stopped
        );
        assert_clean(&manager);
    }

    #[test]
    fn shutdown_timeout_kills_and_reaps_hung_child() {
        let manager = manager();
        manager
            .start_mode_for_test(HelperMode::HangOnShutdown)
            .unwrap();
        manager.wait_for_state(RuntimeState::Ready, Duration::from_secs(2));
        let stopped = manager.stop_and_wait().unwrap();
        assert_eq!(stopped.state, RuntimeState::Stopped);
        assert_eq!(stopped.failure_category, Some("shutdown_timeout"));
        assert_clean(&manager);
    }

    #[test]
    fn stop_after_child_exit_preserves_crash_evidence() {
        let manager = manager();
        manager
            .start_mode_for_test(HelperMode::CrashAfterReady)
            .unwrap();
        let crashed = manager.wait_for_state(RuntimeState::Crashed, Duration::from_secs(2));
        assert_eq!(manager.request_stop().unwrap().state, RuntimeState::Stopped);
        assert_eq!(
            manager.snapshot().failure_category,
            crashed.failure_category
        );
        assert_clean(&manager);
    }

    #[test]
    fn explicit_restart_after_crash_uses_new_instance_id() {
        let manager = manager();
        let first = manager
            .start_mode_for_test(HelperMode::CrashAfterReady)
            .unwrap();
        let crashed = manager.wait_for_state(RuntimeState::Crashed, Duration::from_secs(2));
        assert_eq!(crashed.runtime_instance_id, first.runtime_instance_id);

        let restarted = manager.restart_test().unwrap();
        assert_eq!(restarted.state, RuntimeState::Starting);
        assert_ne!(restarted.runtime_instance_id, first.runtime_instance_id);
        manager.wait_for_state(RuntimeState::Ready, Duration::from_secs(2));
        manager.stop_and_wait().unwrap();
        assert_clean(&manager);
    }

    #[test]
    fn wrong_instance_readiness_is_ignored() {
        let manager = manager();
        manager
            .start_mode_for_test(HelperMode::WrongReadiness)
            .unwrap();
        let failed = manager.wait_for_state(RuntimeState::Failed, Duration::from_secs(2));
        assert_eq!(failed.failure_category, Some("startup_timeout"));
        assert_clean(&manager);
    }

    #[test]
    fn stale_readiness_is_ignored() {
        let manager = manager();
        let previous = manager.start_test().unwrap();
        manager.wait_for_state(RuntimeState::Ready, Duration::from_secs(2));
        manager.stop_and_wait().unwrap();
        let previous_id = previous.runtime_instance_id.unwrap();
        manager.start_stale_mode_for_test(&previous_id).unwrap();
        let failed = manager.wait_for_state(RuntimeState::Failed, Duration::from_secs(2));
        assert_eq!(failed.failure_category, Some("startup_timeout"));
        assert_clean(&manager);
    }

    #[test]
    fn readiness_like_but_invalid_text_is_ignored() {
        let manager = manager();
        manager
            .start_mode_for_test(HelperMode::InvalidReadiness)
            .unwrap();
        let failed = manager.wait_for_state(RuntimeState::Failed, Duration::from_secs(2));
        assert_eq!(failed.failure_category, Some("startup_timeout"));
        assert_clean(&manager);
    }

    #[test]
    fn duplicate_readiness_does_not_duplicate_transition() {
        let manager = manager();
        manager
            .start_mode_for_test(HelperMode::DuplicateReadiness)
            .unwrap();
        let ready = manager.wait_for_state(RuntimeState::Ready, Duration::from_secs(2));
        thread::sleep(Duration::from_millis(30));
        assert_eq!(manager.snapshot().state, RuntimeState::Ready);
        assert_eq!(
            manager.snapshot().runtime_instance_id,
            ready.runtime_instance_id
        );
        manager.stop_and_wait().unwrap();
        assert_clean(&manager);
    }

    #[test]
    fn closed_stdout_before_readiness_fails_and_reaps_child() {
        let manager = manager();
        manager
            .start_mode_for_test(HelperMode::CloseStdoutBeforeReady)
            .unwrap();
        let failed = manager.wait_for_state(RuntimeState::Failed, Duration::from_secs(2));
        assert_eq!(failed.failure_category, Some("readiness_channel_closed"));
        assert_clean(&manager);
    }

    #[test]
    fn cleanup_on_normal_application_shutdown() {
        let manager = manager();
        manager.start_test().unwrap();
        manager.wait_for_state(RuntimeState::Ready, Duration::from_secs(2));
        assert_eq!(
            manager.stop_and_wait().unwrap().state,
            RuntimeState::Stopped
        );
        assert_clean(&manager);
    }

    struct ExternalHelper {
        child: Child,
        stdin: ChildStdin,
        instance_id: String,
    }

    impl ExternalHelper {
        fn start() -> Self {
            let instance_id = new_instance_id();
            let executable = env::current_exe().unwrap();
            let mut child = Command::new(executable)
                .arg("--ignored")
                .arg("--exact")
                .arg("runtime_manager::tests::runtime_helper_entry")
                .arg("--format=terse")
                .arg("--nocapture")
                .arg("--test-threads=1")
                .env_clear()
                .env(HELPER_ID_ENV, &instance_id)
                .env(HELPER_MODE_ENV, HelperMode::Normal.as_str())
                .stdin(Stdio::piped())
                .stdout(Stdio::null())
                .stderr(Stdio::null())
                .spawn()
                .expect("unrelated synthetic process starts");
            let stdin = child.stdin.take().unwrap();
            Self {
                child,
                stdin,
                instance_id,
            }
        }

        fn assert_alive(&mut self) {
            assert!(
                self.child.try_wait().unwrap().is_none(),
                "unrelated process was terminated"
            );
        }
    }

    impl Drop for ExternalHelper {
        fn drop(&mut self) {
            let _ = writeln!(self.stdin, "{STOP_PREFIX}{}", self.instance_id);
            let _ = self.stdin.flush();
            if self.child.try_wait().ok().flatten().is_none() {
                let _ = self.child.kill();
            }
            let _ = self.child.wait();
        }
    }

    #[test]
    fn unrelated_process_survives_start_stop_and_restart() {
        let mut external = ExternalHelper::start();
        let manager = manager();

        manager.start_test().unwrap();
        manager.wait_for_state(RuntimeState::Ready, Duration::from_secs(2));
        external.assert_alive();
        manager.stop_and_wait().unwrap();
        external.assert_alive();

        manager
            .start_mode_for_test(HelperMode::CrashAfterReady)
            .unwrap();
        manager.wait_for_state(RuntimeState::Crashed, Duration::from_secs(2));
        external.assert_alive();
        manager.restart_test().unwrap();
        manager.wait_for_state(RuntimeState::Ready, Duration::from_secs(2));
        external.assert_alive();
        manager.stop_and_wait().unwrap();
        external.assert_alive();
        assert_clean(&manager);
    }

    #[test]
    fn helper_launch_arguments_are_fixed_and_shell_free() {
        let arguments = helper_arguments("123-456-1", HelperMode::Normal);
        assert_eq!(
            arguments,
            vec![
                TEST_HELPER_SWITCH.to_owned(),
                "123-456-1".to_owned(),
                "normal".to_owned()
            ]
        );
        assert!(!arguments
            .iter()
            .any(|value| { matches!(value.as_str(), "sh" | "bash" | "zsh" | "-c" | "eval") }));
        assert_eq!(HelperMode::parse("/bin/sh -c id"), None);
    }

    #[test]
    fn concurrent_start_creates_exactly_one_child() {
        let manager = Arc::new(manager());
        let barrier = Arc::new(Barrier::new(3));
        let results = Arc::new(TestMutex::new(Vec::new()));
        let mut workers = Vec::new();
        for _ in 0..2 {
            let manager = Arc::clone(&manager);
            let barrier = Arc::clone(&barrier);
            let results = Arc::clone(&results);
            workers.push(thread::spawn(move || {
                barrier.wait();
                results.lock().unwrap().push(manager.start_test());
            }));
        }
        barrier.wait();
        for worker in workers {
            worker.join().unwrap();
        }
        let results = results.lock().unwrap();
        assert_eq!(results.iter().filter(|result| result.is_ok()).count(), 1);
        assert_eq!(results.iter().filter(|result| result.is_err()).count(), 1);
        drop(results);
        manager.wait_for_state(RuntimeState::Ready, Duration::from_secs(2));
        manager.stop_and_wait().unwrap();
        assert_clean(&manager);
    }

    #[test]
    fn start_stop_race_leaves_no_child_or_supervisor() {
        let manager = Arc::new(manager());
        let barrier = Arc::new(Barrier::new(3));
        let start_manager = Arc::clone(&manager);
        let start_barrier = Arc::clone(&barrier);
        let starter = thread::spawn(move || {
            start_barrier.wait();
            start_manager.start_test()
        });
        let stop_manager = Arc::clone(&manager);
        let stop_barrier = Arc::clone(&barrier);
        let stopper = thread::spawn(move || {
            stop_barrier.wait();
            stop_manager.stop_and_wait()
        });
        barrier.wait();
        let _ = starter.join().unwrap();
        let _ = stopper.join().unwrap();
        if manager.snapshot().state.is_active() {
            manager.stop_and_wait().unwrap();
        }
        assert_clean(&manager);
    }

    #[test]
    fn restart_stop_race_is_serialized() {
        let manager = Arc::new(manager());
        manager
            .start_mode_for_test(HelperMode::CrashAfterReady)
            .unwrap();
        manager.wait_for_state(RuntimeState::Crashed, Duration::from_secs(2));

        let barrier = Arc::new(Barrier::new(3));
        let restart_manager = Arc::clone(&manager);
        let restart_barrier = Arc::clone(&barrier);
        let restarter = thread::spawn(move || {
            restart_barrier.wait();
            restart_manager.restart_test()
        });
        let stop_manager = Arc::clone(&manager);
        let stop_barrier = Arc::clone(&barrier);
        let stopper = thread::spawn(move || {
            stop_barrier.wait();
            stop_manager.stop_and_wait()
        });
        barrier.wait();
        let _ = restarter.join().unwrap();
        let _ = stopper.join().unwrap();
        if manager.snapshot().state.is_active() {
            manager.stop_and_wait().unwrap();
        }
        assert_clean(&manager);
    }

    #[test]
    fn restart_after_manual_stop_is_not_implicit_start() {
        let manager = manager();
        assert_eq!(
            manager.restart_test().unwrap_err(),
            ManagerError::InvalidState
        );
        assert_eq!(manager.snapshot().state, RuntimeState::Stopped);
    }
}
