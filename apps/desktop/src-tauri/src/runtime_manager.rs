use crate::transport::{ChildTransportConfig, TransportSession, TransportSnapshot, TransportState};
#[cfg(test)]
use std::path::{Path, PathBuf};
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
    ExitZeroBeforeReady,
    #[cfg(test)]
    CloseStdoutThenExit,
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
    #[cfg(test)]
    MissingTransport,
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
            Self::ExitZeroBeforeReady => "exit-zero-before-ready",
            #[cfg(test)]
            Self::CloseStdoutThenExit => "close-stdout-then-exit",
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
            #[cfg(test)]
            Self::MissingTransport => "missing-transport",
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
            "exit-zero-before-ready" => Self::ExitZeroBeforeReady,
            #[cfg(test)]
            "close-stdout-then-exit" => Self::CloseStdoutThenExit,
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
            #[cfg(test)]
            "missing-transport" => Self::MissingTransport,
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
    transport_snapshot: TransportSnapshot,
    transport_session: Option<Arc<TransportSession>>,
    supervisor: Option<Sender<SupervisorMessage>>,
    completion: Option<Arc<GenerationCompletion>>,
}

/// Kept alive by stop waiters after a later generation replaces `Inner.snapshot`.
struct GenerationCompletion {
    result: Mutex<Option<RuntimeSnapshot>>,
    changed: Condvar,
}

impl GenerationCompletion {
    fn new() -> Self {
        Self {
            result: Mutex::new(None),
            changed: Condvar::new(),
        }
    }

    fn finish(&self, snapshot: &RuntimeSnapshot) {
        let mut result = self
            .result
            .lock()
            .unwrap_or_else(|error| error.into_inner());
        if result.is_none() {
            *result = Some(snapshot.clone());
            self.changed.notify_all();
        }
    }
}

enum SupervisorMessage {
    Output(String),
    StdoutClosed,
    StdoutFailed,
    Stop(Sender<RuntimeSnapshot>),
}

enum StopDecision {
    Complete(RuntimeSnapshot),
    WaitForGeneration {
        runtime_instance_id: String,
        snapshot: RuntimeSnapshot,
        completion: Arc<GenerationCompletion>,
    },
}

#[cfg(test)]
#[derive(Clone)]
struct StopWaitTestHook {
    captured: Arc<std::sync::Barrier>,
    resume: Arc<std::sync::Barrier>,
}

pub struct RuntimeManager {
    shared: Arc<Shared>,
    #[cfg(test)]
    helper_executable: Option<PathBuf>,
    #[cfg(test)]
    stop_wait_test_hook: Mutex<Option<StopWaitTestHook>>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum ManagerError {
    InvalidState,
    SupervisorUnavailable,
    CommandTimeout,
    SpawnFailed,
    TransportSetupFailed,
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
            Self::TransportSetupFailed => "Não foi possível preparar o canal local autenticado.",
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
                    transport_snapshot: TransportSnapshot::disconnected(),
                    transport_session: None,
                    supervisor: None,
                    completion: None,
                }),
                changed: Condvar::new(),
                options,
            }),
            #[cfg(test)]
            helper_executable: None,
            #[cfg(test)]
            stop_wait_test_hook: Mutex::new(None),
        }
    }

    #[cfg(test)]
    fn with_test_helper_executable(executable: PathBuf) -> Self {
        let mut manager = Self::with_options(RuntimeOptions::production());
        manager.helper_executable = Some(executable);
        manager
    }

    fn snapshot(&self) -> RuntimeSnapshot {
        lock_inner(&self.shared).snapshot.clone()
    }

    fn status_json(&self) -> String {
        json_envelope(true, &self.snapshot(), None)
    }

    fn transport_status_json(&self) -> String {
        lock_inner(&self.shared).transport_snapshot.json()
    }

    fn probe_transport_now(&self) -> TransportSnapshot {
        let (instance_id, session) = {
            let mut inner = lock_inner(&self.shared);
            if inner.snapshot.state != RuntimeState::Ready {
                let instance_id = inner.snapshot.runtime_instance_id.clone();
                inner.transport_snapshot = TransportSnapshot {
                    state: TransportState::Failed,
                    runtime_instance_id: instance_id,
                    endpoint_type: Some("uds"),
                    protocol_version: None,
                    error_category: Some("runtime_not_ready"),
                };
                return inner.transport_snapshot.clone();
            }
            let Some(session) = inner.transport_session.clone() else {
                inner.transport_snapshot = TransportSnapshot {
                    state: TransportState::Failed,
                    runtime_instance_id: inner.snapshot.runtime_instance_id.clone(),
                    endpoint_type: Some("uds"),
                    protocol_version: None,
                    error_category: Some("endpoint_unavailable"),
                };
                return inner.transport_snapshot.clone();
            };
            let instance_id = inner
                .snapshot
                .runtime_instance_id
                .clone()
                .expect("ready runtime has an instance ID");
            inner.transport_snapshot = TransportSnapshot {
                state: TransportState::ProvingInstance,
                runtime_instance_id: Some(instance_id.clone()),
                endpoint_type: Some("uds"),
                protocol_version: None,
                error_category: None,
            };
            (instance_id, session)
        };
        complete_transport_probe(&self.shared, &instance_id, session);
        lock_inner(&self.shared).transport_snapshot.clone()
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
        let transport_session = TransportSession::create(&instance_id)
            .map_err(|_| ManagerError::TransportSetupFailed)?;
        let mut command = helper_command(
            &instance_id,
            mode,
            stale_instance_id,
            #[cfg(test)]
            self.helper_executable.as_deref(),
        )
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
        inner.transport_snapshot = TransportSnapshot::discovering(&instance_id);
        inner.transport_session = Some(Arc::clone(&transport_session));
        inner.supervisor = None;
        inner.completion = Some(Arc::new(GenerationCompletion::new()));

        command
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::null());

        let mut child = match command.spawn() {
            Ok(child) => child,
            Err(_) => {
                inner.snapshot.state = RuntimeState::Failed;
                inner.snapshot.failure_category = Some("spawn_failed");
                revoke_transport_locked(
                    &mut inner,
                    &instance_id,
                    TransportState::Failed,
                    Some("spawn_failed"),
                );
                transition_log(RuntimeState::Starting, RuntimeState::Failed, &instance_id);
                complete_current_generation(&inner);
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
        let mut stdin = child.stdin.take();
        let init_written = stdin
            .as_mut()
            .is_some_and(|pipe| transport_session.write_child_init(pipe).is_ok());
        if !init_written {
            drop(inner);
            let _ = child.kill();
            let status = child.wait().ok();
            finish_start_failure(&self.shared, &instance_id, "transport_init_failed", status);
            return Err(ManagerError::TransportSetupFailed);
        }
        let (sender, receiver) = mpsc::channel();
        inner.supervisor = Some(sender.clone());
        let reader_sender = sender.clone();
        thread::spawn(move || read_child_stdout(stdout, reader_sender));

        let shared = Arc::clone(&self.shared);
        let options = self.shared.options;
        let worker_instance_id = instance_id.clone();
        thread::spawn(move || {
            supervise_child(
                shared,
                worker_instance_id,
                child,
                stdin,
                receiver,
                options,
                transport_session,
            )
        });

        self.shared.changed.notify_all();
        Ok(inner.snapshot.clone())
    }

    /// Linearizes the stop target under the state lock and queues STOP before releasing it.
    fn begin_stop(&self) -> Result<StopDecision, ManagerError> {
        let mut inner = lock_inner(&self.shared);
        let snapshot = inner.snapshot.clone();
        match snapshot.state {
            RuntimeState::Stopped => Ok(StopDecision::Complete(snapshot)),
            RuntimeState::Failed | RuntimeState::Crashed => {
                let instance_id = snapshot.runtime_instance_id.as_deref().unwrap_or_default();
                if transition_locked(&mut inner, RuntimeState::Stopped, instance_id) {
                    inner.supervisor = None;
                    revoke_transport_locked(
                        &mut inner,
                        instance_id,
                        TransportState::Disconnected,
                        None,
                    );
                }
                self.shared.changed.notify_all();
                Ok(StopDecision::Complete(inner.snapshot.clone()))
            }
            RuntimeState::Stopping => Ok(StopDecision::WaitForGeneration {
                runtime_instance_id: snapshot
                    .runtime_instance_id
                    .clone()
                    .ok_or(ManagerError::SupervisorUnavailable)?,
                snapshot,
                completion: inner
                    .completion
                    .clone()
                    .ok_or(ManagerError::SupervisorUnavailable)?,
            }),
            RuntimeState::Starting | RuntimeState::Ready => {
                let runtime_instance_id = snapshot
                    .runtime_instance_id
                    .clone()
                    .ok_or(ManagerError::SupervisorUnavailable)?;
                let sender = inner
                    .supervisor
                    .clone()
                    .ok_or(ManagerError::SupervisorUnavailable)?;
                let (reply_tx, _reply_rx) = mpsc::channel();
                if sender.send(SupervisorMessage::Stop(reply_tx)).is_err() {
                    if inner.snapshot.state.is_terminal() {
                        return Ok(StopDecision::Complete(inner.snapshot.clone()));
                    }
                    return Err(ManagerError::SupervisorUnavailable);
                }
                if snapshot.state == RuntimeState::Starting {
                    if let Some(session) = inner.transport_session.as_ref() {
                        session.deactivate();
                    }
                    inner.transport_snapshot = TransportSnapshot {
                        state: TransportState::Disconnected,
                        runtime_instance_id: Some(runtime_instance_id.clone()),
                        endpoint_type: Some("uds"),
                        protocol_version: None,
                        error_category: None,
                    };
                } else {
                    revoke_transport_locked(
                        &mut inner,
                        &runtime_instance_id,
                        TransportState::Disconnected,
                        None,
                    );
                }
                Ok(StopDecision::WaitForGeneration {
                    runtime_instance_id,
                    snapshot,
                    completion: inner
                        .completion
                        .clone()
                        .ok_or(ManagerError::SupervisorUnavailable)?,
                })
            }
        }
    }

    /// Requests a controlled stop and returns immediately. The supervisor owns and reaps the child.
    fn request_stop(&self) -> Result<RuntimeSnapshot, ManagerError> {
        match self.begin_stop()? {
            StopDecision::Complete(snapshot) | StopDecision::WaitForGeneration { snapshot, .. } => {
                Ok(snapshot)
            }
        }
    }

    /// Used during normal application exit and in lifecycle tests; waits until the child is reaped.
    pub(crate) fn stop_and_wait(&self) -> Result<RuntimeSnapshot, ManagerError> {
        let decision = self.begin_stop()?;
        #[cfg(test)]
        self.pause_stop_wait_for_test();

        match decision {
            StopDecision::Complete(snapshot) => Ok(snapshot),
            StopDecision::WaitForGeneration {
                runtime_instance_id,
                completion,
                ..
            } => self.wait_for_generation(&runtime_instance_id, &completion),
        }
    }

    fn wait_for_generation(
        &self,
        runtime_instance_id: &str,
        completion: &GenerationCompletion,
    ) -> Result<RuntimeSnapshot, ManagerError> {
        let deadline = Instant::now() + self.shared.options.command_timeout;
        let mut result = completion
            .result
            .lock()
            .unwrap_or_else(|error| error.into_inner());
        loop {
            if let Some(snapshot) = result.as_ref() {
                debug_assert_eq!(
                    snapshot.runtime_instance_id.as_deref(),
                    Some(runtime_instance_id)
                );
                return Ok(snapshot.clone());
            }
            let now = Instant::now();
            if now >= deadline {
                return Err(ManagerError::CommandTimeout);
            }
            let remaining = deadline.saturating_duration_since(now);
            let (guard, wait_result) = completion
                .changed
                .wait_timeout(result, remaining)
                .unwrap_or_else(|error| error.into_inner());
            let timed_out = wait_result.timed_out();
            result = guard;
            if timed_out && result.is_none() {
                return Err(ManagerError::CommandTimeout);
            }
        }
    }

    #[cfg(test)]
    fn set_stop_wait_test_hook(&self, hook: Option<StopWaitTestHook>) {
        *self
            .stop_wait_test_hook
            .lock()
            .unwrap_or_else(|error| error.into_inner()) = hook;
    }

    #[cfg(test)]
    fn pause_stop_wait_for_test(&self) {
        let hook = self
            .stop_wait_test_hook
            .lock()
            .unwrap_or_else(|error| error.into_inner())
            .clone();
        if let Some(hook) = hook {
            hook.captured.wait();
            hook.resume.wait();
        }
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
    fn wait_for_transport_state(
        &self,
        target: TransportState,
        timeout: Duration,
    ) -> TransportSnapshot {
        let deadline = Instant::now() + timeout;
        let mut inner = lock_inner(&self.shared);
        loop {
            if inner.transport_snapshot.state == target {
                return inner.transport_snapshot.clone();
            }
            let now = Instant::now();
            assert!(
                now < deadline,
                "timeout waiting for {target:?}; current={:?}",
                inner.transport_snapshot
            );
            let (guard, result) = self
                .shared
                .changed
                .wait_timeout(inner, deadline.saturating_duration_since(now))
                .unwrap_or_else(|error| error.into_inner());
            inner = guard;
            assert!(
                !result.timed_out() || inner.transport_snapshot.state == target,
                "timeout waiting for {target:?}; current={:?}",
                inner.transport_snapshot
            );
        }
    }

    #[cfg(test)]
    fn transport_session_for_test(&self) -> Arc<TransportSession> {
        lock_inner(&self.shared)
            .transport_session
            .clone()
            .expect("active generation has a transport session")
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

// Called with `Inner` locked, before a newer generation can replace its snapshot.
fn complete_current_generation(inner: &Inner) {
    if let Some(completion) = &inner.completion {
        completion.finish(&inner.snapshot);
    }
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

fn complete_transport_probe(shared: &Shared, instance_id: &str, session: Arc<TransportSession>) {
    let result = session.probe();
    let mut inner = lock_inner(shared);
    if inner.snapshot.runtime_instance_id.as_deref() != Some(instance_id)
        || inner.snapshot.state != RuntimeState::Ready
        || !inner
            .transport_session
            .as_ref()
            .is_some_and(|current| Arc::ptr_eq(current, &session))
    {
        return;
    }
    match result {
        Ok(()) => {
            inner.transport_snapshot = TransportSnapshot {
                state: TransportState::Ready,
                runtime_instance_id: Some(instance_id.to_owned()),
                endpoint_type: Some("uds"),
                protocol_version: Some("1".to_owned()),
                error_category: None,
            };
            eprintln!(
                "transport ready instance_id={instance_id} endpoint_type=uds protocol_version=1"
            );
        }
        Err(error) => {
            inner.transport_snapshot = TransportSnapshot {
                state: if error.incompatible() {
                    TransportState::Incompatible
                } else {
                    TransportState::Failed
                },
                runtime_instance_id: Some(instance_id.to_owned()),
                endpoint_type: Some("uds"),
                protocol_version: None,
                error_category: Some(error.category()),
            };
            eprintln!(
                "transport failed instance_id={instance_id} endpoint_type=uds category={}",
                error.category()
            );
        }
    }
    shared.changed.notify_all();
}

fn revoke_transport_locked(
    inner: &mut Inner,
    instance_id: &str,
    state: TransportState,
    error_category: Option<&'static str>,
) {
    if inner.snapshot.runtime_instance_id.as_deref() != Some(instance_id) {
        return;
    }
    if let Some(session) = inner.transport_session.take() {
        session.revoke();
    }
    inner.transport_snapshot = TransportSnapshot {
        state,
        runtime_instance_id: Some(instance_id.to_owned()),
        endpoint_type: Some("uds"),
        protocol_version: None,
        error_category,
    };
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
    revoke_transport_locked(
        &mut inner,
        instance_id,
        if target == RuntimeState::Stopped {
            TransportState::Disconnected
        } else {
            TransportState::Failed
        },
        Some("runtime_exited"),
    );
    inner.supervisor = None;
    complete_current_generation(&inner);
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
    revoke_transport_locked(
        &mut inner,
        instance_id,
        TransportState::Failed,
        Some(category),
    );
    inner.supervisor = None;
    complete_current_generation(&inner);
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
    revoke_transport_locked(
        &mut inner,
        instance_id,
        TransportState::Failed,
        Some(category),
    );
    inner.supervisor = None;
    complete_current_generation(&inner);
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
        revoke_transport_locked(&mut inner, instance_id, TransportState::Disconnected, None);
        inner.supervisor = None;
        complete_current_generation(&inner);
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
    transport_session: Arc<TransportSession>,
) {
    let startup_deadline = Instant::now() + options.startup_timeout;
    let mut readiness_channel_closed = false;
    loop {
        let state = lock_inner(&shared).snapshot.state;
        if state == RuntimeState::Starting {
            // EOF can precede process exit. Resolve the process outcome before
            // classifying the closed readiness channel at the startup deadline.
            if readiness_channel_closed {
                if let Ok(Some(status)) = child.try_wait() {
                    finish_child_exit(&shared, &instance_id, status);
                    return;
                }
            }
            if Instant::now() >= startup_deadline {
                let _ = child.kill();
                let status = child.wait().ok();
                let category = if readiness_channel_closed {
                    "readiness_channel_closed"
                } else {
                    "startup_timeout"
                };
                finish_start_failure(&shared, &instance_id, category, status);
                return;
            }
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
                    {
                        let mut inner = lock_inner(&shared);
                        if inner.snapshot.runtime_instance_id.as_deref()
                            == Some(instance_id.as_str())
                            && inner.snapshot.state == RuntimeState::Ready
                        {
                            inner.transport_snapshot = TransportSnapshot {
                                state: TransportState::ProvingInstance,
                                runtime_instance_id: Some(instance_id.clone()),
                                endpoint_type: Some("uds"),
                                protocol_version: None,
                                error_category: None,
                            };
                        }
                    }
                    let probe_shared = Arc::clone(&shared);
                    let probe_instance = instance_id.clone();
                    let probe_session = Arc::clone(&transport_session);
                    thread::spawn(move || {
                        complete_transport_probe(&probe_shared, &probe_instance, probe_session)
                    });
                }
            }
            SupervisorMessage::StdoutClosed => {
                let state = lock_inner(&shared).snapshot.state;
                if state == RuntimeState::Starting {
                    readiness_channel_closed = true;
                    // Keep accepting STOP while process exit and EOF are aggregated.
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
    #[cfg(test)] test_executable: Option<&Path>,
) -> io::Result<Command> {
    #[cfg(test)]
    {
        if let Some(executable) = test_executable {
            let mut command = Command::new(executable);
            command.env_clear();
            command.args(helper_arguments(instance_id, mode));
            return Ok(command);
        }

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
    let transport = match crate::transport::read_child_init(&mut input, instance_id) {
        Ok(config) => config,
        Err(_) => return 44,
    };
    let listener = if mode == HelperMode::Normal {
        match transport.bind() {
            Ok(listener) => Some(listener),
            Err(_) => return 45,
        }
    } else {
        None
    };

    match mode {
        HelperMode::CrashBeforeReady => return 41,
        HelperMode::ExitZeroBeforeReady => return 0,
        HelperMode::CloseStdoutThenExit => {
            drop(output);
            close_stdout_for_helper();
            return 47;
        }
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

    if let Some(listener) = listener {
        return serve_transport_until_stop(transport, listener, input, instance_id);
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
    let mut input = BufReader::new(io::stdin());
    let transport = match crate::transport::read_child_init(&mut input, instance_id) {
        Ok(config) => config,
        Err(_) => return 44,
    };
    let listener = match transport.bind() {
        Ok(listener) => listener,
        Err(_) => return 45,
    };
    if writeln!(output, "{READY_PREFIX}{instance_id}")
        .and_then(|_| output.flush())
        .is_err()
    {
        return 43;
    }
    drop(output);

    if !wait_for_ack(&mut input, instance_id) {
        return 0;
    }
    serve_transport_until_stop(transport, listener, input, instance_id)
}

fn serve_transport_until_stop(
    transport: ChildTransportConfig,
    listener: std::os::unix::net::UnixListener,
    input: BufReader<io::Stdin>,
    instance_id: &str,
) -> i32 {
    let (stop_sender, stop_receiver) = mpsc::channel();
    let expected_stop = format!("{STOP_PREFIX}{instance_id}");
    thread::spawn(move || {
        let mut input = input;
        let mut line = String::new();
        while input.read_line(&mut line).unwrap_or(0) > 0 {
            if line.trim_end_matches(['\r', '\n']) == expected_stop {
                let _ = stop_sender.send(());
                return;
            }
            line.clear();
        }
    });
    loop {
        if stop_receiver.try_recv().is_ok() {
            return 0;
        }
        match transport.serve_one(&listener, Duration::from_millis(10)) {
            Ok(_) => {}
            Err(_) => return 46,
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
pub fn runtime_transport_status(manager: tauri::State<'_, RuntimeManager>) -> String {
    manager.transport_status_json()
}

#[tauri::command]
pub fn runtime_transport_probe(manager: tauri::State<'_, RuntimeManager>) -> String {
    manager.probe_transport_now().json()
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
    #[path = "runtime_manager_linearization_tests.rs"]
    mod linearization_tests;
    #[path = "runtime_manager_preready_tests.rs"]
    mod preready_tests;

    use super::*;
    use std::{
        io::Write,
        path::Path,
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
        assert!(
            lock_inner(&manager.shared).transport_session.is_none(),
            "transport session still belongs to a terminal runtime: {snapshot:?}"
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
        let transport =
            manager.wait_for_transport_state(TransportState::Ready, Duration::from_secs(2));
        assert_eq!(transport.runtime_instance_id, ready.runtime_instance_id);
        assert_eq!(transport.endpoint_type, Some("uds"));
        assert_eq!(transport.protocol_version.as_deref(), Some("1"));
        let transport_session = manager.transport_session_for_test();
        let stopped = manager.stop_and_wait().unwrap();
        assert_eq!(stopped.state, RuntimeState::Stopped);
        assert_eq!(
            manager.transport_status_json().contains("DISCONNECTED"),
            true
        );
        assert!(transport_session.is_clean_for_test());
        assert_clean(&manager);
    }

    #[test]
    fn separate_managers_and_stale_generations_cannot_cross_authenticate() {
        let manager_a = manager();
        let manager_b = manager();
        manager_a.start_test().unwrap();
        manager_b.start_test().unwrap();
        manager_a.wait_for_state(RuntimeState::Ready, Duration::from_secs(2));
        manager_b.wait_for_state(RuntimeState::Ready, Duration::from_secs(2));
        manager_a.wait_for_transport_state(TransportState::Ready, Duration::from_secs(2));
        manager_b.wait_for_transport_state(TransportState::Ready, Duration::from_secs(2));

        let session_a = manager_a.transport_session_for_test();
        let session_b = manager_b.transport_session_for_test();
        assert_eq!(
            session_a.probe_other_session_for_test(&session_b),
            Err(crate::transport::TransportError::ProofRejected)
        );
        assert_eq!(
            session_b.probe_other_session_for_test(&session_a),
            Err(crate::transport::TransportError::ProofRejected)
        );

        manager_a.stop_and_wait().unwrap();
        assert_eq!(
            session_a.probe(),
            Err(crate::transport::TransportError::Inactive)
        );
        assert!(session_a.is_clean_for_test());
        assert_eq!(manager_b.transport_status_json().contains("READY"), true);

        let generation_b = manager_a.start_test().unwrap();
        manager_a.wait_for_state(RuntimeState::Ready, Duration::from_secs(2));
        manager_a.wait_for_transport_state(TransportState::Ready, Duration::from_secs(2));
        let session_generation_b = manager_a.transport_session_for_test();
        assert_ne!(
            session_generation_b.instance_id_for_test(),
            session_a.instance_id_for_test()
        );
        assert_eq!(
            session_a.probe_other_session_for_test(&session_generation_b),
            Err(crate::transport::TransportError::Inactive)
        );
        assert_ne!(
            generation_b.runtime_instance_id.as_deref(),
            Some(session_a.instance_id_for_test())
        );
        manager_a.stop_and_wait().unwrap();
        manager_b.stop_and_wait().unwrap();
        assert_clean(&manager_a);
        assert_clean(&manager_b);
    }

    #[test]
    fn process_ready_does_not_imply_transport_ready() {
        let manager = manager();
        manager
            .start_mode_for_test(HelperMode::MissingTransport)
            .unwrap();
        let runtime = manager.wait_for_state(RuntimeState::Ready, Duration::from_secs(2));
        let transport =
            manager.wait_for_transport_state(TransportState::Failed, Duration::from_secs(2));
        assert_eq!(runtime.state, RuntimeState::Ready);
        assert_eq!(transport.runtime_instance_id, runtime.runtime_instance_id);
        assert_eq!(transport.error_category, Some("endpoint_unavailable"));
        assert_eq!(manager.snapshot().state, RuntimeState::Ready);
        assert_eq!(
            manager.stop_and_wait().unwrap().state,
            RuntimeState::Stopped
        );
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

    #[test]
    #[ignore = "requires npm run tauri -- build --no-bundle"]
    fn release_tauri_binary_is_spawned_and_reaped() {
        let executable = Path::new(env!("CARGO_MANIFEST_DIR")).join("target/release/desktop");
        assert!(
            executable.is_file(),
            "release binary missing: {executable:?}"
        );

        let manager = RuntimeManager::with_test_helper_executable(executable);
        let started = manager.start_test().unwrap();
        assert_eq!(started.state, RuntimeState::Starting);
        let ready = manager.wait_for_state(RuntimeState::Ready, Duration::from_secs(8));
        assert_eq!(ready.runtime_instance_id, started.runtime_instance_id);
        let transport =
            manager.wait_for_transport_state(TransportState::Ready, Duration::from_secs(8));
        assert_eq!(transport.runtime_instance_id, ready.runtime_instance_id);
        assert_eq!(transport.protocol_version.as_deref(), Some("1"));
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
        transport_session: Arc<TransportSession>,
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
            let mut stdin = child.stdin.take().unwrap();
            let transport_session = TransportSession::create(&instance_id).unwrap();
            transport_session.write_child_init(&mut stdin).unwrap();
            Self {
                child,
                stdin,
                instance_id,
                transport_session,
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
            self.transport_session.revoke();
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
        let start_result = starter.join().unwrap();
        let stop_result = stopper.join().unwrap();
        assert!(start_result.is_ok(), "start result: {start_result:?}");
        assert!(stop_result.is_ok(), "stop result: {stop_result:?}");
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
