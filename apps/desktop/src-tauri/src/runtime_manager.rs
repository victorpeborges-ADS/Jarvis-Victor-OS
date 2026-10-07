use crate::transport::{
    ChildTransportConfig, TransportError, TransportSession, TransportSnapshot, TransportState,
};
use std::{
    env,
    io::{self, BufRead, BufReader, Write},
    path::{Path, PathBuf},
    process::{Child, Command, ExitStatus, Stdio},
    sync::{
        atomic::{AtomicBool, AtomicU64, Ordering},
        mpsc::{self, Receiver, RecvTimeoutError, Sender},
        Arc, Condvar, Mutex, MutexGuard,
    },
    thread,
    time::{Duration, Instant, SystemTime, UNIX_EPOCH},
};

const READY_PREFIX: &str = "JARVIS_RUNTIME_READY ";
const ACK_PREFIX: &str = "JARVIS_RUNTIME_ACK ";
const STOP_PREFIX: &str = "JARVIS_RUNTIME_STOP ";
const SUPERVISOR_LOST_EXIT: i32 = 48;
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
    #[cfg(test)]
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
    g5_session: Option<G5Session>,
    g5_grant: Option<G5Grant>,
    supervisor: Option<Sender<SupervisorMessage>>,
    completion: Option<Arc<GenerationCompletion>>,
}

struct G5Session {
    runtime_instance_id: String,
    token: SecretText,
    csrf_token: SecretText,
    expires_at: String,
    expires_at_unix_microseconds: u64,
}

struct G5Grant {
    session_token: SecretText,
    id: String,
    domain_id: String,
    expires_at: String,
    expires_at_unix_microseconds: u64,
}

struct SecretText(String);

impl SecretText {
    fn new(value: String) -> Self {
        Self(value)
    }

    fn as_str(&self) -> &str {
        &self.0
    }
}

impl Drop for SecretText {
    fn drop(&mut self) {
        // NUL bytes are valid UTF-8, so replacing the initialized bytes keeps
        // String's invariant while clearing secret material before release.
        unsafe { self.0.as_mut_vec().fill(0) };
    }
}

struct SecretBytes(Vec<u8>);

impl SecretBytes {
    fn new(value: Vec<u8>) -> Self {
        Self(value)
    }

    fn as_slice(&self) -> &[u8] {
        &self.0
    }
}

impl Drop for SecretBytes {
    fn drop(&mut self) {
        self.0.fill(0);
        std::hint::black_box(&self.0);
    }
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
    TransportVerified(Result<(), TransportError>),
    StdoutClosed,
    StdoutFailed,
    Stop(Sender<RuntimeSnapshot>),
    #[cfg(any(test, feature = "mac003-production-supervisor-test"))]
    CloseControl(Sender<()>),
    #[cfg(feature = "mac003-production-supervisor-test")]
    CrashChildForIntegration(Sender<bool>),
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum ControlSignal {
    Acknowledged,
    Stop,
    SupervisorLost,
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
    g5_operation: Mutex<()>,
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
            Self::SpawnFailed => "Não foi possível iniciar o backend local.",
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
                    g5_session: None,
                    g5_grant: None,
                    supervisor: None,
                    completion: None,
                }),
                changed: Condvar::new(),
                options,
            }),
            g5_operation: Mutex::new(()),
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

    fn g5_session_status_json(&self) -> String {
        let mut inner = lock_inner(&self.shared);
        expire_cached_authorization(&mut inner);
        let session = inner.g5_session.as_ref().filter(|session| {
            inner.snapshot.runtime_instance_id.as_deref()
                == Some(session.runtime_instance_id.as_str())
                && inner.snapshot.state == RuntimeState::Ready
        });
        let grant = if session.is_some() {
            inner.g5_grant.as_ref()
        } else {
            None
        };
        format!(
            "{{\"ok\":true,\"session_active\":{},\"session_expires_at\":{},\"grant_active\":{},\"grant_domain_id\":{},\"grant_expires_at\":{}}}",
            session.is_some(),
            json_optional_string(session.map(|value| value.expires_at.as_str())),
            grant.is_some(),
            json_optional_string(grant.map(|value| value.domain_id.as_str())),
            json_optional_string(grant.map(|value| value.expires_at.as_str())),
        )
    }

    fn active_transport_for_g5(&self) -> Result<(String, Arc<TransportSession>), &'static str> {
        let inner = lock_inner(&self.shared);
        if inner.snapshot.state != RuntimeState::Ready
            || inner.transport_snapshot.state != TransportState::Ready
        {
            return Err("runtime_unavailable");
        }
        let instance_id = inner
            .snapshot
            .runtime_instance_id
            .clone()
            .ok_or("runtime_unavailable")?;
        let session = inner
            .transport_session
            .clone()
            .ok_or("runtime_unavailable")?;
        Ok((instance_id, session))
    }

    fn g5_session_open(&self, passphrase: String) -> String {
        let _operation = self
            .g5_operation
            .lock()
            .unwrap_or_else(|error| error.into_inner());
        let passphrase = SecretText::new(passphrase);
        if passphrase.as_str().len() < 12 || passphrase.as_str().len() > 128 {
            return g5_error_json("credential_rejected");
        }
        {
            let mut inner = lock_inner(&self.shared);
            expire_cached_authorization(&mut inner);
            if inner.g5_session.is_some() {
                return g5_error_json("session_already_open");
            }
        }
        let (instance_id, transport) = match self.active_transport_for_g5() {
            Ok(value) => value,
            Err(error) => return g5_error_json(error),
        };
        let body = SecretBytes::new(encode_application_fields(&[(
            "passphrase",
            passphrase.as_str(),
        )]));
        let response = match transport.call_g5_application("/v1/app/session/open", body.as_slice())
        {
            Ok(value) => SecretBytes::new(value),
            Err(_) => return g5_error_json("transport_failure"),
        };
        // The form body contains the user-entered credential and is cleared
        // before parsing the response.
        drop(body);
        let mut fields = match parse_application_response(response.as_slice()) {
            Ok(value) => value,
            Err(()) => return g5_error_json("protocol_failure"),
        };
        if app_response_error(&fields).is_some() {
            let error = app_response_error(&fields).unwrap_or("operation_failed");
            return g5_error_json(error);
        }
        if !app_fields_match(
            &fields,
            &[
                "ok",
                "principal",
                "session_token",
                "csrf_token",
                "expires_at_epoch_us",
                "expires_at",
            ],
        ) || app_field(&fields, "ok") != Some("true")
            || app_field(&fields, "principal") != Some("owner")
        {
            return g5_error_json("protocol_failure");
        }
        let token = match take_app_secret(&mut fields, "session_token") {
            Some(value) if is_session_token(value.as_str()) => value,
            _ => return g5_error_json("protocol_failure"),
        };
        let csrf_token = match take_app_secret(&mut fields, "csrf_token") {
            Some(value) if is_session_token(value.as_str()) => value,
            _ => return g5_error_json("protocol_failure"),
        };
        let expires_at = match take_app_secret(&mut fields, "expires_at") {
            Some(value) if !value.as_str().is_empty() && value.as_str().len() <= 64 => {
                value.as_str().to_owned()
            }
            _ => return g5_error_json("protocol_failure"),
        };
        let expires_at_unix_microseconds = match take_app_secret(&mut fields, "expires_at_epoch_us")
            .and_then(|value| value.as_str().parse::<u64>().ok())
        {
            Some(value) if value > unix_time_microseconds() => value,
            _ => return g5_error_json("protocol_failure"),
        };
        let mut inner = lock_inner(&self.shared);
        if inner.snapshot.runtime_instance_id.as_deref() != Some(instance_id.as_str())
            || inner.snapshot.state != RuntimeState::Ready
            || inner.transport_snapshot.state != TransportState::Ready
            || !inner
                .transport_session
                .as_ref()
                .is_some_and(|current| Arc::ptr_eq(current, &transport))
        {
            return g5_error_json("stale_generation");
        }
        inner.g5_session = Some(G5Session {
            runtime_instance_id: instance_id,
            token,
            csrf_token,
            expires_at: expires_at.clone(),
            expires_at_unix_microseconds,
        });
        format!(
            "{{\"ok\":true,\"session_active\":true,\"expires_at\":{}}}",
            json_string(&expires_at)
        )
    }

    fn g5_mission_read_grant_create(&self) -> String {
        let _operation = self
            .g5_operation
            .lock()
            .unwrap_or_else(|error| error.into_inner());
        {
            let mut inner = lock_inner(&self.shared);
            expire_cached_authorization(&mut inner);
            if inner.g5_grant.is_some() {
                return g5_error_json("grant_conflict");
            }
        }
        let (instance_id, transport, token, csrf_token) = match self.g5_credentials_for_active() {
            Ok(value) => value,
            Err(error) => return g5_error_json(error),
        };
        let body = SecretBytes::new(encode_application_fields(&[
            ("session_token", token.as_str()),
            ("csrf_token", csrf_token.as_str()),
            ("domain_id", "dom_synthetic_a"),
        ]));
        let response =
            match transport.call_g5_application("/v1/app/grants/mission-read", body.as_slice()) {
                Ok(value) => SecretBytes::new(value),
                Err(_) => return g5_error_json("transport_failure"),
            };
        let mut fields = match parse_application_response(response.as_slice()) {
            Ok(value) => value,
            Err(()) => return g5_error_json("protocol_failure"),
        };
        if let Some(error) = app_response_error(&fields) {
            clear_cached_authorization_after_rejection(
                &self.shared,
                &instance_id,
                &transport,
                token.as_str(),
                error,
            );
            return g5_error_json(error);
        }
        if !app_fields_match(
            &fields,
            &[
                "ok",
                "grant_id",
                "domain_id",
                "expires_at_epoch_us",
                "expires_at",
            ],
        ) || app_field(&fields, "ok") != Some("true")
            || app_field(&fields, "domain_id") != Some("dom_synthetic_a")
        {
            return g5_error_json("protocol_failure");
        }
        let grant_id = match take_app_secret(&mut fields, "grant_id") {
            Some(value) if is_hex_identifier(value.as_str()) => value.as_str().to_owned(),
            _ => return g5_error_json("protocol_failure"),
        };
        let expires_at = match take_app_secret(&mut fields, "expires_at") {
            Some(value) if !value.as_str().is_empty() && value.as_str().len() <= 64 => {
                value.as_str().to_owned()
            }
            _ => return g5_error_json("protocol_failure"),
        };
        let expires_at_unix_microseconds = match take_app_secret(&mut fields, "expires_at_epoch_us")
            .and_then(|value| value.as_str().parse::<u64>().ok())
        {
            Some(value) if value > unix_time_microseconds() => value,
            _ => return g5_error_json("protocol_failure"),
        };
        let mut inner = lock_inner(&self.shared);
        if !g5_generation_matches(&inner, &instance_id, &transport)
            || inner
                .g5_session
                .as_ref()
                .is_none_or(|session| session.token.as_str() != token.as_str())
        {
            return g5_error_json("stale_generation");
        }
        inner.g5_grant = Some(G5Grant {
            session_token: SecretText::new(token.as_str().to_owned()),
            id: grant_id,
            domain_id: "dom_synthetic_a".to_owned(),
            expires_at: expires_at.clone(),
            expires_at_unix_microseconds,
        });
        format!(
            "{{\"ok\":true,\"grant_active\":true,\"domain_id\":\"dom_synthetic_a\",\"expires_at\":{}}}",
            json_string(&expires_at)
        )
    }

    fn g5_mission_read_grant_revoke(&self) -> String {
        let _operation = self
            .g5_operation
            .lock()
            .unwrap_or_else(|error| error.into_inner());
        self.g5_mission_read_grant_revoke_locked()
    }

    fn g5_mission_read_grant_revoke_locked(&self) -> String {
        let (instance_id, transport, token, csrf_token, grant_id) = {
            let mut inner = lock_inner(&self.shared);
            expire_cached_authorization(&mut inner);
            let Some(session) = inner.g5_session.as_ref() else {
                return g5_error_json("session_required");
            };
            let Some(grant) = inner.g5_grant.as_ref() else {
                return "{\"ok\":true,\"grant_active\":false}".to_owned();
            };
            if inner.snapshot.state != RuntimeState::Ready
                || inner.transport_snapshot.state != TransportState::Ready
                || inner.snapshot.runtime_instance_id.as_deref()
                    != Some(session.runtime_instance_id.as_str())
            {
                return g5_error_json("runtime_unavailable");
            }
            let Some(transport) = inner.transport_session.clone() else {
                return g5_error_json("runtime_unavailable");
            };
            (
                session.runtime_instance_id.clone(),
                transport,
                SecretText::new(session.token.as_str().to_owned()),
                SecretText::new(session.csrf_token.as_str().to_owned()),
                grant.id.clone(),
            )
        };
        let body = SecretBytes::new(encode_application_fields(&[
            ("session_token", token.as_str()),
            ("csrf_token", csrf_token.as_str()),
            ("grant_id", &grant_id),
        ]));
        let response = match transport
            .call_g5_application("/v1/app/grants/mission-read/revoke", body.as_slice())
        {
            Ok(value) => SecretBytes::new(value),
            Err(_) => return g5_error_json("transport_failure"),
        };
        let fields = match parse_application_response(response.as_slice()) {
            Ok(value) => value,
            Err(()) => return g5_error_json("protocol_failure"),
        };
        if let Some(error) = app_response_error(&fields) {
            clear_cached_authorization_after_rejection(
                &self.shared,
                &instance_id,
                &transport,
                token.as_str(),
                error,
            );
            return g5_error_json(error);
        }
        if !app_fields_match(&fields, &["ok", "revoked"])
            || app_field(&fields, "ok") != Some("true")
            || app_field(&fields, "revoked") != Some("true")
        {
            return g5_error_json("protocol_failure");
        }
        let mut inner = lock_inner(&self.shared);
        if !g5_generation_matches(&inner, &instance_id, &transport)
            || inner
                .g5_session
                .as_ref()
                .is_none_or(|session| session.token.as_str() != token.as_str())
        {
            return g5_error_json("stale_generation");
        }
        if inner
            .g5_grant
            .as_ref()
            .is_some_and(|grant| grant.id == grant_id)
        {
            inner.g5_grant = None;
        }
        "{\"ok\":true,\"grant_active\":false}".to_owned()
    }

    fn g5_session_close(&self) -> String {
        let _operation = self
            .g5_operation
            .lock()
            .unwrap_or_else(|error| error.into_inner());
        {
            let mut inner = lock_inner(&self.shared);
            expire_cached_authorization(&mut inner);
        }
        let (instance_id, transport, token, csrf_token) = match self.g5_credentials_for_active() {
            Ok(value) => value,
            Err(error) => return g5_error_json(error),
        };
        let body = SecretBytes::new(encode_application_fields(&[
            ("session_token", token.as_str()),
            ("csrf_token", csrf_token.as_str()),
        ]));
        let response = match transport.call_g5_application("/v1/app/session/close", body.as_slice())
        {
            Ok(value) => SecretBytes::new(value),
            Err(_) => return g5_error_json("transport_failure"),
        };
        let fields = match parse_application_response(response.as_slice()) {
            Ok(value) => value,
            Err(()) => return g5_error_json("protocol_failure"),
        };
        if let Some(error) = app_response_error(&fields) {
            clear_cached_authorization_after_rejection(
                &self.shared,
                &instance_id,
                &transport,
                token.as_str(),
                error,
            );
            return g5_error_json(error);
        }
        if !app_fields_match(&fields, &["ok", "closed"])
            || app_field(&fields, "ok") != Some("true")
            || app_field(&fields, "closed") != Some("true")
        {
            return g5_error_json("protocol_failure");
        }
        let mut inner = lock_inner(&self.shared);
        if !g5_generation_matches(&inner, &instance_id, &transport)
            || inner
                .g5_session
                .as_ref()
                .is_none_or(|session| session.token.as_str() != token.as_str())
        {
            return g5_error_json("stale_generation");
        }
        inner.g5_session = None;
        inner.g5_grant = None;
        "{\"ok\":true,\"session_active\":false,\"grant_active\":false}".to_owned()
    }

    fn g5_missions_list(&self) -> String {
        let _operation = self
            .g5_operation
            .lock()
            .unwrap_or_else(|error| error.into_inner());
        let (instance_id, transport, token, _csrf_token) = match self.g5_credentials_for_active() {
            Ok(value) => value,
            Err(error) => return g5_error_json(error),
        };
        if lock_inner(&self.shared).g5_grant.is_none() {
            return g5_error_json("grant_required");
        }
        let body = SecretBytes::new(encode_application_fields(&[
            ("session_token", token.as_str()),
            ("domain_id", "dom_synthetic_a"),
        ]));
        let response = match transport.call_g5_application("/v1/app/missions/list", body.as_slice())
        {
            Ok(value) => SecretBytes::new(value),
            Err(_) => return g5_error_json("transport_failure"),
        };
        let mut fields = match parse_application_response(response.as_slice()) {
            Ok(value) => value,
            Err(()) => return g5_error_json("protocol_failure"),
        };
        if let Some(error) = app_response_error(&fields) {
            clear_cached_authorization_after_rejection(
                &self.shared,
                &instance_id,
                &transport,
                token.as_str(),
                error,
            );
            return g5_error_json(error);
        }
        let count = app_field(&fields, "count");
        let expected = if count == Some("0") {
            &["ok", "dataset", "count"][..]
        } else if count == Some("1") {
            &[
                "ok",
                "dataset",
                "count",
                "mission_id",
                "title",
                "domain_id",
                "status",
                "revision",
            ][..]
        } else {
            return g5_error_json("protocol_failure");
        };
        if !app_fields_match(&fields, expected)
            || app_field(&fields, "ok") != Some("true")
            || app_field(&fields, "dataset") != Some("api_synthetic")
        {
            return g5_error_json("protocol_failure");
        }
        let result = if count == Some("0") {
            "{\"ok\":true,\"dataset\":\"api_synthetic\",\"items\":[]}".to_owned()
        } else {
            let mission_id = take_app_secret(&mut fields, "mission_id").unwrap();
            let title = take_app_secret(&mut fields, "title").unwrap();
            let domain_id = take_app_secret(&mut fields, "domain_id").unwrap();
            let status = take_app_secret(&mut fields, "status").unwrap();
            let revision = take_app_secret(&mut fields, "revision").unwrap();
            if mission_id.as_str().is_empty()
                || mission_id.as_str().len() > 128
                || mission_id.as_str().chars().any(char::is_control)
                || title.as_str().chars().count() > 80
                || domain_id.as_str() != "dom_synthetic_a"
                || !is_safe_mission_status(status.as_str())
                || revision.as_str().parse::<u64>().is_err()
            {
                return g5_error_json("protocol_failure");
            }
            format!(
                "{{\"ok\":true,\"dataset\":\"api_synthetic\",\"items\":[{{\"id\":{},\"title\":{},\"domain_id\":{},\"status\":{},\"revision\":{}}}]}}",
                json_string(mission_id.as_str()),
                json_string(title.as_str()),
                json_string(domain_id.as_str()),
                json_string(status.as_str()),
                revision.as_str(),
            )
        };
        let inner = lock_inner(&self.shared);
        if !g5_generation_matches(&inner, &instance_id, &transport)
            || inner
                .g5_session
                .as_ref()
                .is_none_or(|session| session.token.as_str() != token.as_str())
        {
            return g5_error_json("stale_generation");
        }
        result
    }

    fn g5_credentials_for_active(
        &self,
    ) -> Result<(String, Arc<TransportSession>, SecretText, SecretText), &'static str> {
        let mut inner = lock_inner(&self.shared);
        expire_cached_authorization(&mut inner);
        let Some(session) = inner.g5_session.as_ref() else {
            return Err("session_required");
        };
        if inner.snapshot.state != RuntimeState::Ready
            || inner.transport_snapshot.state != TransportState::Ready
            || inner.snapshot.runtime_instance_id.as_deref()
                != Some(session.runtime_instance_id.as_str())
        {
            return Err("runtime_unavailable");
        }
        let transport = inner
            .transport_session
            .clone()
            .ok_or("runtime_unavailable")?;
        Ok((
            session.runtime_instance_id.clone(),
            transport,
            SecretText::new(session.token.as_str().to_owned()),
            SecretText::new(session.csrf_token.as_str().to_owned()),
        ))
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

    fn start_runtime(&self) -> Result<RuntimeSnapshot, ManagerError> {
        self.start_mode(HelperMode::Normal, false)
    }

    fn restart_runtime(&self) -> Result<RuntimeSnapshot, ManagerError> {
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
        command.current_dir(transport_session.directory_path());
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
        if transport_session.set_expected_peer_pid(pid).is_err() {
            drop(inner);
            let _ = child.kill();
            let status = child.wait().ok();
            finish_start_failure(
                &self.shared,
                &instance_id,
                "transport_peer_setup_failed",
                status,
            );
            return Err(ManagerError::TransportSetupFailed);
        }
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
        let supervisor_sender = sender.clone();
        thread::spawn(move || {
            supervise_child(
                shared,
                worker_instance_id,
                child,
                stdin,
                receiver,
                supervisor_sender,
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

    #[cfg(any(test, feature = "mac003-production-supervisor-test"))]
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

    #[cfg(any(test, feature = "mac003-production-supervisor-test"))]
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

    #[cfg(any(test, feature = "mac003-production-supervisor-test"))]
    fn transport_session_for_test(&self) -> Arc<TransportSession> {
        lock_inner(&self.shared)
            .transport_session
            .clone()
            .expect("active generation has a transport session")
    }

    #[cfg(any(test, feature = "mac003-production-supervisor-test"))]
    fn close_control_for_test(&self) {
        self.queue_control_close_for_test()
            .recv_timeout(Duration::from_secs(1))
            .expect("supervisor closed the control pipe");
    }

    #[cfg(any(test, feature = "mac003-production-supervisor-test"))]
    fn queue_control_close_for_test(&self) -> Receiver<()> {
        let sender = lock_inner(&self.shared)
            .supervisor
            .clone()
            .expect("active generation has a supervisor");
        let (reply, received) = mpsc::channel();
        sender
            .send(SupervisorMessage::CloseControl(reply))
            .expect("supervisor worker is active");
        received
    }

    #[cfg(any(test, feature = "mac003-production-supervisor-test"))]
    fn has_supervisor(&self) -> bool {
        lock_inner(&self.shared).supervisor.is_some()
    }

    #[cfg(feature = "mac003-production-supervisor-test")]
    fn crash_child_for_integration_test(&self) -> Result<(), &'static str> {
        let sender = lock_inner(&self.shared)
            .supervisor
            .clone()
            .ok_or("supervisor unavailable for crash injection")?;
        let (reply, received) = mpsc::channel();
        sender
            .send(SupervisorMessage::CrashChildForIntegration(reply))
            .map_err(|_| "supervisor rejected crash injection")?;
        if received
            .recv_timeout(Duration::from_secs(2))
            .map_err(|_| "supervisor did not acknowledge crash injection")?
        {
            Ok(())
        } else {
            Err("supervisor could not inject child crash")
        }
    }

    #[cfg(feature = "mac003-production-supervisor-test")]
    fn g5_missions_list_server_probe_for_integration_test(&self) -> String {
        let _operation = self
            .g5_operation
            .lock()
            .unwrap_or_else(|error| error.into_inner());
        let (_instance_id, transport, token, _csrf_token) = match self.g5_credentials_for_active() {
            Ok(value) => value,
            Err(error) => return g5_error_json(error),
        };
        let body = SecretBytes::new(encode_application_fields(&[
            ("session_token", token.as_str()),
            ("domain_id", "dom_synthetic_a"),
        ]));
        let response = match transport.call_g5_application("/v1/app/missions/list", body.as_slice())
        {
            Ok(value) => SecretBytes::new(value),
            Err(_) => return g5_error_json("transport_failure"),
        };
        let fields = match parse_application_response(response.as_slice()) {
            Ok(value) => value,
            Err(()) => return g5_error_json("protocol_failure"),
        };
        if let Some(error) = app_response_error(&fields) {
            return g5_error_json(error);
        }
        g5_error_json("operation_failed")
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

#[cfg(feature = "mac003-production-supervisor-test")]
struct ProductionSupervisorTestCleanup {
    scratch: PathBuf,
    transport_directories: Vec<PathBuf>,
}

#[cfg(feature = "mac003-production-supervisor-test")]
impl Drop for ProductionSupervisorTestCleanup {
    fn drop(&mut self) {
        for directory in &self.transport_directories {
            let _ = std::fs::remove_dir(directory);
        }
        for suffix in ["", "-wal", "-shm"] {
            let path = PathBuf::from(format!(
                "{}{}",
                self.scratch.join("synthetic.sqlite3").display(),
                suffix
            ));
            let _ = std::fs::remove_file(path);
        }
        let _ = std::fs::remove_dir(&self.scratch);
        env::remove_var("JARVIS_LOCAL_PASSPHRASE");
        env::remove_var("JARVIS_DATABASE_PATH");
    }
}

/// Integration entrypoint compiled into the library dependency without `cfg(test)`.
/// The manager therefore selects the same Python/serve.py launcher as the Tauri release build.
#[cfg(feature = "mac003-production-supervisor-test")]
pub fn run_production_supervisor_integration() -> Result<(), &'static str> {
    let api_root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../../api")
        .canonicalize()
        .map_err(|_| "API source root is unavailable")?;
    let python = api_root.join(".venv/bin/python");
    if !python.is_file() {
        return Err("API virtualenv is unavailable; no dependencies were installed");
    }

    let scratch = env::temp_dir().join(format!(
        "mac003-production-supervisor-{}-{}",
        std::process::id(),
        unix_time_microseconds()
    ));
    std::fs::create_dir(&scratch).map_err(|_| "synthetic test directory could not be created")?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(&scratch, std::fs::Permissions::from_mode(0o700))
            .map_err(|_| "synthetic test directory permissions could not be set")?;
    }
    let mut cleanup = ProductionSupervisorTestCleanup {
        scratch: scratch.clone(),
        transport_directories: Vec::new(),
    };
    let database = scratch.join("synthetic.sqlite3");
    let passphrase = format!("synthetic-supervisor-{}", unix_time_microseconds());
    env::set_var("JARVIS_LOCAL_PASSPHRASE", &passphrase);
    env::set_var("JARVIS_DATABASE_PATH", &database);

    let seed = std::process::Command::new(&python)
        .arg("-B")
        .arg("-c")
        .arg("from memory_store import SQLiteMemoryStore; from mission_repository import MissionRepository; import os; store=SQLiteMemoryStore(os.environ['JARVIS_DATABASE_PATH']); store.initialize(); MissionRepository(store).create('owner', 'MAC003 synthetic supervisor mission', 'dom_synthetic_a', 'mac003-production-supervisor-seed')")
        .current_dir(&api_root)
        .env_clear()
        .env("JARVIS_DATABASE_PATH", &database)
        .env("PYTHONDONTWRITEBYTECODE", "1")
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status()
        .map_err(|_| "synthetic database seeder could not start")?;
    if !seed.success() {
        return Err("synthetic database seeder failed");
    }

    let manager = RuntimeManager::new();
    let result = (|| {
        let first_start = manager
            .start_runtime()
            .map_err(|_| "production RuntimeManager failed to spawn FastAPI")?;
        let first_id = first_start
            .runtime_instance_id
            .clone()
            .ok_or("production RuntimeManager omitted its generation ID")?;
        let first_ready = manager.wait_for_state(RuntimeState::Ready, Duration::from_secs(30));
        if first_ready.runtime_instance_id.as_deref() != Some(first_id.as_str()) {
            return Err("FastAPI did not reach authenticated RuntimeManager READY");
        }
        let first_transport =
            manager.wait_for_transport_state(TransportState::Ready, Duration::from_secs(30));
        if first_transport.runtime_instance_id.as_deref() != Some(first_id.as_str()) {
            return Err("FastAPI UDS proof did not reach transport READY");
        }
        let first_session = manager.transport_session_for_test();
        cleanup
            .transport_directories
            .push(first_session.directory_path().to_owned());

        let session_open_body = SecretBytes::new(encode_application_fields(&[(
            "passphrase",
            passphrase.as_str(),
        )]));
        let create_grant_body = SecretBytes::new(encode_application_fields(&[
            ("session_token", "synthetic-session-token-for-peer-probe"),
            ("csrf_token", "synthetic-csrf-token-for-peer-probe"),
            ("domain_id", "dom_synthetic_a"),
        ]));
        let revoke_grant_body = SecretBytes::new(encode_application_fields(&[
            ("session_token", "synthetic-session-token-for-peer-probe"),
            ("csrf_token", "synthetic-csrf-token-for-peer-probe"),
            ("grant_id", "0123456789abcdef0123456789abcdef"),
        ]));
        let list_missions_body = SecretBytes::new(encode_application_fields(&[
            ("session_token", "synthetic-session-token-for-peer-probe"),
            ("domain_id", "dom_synthetic_a"),
        ]));
        for (route, body) in [
            ("/v1/app/session/open", session_open_body.as_slice()),
            ("/v1/app/grants/mission-read", create_grant_body.as_slice()),
            (
                "/v1/app/grants/mission-read/revoke",
                revoke_grant_body.as_slice(),
            ),
            ("/v1/app/missions/list", list_missions_body.as_slice()),
        ] {
            assert_replacement_peer_rejected(&python, &first_session, route, body)?;
        }
        eprintln!("mac002_2 stage=real_fastapi_proof_then_socket_swap_rejected PASS");

        if !manager
            .g5_session_open(passphrase.clone())
            .contains("\"session_active\":true")
        {
            return Err("synthetic passphrase did not open a G5 session");
        }
        if !manager
            .g5_mission_read_grant_create()
            .contains("\"grant_active\":true")
        {
            return Err("explicit mission:read grant creation failed");
        }
        let missions = manager.g5_missions_list();
        if !missions.contains("MAC003 synthetic supervisor mission")
            || !missions.contains("\"dataset\":\"api_synthetic\"")
        {
            return Err("G5 list did not return the synthetic mission");
        }
        eprintln!("production_supervisor stage=ready_g5_grant_read_revoke PASS");

        let direct_probe = run_same_uid_uds_probe(&python, first_session.directory_path())?;
        eprintln!("same_uid_uds_probe={direct_probe}");
        if direct_probe.trim_end()
            != "health=200;version=200;proof=200;open=404;close=404;grant=404;revoke=404;read=404"
        {
            return Err("same-UID direct UDS probe crossed an unexpected authorization boundary");
        }

        if !manager
            .g5_mission_read_grant_revoke()
            .contains("\"grant_active\":false")
        {
            return Err("grant revocation failed");
        }
        let local_denial = manager.g5_missions_list();
        if !local_denial.contains("concessão de leitura está ausente") {
            return Err("Rust cache did not deny mission read after revocation");
        }
        let server_denial = manager.g5_missions_list_server_probe_for_integration_test();
        if !server_denial.contains("concessão de leitura está ausente") {
            return Err("FastAPI did not deny mission read after grant revocation");
        }

        if !manager
            .g5_mission_read_grant_create()
            .contains("\"grant_active\":true")
            || !manager
                .g5_session_close()
                .contains("\"session_active\":false")
            || !manager
                .g5_session_open(passphrase.clone())
                .contains("\"session_active\":true")
            || !manager
                .g5_session_status_json()
                .contains("\"grant_active\":false")
        {
            return Err("closing and reopening a session did not clear its grant");
        }

        let first_pid = first_ready
            .pid
            .ok_or("READY omitted the supervised child PID")?;
        let stopped = manager
            .stop_and_wait()
            .map_err(|_| "RuntimeManager STOP did not complete")?;
        if stopped.state != RuntimeState::Stopped || stopped.exit_code != Some(0) {
            return Err("RuntimeManager STOP did not produce normal STOPPED exit");
        }
        if manager.has_supervisor() || !first_session.is_clean_for_test() {
            return Err("STOP left a supervisor, capability, or UDS socket active");
        }
        if !child_pid_is_reaped(first_pid) {
            return Err("RuntimeManager STOP returned before the FastAPI child was reaped");
        }
        eprintln!("production_supervisor stage=STOP_reap_uds_cleanup PASS");

        let eof_start = manager
            .start_runtime()
            .map_err(|_| "RuntimeManager failed to start the EOF generation")?;
        let eof_id = eof_start
            .runtime_instance_id
            .clone()
            .ok_or("EOF generation omitted its ID")?;
        let eof_ready = manager.wait_for_state(RuntimeState::Ready, Duration::from_secs(30));
        if eof_ready.runtime_instance_id.as_deref() != Some(eof_id.as_str()) {
            return Err("EOF generation did not become READY");
        }
        manager.wait_for_transport_state(TransportState::Ready, Duration::from_secs(30));
        let eof_session = manager.transport_session_for_test();
        cleanup
            .transport_directories
            .push(eof_session.directory_path().to_owned());
        let eof_pid = eof_ready.pid.ok_or("EOF READY omitted child PID")?;
        manager.close_control_for_test();
        let eof_exit = manager.wait_for_state(RuntimeState::Stopped, Duration::from_secs(15));
        if eof_exit.failure_category != Some("supervisor_lost") || eof_exit.exit_code != Some(48) {
            return Err("FastAPI stdin EOF did not produce supervisor_lost STOPPED");
        }
        if manager.has_supervisor() || !eof_session.is_clean_for_test() {
            return Err("EOF left a supervisor, capability, or UDS socket active");
        }
        if !child_pid_is_reaped(eof_pid) {
            return Err("RuntimeManager did not reap the FastAPI child after EOF");
        }
        eprintln!("production_supervisor stage=EOF_supervisor_lost_reap_cleanup PASS");

        let crash_start = manager
            .start_runtime()
            .map_err(|_| "RuntimeManager failed to start the crash generation")?;
        let crash_id = crash_start
            .runtime_instance_id
            .clone()
            .ok_or("crash generation omitted its ID")?;
        let crash_ready = manager.wait_for_state(RuntimeState::Ready, Duration::from_secs(30));
        if crash_ready.runtime_instance_id.as_deref() != Some(crash_id.as_str()) {
            return Err("crash generation did not become READY");
        }
        manager.wait_for_transport_state(TransportState::Ready, Duration::from_secs(30));
        let crash_session = manager.transport_session_for_test();
        cleanup
            .transport_directories
            .push(crash_session.directory_path().to_owned());
        let crashed_pid = crash_ready.pid.ok_or("crash READY omitted child PID")?;
        manager.crash_child_for_integration_test()?;
        let crashed = manager.wait_for_state(RuntimeState::Crashed, Duration::from_secs(15));
        if crashed.failure_category != Some("child_crash") {
            return Err("supervisor did not classify the injected child crash");
        }
        if manager.has_supervisor() || !crash_session.is_clean_for_test() {
            return Err("crash left a supervisor, capability, or UDS socket active");
        }
        if !child_pid_is_reaped(crashed_pid) {
            return Err("RuntimeManager did not reap the crashed FastAPI child");
        }
        eprintln!("production_supervisor stage=crash_reap PASS");

        let restart_start = manager
            .restart_runtime()
            .map_err(|_| "RuntimeManager explicit restart after crash failed")?;
        let restart_id = restart_start
            .runtime_instance_id
            .as_deref()
            .ok_or("restarted generation omitted its ID")?;
        if restart_id == crash_id {
            return Err("restart reused the crashed generation ID");
        }
        let restart_ready = manager.wait_for_state(RuntimeState::Ready, Duration::from_secs(30));
        if restart_ready.runtime_instance_id.as_deref() != Some(restart_id) {
            return Err("restarted FastAPI generation did not reach READY");
        }
        manager.wait_for_transport_state(TransportState::Ready, Duration::from_secs(30));
        let restart_session = manager.transport_session_for_test();
        cleanup
            .transport_directories
            .push(restart_session.directory_path().to_owned());
        let restart_pid = restart_ready.pid.ok_or("restart READY omitted child PID")?;
        let final_stop = manager
            .stop_and_wait()
            .map_err(|_| "RuntimeManager STOP after restart failed")?;
        if final_stop.state != RuntimeState::Stopped
            || final_stop.exit_code != Some(0)
            || manager.has_supervisor()
            || !restart_session.is_clean_for_test()
            || !child_pid_is_reaped(restart_pid)
        {
            return Err("restarted FastAPI generation did not STOP and clean up");
        }
        eprintln!("production_supervisor stage=restart_READY_STOP_reap_cleanup PASS");
        Ok(())
    })();
    drop(manager);
    result
}

#[cfg(feature = "mac003-production-supervisor-test")]
fn assert_replacement_peer_rejected(
    python: &Path,
    transport: &Arc<TransportSession>,
    route: &'static str,
    body: &[u8],
) -> Result<(), &'static str> {
    use std::io::Read;

    const FAKE_PEER: &str = r#"
import os, socket, sys
path = sys.argv[1]
ready_path = sys.argv[2]
listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
listener.bind(path)
os.chmod(path, 0o600)
listener.listen(1)
with open(ready_path, "wb") as marker:
    marker.write(b"ready")
connection, _ = listener.accept()
try:
    connection.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: application/octet-stream\r\nContent-Length: 1\r\nConnection: close\r\n\r\nx")
except OSError:
    pass
received = bytearray()
connection.settimeout(1)
try:
    while True:
        chunk = connection.recv(1024)
        if not chunk:
            break
        received.extend(chunk)
except OSError:
    pass
print("payload=" + ("1" if received else "0"), flush=True)
connection.close()
listener.close()
"#;

    let socket_path = transport.directory_path().join("runtime.sock");
    let saved_path = transport.directory_path().join("runtime.genuine.sock");
    let ready_path = transport
        .directory_path()
        .join("replacement-listener.ready");
    if saved_path.exists() {
        return Err("replacement probe found an unexpected saved socket");
    }

    let mut fake_peer = None;
    let mut setup_ok = true;
    let result = transport.call_g5_application_after_probe_for_test(route, body, || {
        if std::fs::rename(&socket_path, &saved_path).is_err() {
            setup_ok = false;
            return;
        }
        let child = std::process::Command::new(python)
            .arg("-B")
            .arg("-c")
            .arg(FAKE_PEER)
            .arg(&socket_path)
            .arg(&ready_path)
            .env_clear()
            .env("PYTHONDONTWRITEBYTECODE", "1")
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .spawn();
        match child {
            Ok(child) => {
                fake_peer = Some(child);
                let deadline = Instant::now() + Duration::from_secs(2);
                while !ready_path.exists() && Instant::now() < deadline {
                    thread::sleep(Duration::from_millis(5));
                }
                setup_ok = socket_path.exists() && ready_path.exists();
            }
            Err(_) => setup_ok = false,
        }
    });

    let mut payload_marker = String::new();
    let fake_status_ok = if let Some(mut child) = fake_peer {
        let deadline = Instant::now() + Duration::from_secs(2);
        while child.try_wait().ok().flatten().is_none() && Instant::now() < deadline {
            thread::sleep(Duration::from_millis(5));
        }
        if child.try_wait().ok().flatten().is_none() {
            let _ = child.kill();
        }
        let status = child.wait().ok();
        if let Some(mut stdout) = child.stdout.take() {
            let _ = stdout.read_to_string(&mut payload_marker);
        }
        status.is_some_and(|status| status.success())
    } else {
        false
    };

    if socket_path.exists() {
        let _ = std::fs::remove_file(&socket_path);
    }
    if ready_path.exists() {
        let _ = std::fs::remove_file(&ready_path);
    }
    let restored = saved_path.exists() && std::fs::rename(&saved_path, &socket_path).is_ok();
    if !setup_ok || !fake_status_ok || !restored {
        return Err("socket replacement probe did not complete and restore the genuine endpoint");
    }
    if result != Err(TransportError::PeerRejected) || payload_marker.trim() != "payload=0" {
        return Err("replacement peer received data or its response was not rejected");
    }
    Ok(())
}

#[cfg(feature = "mac003-production-supervisor-test")]
fn run_same_uid_uds_probe(python: &Path, directory: &Path) -> Result<String, &'static str> {
    const PROBE: &str = r#"
import secrets, socket, sys
sock_path = sys.argv[1]
probe_step = "start"
def request(method, path, body=b""):
    global probe_step
    probe_step = "connect"
    conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    conn.settimeout(3)
    conn.connect(sock_path)
    probe_step = "send"
    head = (f"{method} {path} HTTP/1.1\r\nHost: jarvis.local\r\nContent-Type: text/plain\r\nContent-Length: {len(body)}\r\nConnection: close\r\n\r\n").encode("ascii")
    conn.sendall(head + body)
    chunks = []
    probe_step = "receive"
    while True:
        chunk = conn.recv(4096)
        if not chunk:
            break
        chunks.append(chunk)
    conn.close()
    raw = b"".join(chunks)
    probe_step = "parse_status"
    head, _, body = raw.partition(b"\r\n\r\n")
    status = int(head.split(b"\r\n", 1)[0].split()[1])
    return status
stage = "health"
try:
    health = request("GET", "/v1/health")
    stage = "version"
    version = request("GET", "/v1/version")
    stage = "proof"
    proof = request("POST", "/v1/instance-proof", secrets.token_hex(32).encode("ascii"))
    stage = "open"
    opened = request("POST", "/v1/app/session/open", b"passphrase=wrong-synthetic-probe\n")
    stage = "close"
    closed = request("POST", "/v1/app/session/close", b"session_token=fake-session\ncsrf_token=fake-csrf\n")
    stage = "grant"
    granted = request("POST", "/v1/app/grants/mission-read", b"session_token=fake-session\ncsrf_token=fake-csrf\ndomain_id=dom_synthetic_a\n")
    stage = "revoke"
    revoked = request("POST", "/v1/app/grants/mission-read/revoke", b"session_token=fake-session\ncsrf_token=fake-csrf\ngrant_id=fake-grant\n")
    stage = "read"
    listed = request("POST", "/v1/app/missions/list", b"session_token=fake-session\ndomain_id=dom_synthetic_a\n")
    print(f"health={health};version={version};proof={proof};open={opened};close={closed};grant={granted};revoke={revoked};read={listed}")
except Exception as exc:
    print("probe_error=" + type(exc).__name__ + ";stage=" + stage + ";step=" + probe_step)
    raise SystemExit(2)
"#;
    let output = std::process::Command::new(python)
        .arg("-B")
        .arg("-c")
        .arg(PROBE)
        .arg(directory.join("runtime.sock"))
        .env_clear()
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .output()
        .map_err(|_| "same-UID probe process could not start")?;
    if !output.status.success() {
        let diagnostic = String::from_utf8_lossy(&output.stdout);
        if let Some(line) = diagnostic.lines().next() {
            eprintln!("same_uid_uds_probe diagnostic={line}");
        }
        return Err("same-UID probe process failed");
    }
    String::from_utf8(output.stdout).map_err(|_| "same-UID probe returned invalid status text")
}

#[cfg(feature = "mac003-production-supervisor-test")]
fn child_pid_is_reaped(pid: u32) -> bool {
    std::process::Command::new("/bin/kill")
        .arg("-0")
        .arg(pid.to_string())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status()
        .is_ok_and(|status| !status.success())
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
            | (RuntimeState::Ready, RuntimeState::Stopped)
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

fn mark_ready_after_transport(
    shared: &Shared,
    instance_id: &str,
    session: &Arc<TransportSession>,
) -> bool {
    let mut inner = lock_inner(shared);
    if inner.snapshot.runtime_instance_id.as_deref() != Some(instance_id)
        || inner.snapshot.state != RuntimeState::Starting
        || inner.transport_snapshot.state != TransportState::ProvingInstance
        || !inner
            .transport_session
            .as_ref()
            .is_some_and(|current| Arc::ptr_eq(current, session))
    {
        return false;
    }
    inner.transport_snapshot = TransportSnapshot {
        state: TransportState::Ready,
        runtime_instance_id: Some(instance_id.to_owned()),
        endpoint_type: Some("uds"),
        protocol_version: Some("2".to_owned()),
        error_category: None,
    };
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
        || inner.transport_snapshot.state != TransportState::ProvingInstance
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
                protocol_version: Some("2".to_owned()),
                error_category: None,
            };
            eprintln!(
                "transport ready instance_id={instance_id} endpoint_type=uds protocol_version=2"
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
    inner.g5_session = None;
    inner.g5_grant = None;
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
    let supervisor_lost = status.code() == Some(SUPERVISOR_LOST_EXIT);
    let target = match inner.snapshot.state {
        RuntimeState::Starting => {
            inner.snapshot.failure_category = Some(if supervisor_lost {
                "supervisor_lost"
            } else {
                "child_exit_before_ready"
            });
            RuntimeState::Failed
        }
        RuntimeState::Ready if supervisor_lost => {
            inner.snapshot.failure_category = Some("supervisor_lost");
            RuntimeState::Stopped
        }
        RuntimeState::Ready => {
            inner.snapshot.failure_category = Some("child_crash");
            RuntimeState::Crashed
        }
        RuntimeState::Stopping => {
            if supervisor_lost {
                inner.snapshot.failure_category = Some("supervisor_lost");
            }
            RuntimeState::Stopped
        }
        _ => return,
    };
    inner.snapshot.exit_code = status.code();
    transition_locked(&mut inner, target, instance_id);
    let failure_category = inner.snapshot.failure_category;
    revoke_transport_locked(
        &mut inner,
        instance_id,
        if target == RuntimeState::Stopped {
            TransportState::Disconnected
        } else {
            TransportState::Failed
        },
        failure_category,
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
    sender: Sender<SupervisorMessage>,
    options: RuntimeOptions,
    transport_session: Arc<TransportSession>,
) {
    let startup_deadline = Instant::now() + options.startup_timeout;
    let mut readiness_channel_closed = false;
    let mut readiness_acknowledged = false;
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
                if is_ready_for(&line, &instance_id) {
                    if readiness_acknowledged
                        || lock_inner(&shared).snapshot.state != RuntimeState::Starting
                    {
                        continue;
                    }
                    if !transport_session.path_matches_handle() {
                        let _ = child.kill();
                        let status = child.wait().ok();
                        finish_start_failure(
                            &shared,
                            &instance_id,
                            "transport_path_changed",
                            status,
                        );
                        return;
                    }
                    let acknowledged = stdin.as_mut().is_some_and(|pipe| {
                        writeln!(pipe, "{ACK_PREFIX}{instance_id}")
                            .and_then(|_| pipe.flush())
                            .is_ok()
                    });
                    if !acknowledged {
                        let _ = child.kill();
                        let status = child.wait().ok();
                        finish_start_failure(&shared, &instance_id, "supervisor_lost", status);
                        return;
                    }
                    if !transport_session.path_matches_handle() {
                        let _ = child.kill();
                        let status = child.wait().ok();
                        finish_start_failure(
                            &shared,
                            &instance_id,
                            "transport_path_changed",
                            status,
                        );
                        return;
                    }
                    readiness_acknowledged = true;
                    {
                        let mut inner = lock_inner(&shared);
                        if inner.snapshot.runtime_instance_id.as_deref()
                            == Some(instance_id.as_str())
                            && inner.snapshot.state == RuntimeState::Starting
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
                    let probe_sender = sender.clone();
                    let probe_session = Arc::clone(&transport_session);
                    thread::spawn(move || {
                        let result = probe_session.probe();
                        let _ = probe_sender.send(SupervisorMessage::TransportVerified(result));
                    });
                }
            }
            SupervisorMessage::TransportVerified(result) => {
                if lock_inner(&shared).snapshot.state != RuntimeState::Starting {
                    continue;
                }
                match result {
                    Ok(()) if transport_session.path_matches_handle() => {
                        if !mark_ready_after_transport(&shared, &instance_id, &transport_session) {
                            continue;
                        }
                        eprintln!(
                            "runtime authenticated and ready instance_id={instance_id} endpoint_type=uds protocol_version=2"
                        );
                    }
                    result => {
                        let category = match result {
                            Err(error) => error.category(),
                            Ok(()) => "transport_path_changed",
                        };
                        let _ = child.kill();
                        let status = child.wait().ok();
                        finish_start_failure(&shared, &instance_id, category, status);
                        return;
                    }
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
            #[cfg(any(test, feature = "mac003-production-supervisor-test"))]
            SupervisorMessage::CloseControl(reply) => {
                drop(stdin.take());
                let _ = reply.send(());
            }
            #[cfg(feature = "mac003-production-supervisor-test")]
            SupervisorMessage::CrashChildForIntegration(reply) => {
                let _ = reply.send(child.kill().is_ok());
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

#[cfg(test)]
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
        let _ = mode;
        let _ = stale_instance_id;
        let api_root = Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../../api")
            .canonicalize()?;
        let venv_python = api_root.join(".venv/bin/python");
        let executable = if venv_python.is_file() {
            venv_python
        } else {
            PathBuf::from("python3.12")
        };
        let mut command = Command::new(executable);
        command.env_clear();
        command
            .arg("-u")
            .arg(api_root.join("serve.py"))
            .arg("--desktop-runtime")
            .arg(instance_id)
            .env("PYTHONUNBUFFERED", "1")
            .env("PYTHONDONTWRITEBYTECODE", "1");
        for name in ["JARVIS_LOCAL_PASSPHRASE", "JARVIS_DATABASE_PATH"] {
            if let Some(value) = env::var_os(name) {
                command.env(name, value);
            }
        }
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

fn unix_time_microseconds() -> u64 {
    u64::try_from(
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .as_micros(),
    )
    .unwrap_or(u64::MAX)
}

fn expire_cached_authorization(inner: &mut Inner) {
    expire_cached_authorization_at(inner, unix_time_microseconds());
}

fn expire_cached_authorization_at(inner: &mut Inner, now: u64) {
    if inner
        .g5_session
        .as_ref()
        .is_some_and(|session| session.expires_at_unix_microseconds <= now)
    {
        inner.g5_session = None;
        inner.g5_grant = None;
    }
    if inner.g5_grant.as_ref().is_some_and(|grant| {
        grant.expires_at_unix_microseconds <= now
            || inner
                .g5_session
                .as_ref()
                .is_none_or(|session| session.token.as_str() != grant.session_token.as_str())
    }) {
        inner.g5_grant = None;
    }
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

fn g5_error_json(code: &str) -> String {
    let message = match code {
        "runtime_unavailable" => "O runtime local autenticado não está pronto.",
        "credential_rejected" => "Credencial local recusada ou não configurada.",
        "session_required" => "Abra novamente a sessão G5 local.",
        "session_already_open" => "Já existe uma sessão G5 aberta neste runtime.",
        "grant_required" => "A concessão de leitura está ausente ou expirada.",
        "grant_active" => "Revogue a concessão de leitura antes de encerrar a sessão.",
        "grant_conflict" => "Já existe uma concessão ativa para este escopo.",
        "scope_invalid" => "O escopo fixo de leitura foi recusado.",
        "grant_expired" => "A concessão de leitura expirou.",
        "stale_generation" => "A resposta pertence a um runtime encerrado.",
        "protocol_failure" => "O backend retornou uma resposta inválida.",
        _ => "Não foi possível concluir a operação G5 local.",
    };
    format!("{{\"ok\":false,\"error\":{}}}", json_string(message))
}

fn encode_application_fields(fields: &[(&str, &str)]) -> Vec<u8> {
    let mut body = Vec::new();
    for (name, value) in fields {
        body.extend_from_slice(name.as_bytes());
        body.push(b'=');
        append_application_value(value.as_bytes(), &mut body);
        body.push(b'\n');
    }
    body
}

fn append_application_value(value: &[u8], output: &mut Vec<u8>) {
    const HEX: &[u8; 16] = b"0123456789ABCDEF";
    for byte in value {
        if byte.is_ascii_alphanumeric() || matches!(*byte, b'-' | b'_' | b'.' | b'~') {
            output.push(*byte);
        } else {
            output.push(b'%');
            output.push(HEX[(byte >> 4) as usize]);
            output.push(HEX[(byte & 0x0f) as usize]);
        }
    }
}

fn parse_application_response(body: &[u8]) -> Result<Vec<(String, SecretText)>, ()> {
    if body.is_empty() || body.len() > 2048 || !body.ends_with(b"\n") || body.contains(&b'\r') {
        return Err(());
    }
    let text = std::str::from_utf8(&body[..body.len() - 1]).map_err(|_| ())?;
    let mut parsed = Vec::new();
    for line in text.split('\n') {
        if parsed.len() >= 8 {
            return Err(());
        }
        let (name, encoded) = line.split_once('=').ok_or(())?;
        if name.is_empty()
            || !name
                .bytes()
                .all(|byte| byte.is_ascii_lowercase() || byte == b'_')
            || parsed.iter().any(|(existing, _)| existing == name)
        {
            return Err(());
        }
        let mut decoded = Vec::with_capacity(encoded.len());
        let bytes = encoded.as_bytes();
        let mut index = 0;
        while index < bytes.len() {
            if bytes[index] == b'%' {
                if index + 2 >= bytes.len() {
                    return Err(());
                }
                let high = application_hex_nibble(bytes[index + 1]).ok_or(())?;
                let low = application_hex_nibble(bytes[index + 2]).ok_or(())?;
                decoded.push((high << 4) | low);
                index += 3;
            } else {
                let byte = bytes[index];
                if !(byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'_' | b'.' | b'~')) {
                    return Err(());
                }
                decoded.push(byte);
                index += 1;
            }
        }
        let value = String::from_utf8(decoded).map_err(|_| ())?;
        let mut canonical = Vec::with_capacity(encoded.len());
        append_application_value(value.as_bytes(), &mut canonical);
        let is_canonical = canonical.as_slice() == encoded.as_bytes();
        canonical.fill(0);
        if !is_canonical {
            return Err(());
        }
        parsed.push((name.to_owned(), SecretText::new(value)));
    }
    Ok(parsed)
}

fn application_hex_nibble(value: u8) -> Option<u8> {
    match value {
        b'0'..=b'9' => Some(value - b'0'),
        b'A'..=b'F' => Some(value - b'A' + 10),
        _ => None,
    }
}

fn app_fields_match(fields: &[(String, SecretText)], expected: &[&str]) -> bool {
    fields.len() == expected.len()
        && fields
            .iter()
            .zip(expected)
            .all(|((name, _), expected)| name == expected)
}

fn app_field<'a>(fields: &'a [(String, SecretText)], name: &str) -> Option<&'a str> {
    fields
        .iter()
        .find(|(field, _)| field == name)
        .map(|(_, value)| value.as_str())
}

fn take_app_secret(fields: &mut Vec<(String, SecretText)>, name: &str) -> Option<SecretText> {
    fields
        .iter()
        .position(|(field, _)| field == name)
        .map(|index| fields.remove(index).1)
}

fn app_response_error(fields: &[(String, SecretText)]) -> Option<&'static str> {
    if app_field(fields, "ok") != Some("false") {
        return None;
    }
    if !app_fields_match(fields, &["ok", "code"]) {
        return Some("protocol_failure");
    }
    Some(match app_field(fields, "code")? {
        "credential_rejected" => "credential_rejected",
        "session_required" => "session_required",
        "grant_required" => "grant_required",
        "grant_active" => "grant_active",
        "scope_invalid" => "scope_invalid",
        "grant_conflict" => "grant_conflict",
        "grant_expired" => "grant_expired",
        "operation_failed" => "operation_failed",
        _ => "protocol_failure",
    })
}

fn is_session_token(value: &str) -> bool {
    (32..=128).contains(&value.len())
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'_' | b'-'))
}

fn is_hex_identifier(value: &str) -> bool {
    value.len() == 32
        && value
            .bytes()
            .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
}

fn is_safe_mission_status(value: &str) -> bool {
    matches!(
        value,
        "draft"
            | "planned"
            | "awaiting_approval"
            | "running"
            | "blocked"
            | "done"
            | "cancelled"
            | "failed"
            | "interrupted"
    )
}

fn g5_generation_matches(
    inner: &Inner,
    instance_id: &str,
    transport: &Arc<TransportSession>,
) -> bool {
    inner.snapshot.state == RuntimeState::Ready
        && inner.transport_snapshot.state == TransportState::Ready
        && inner.snapshot.runtime_instance_id.as_deref() == Some(instance_id)
        && inner
            .transport_session
            .as_ref()
            .is_some_and(|current| Arc::ptr_eq(current, transport))
}

fn clear_cached_authorization_after_rejection(
    shared: &Shared,
    instance_id: &str,
    transport: &Arc<TransportSession>,
    session_token: &str,
    error: &str,
) {
    let mut inner = lock_inner(shared);
    if !g5_generation_matches(&inner, instance_id, transport)
        || inner
            .g5_session
            .as_ref()
            .is_none_or(|session| session.token.as_str() != session_token)
    {
        return;
    }
    match error {
        "session_required" => {
            inner.g5_session = None;
            inner.g5_grant = None;
        }
        "grant_required" | "grant_expired" => inner.g5_grant = None,
        _ => {}
    }
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

fn start_control_reader(
    mut input: BufReader<io::Stdin>,
    instance_id: String,
) -> (Receiver<ControlSignal>, Arc<AtomicBool>) {
    let (sender, receiver) = mpsc::channel();
    let live = Arc::new(AtomicBool::new(true));
    let reader_live = Arc::clone(&live);
    thread::spawn(move || {
        let expected_ack = format!("{ACK_PREFIX}{instance_id}");
        let expected_stop = format!("{STOP_PREFIX}{instance_id}");
        let mut line = String::new();
        loop {
            line.clear();
            match input.read_line(&mut line) {
                Ok(0) | Err(_) => {
                    reader_live.store(false, Ordering::Release);
                    let _ = sender.send(ControlSignal::SupervisorLost);
                    return;
                }
                Ok(_) => match line.trim_end_matches(['\r', '\n']) {
                    command if command == expected_ack => {
                        if sender.send(ControlSignal::Acknowledged).is_err() {
                            return;
                        }
                    }
                    command if command == expected_stop => {
                        reader_live.store(false, Ordering::Release);
                        let _ = sender.send(ControlSignal::Stop);
                        return;
                    }
                    _ => {}
                },
            }
        }
    });
    (receiver, live)
}

fn next_control_signal(
    receiver: &Receiver<ControlSignal>,
    live: &AtomicBool,
) -> Option<ControlSignal> {
    match receiver.try_recv() {
        Ok(signal) => Some(signal),
        Err(mpsc::TryRecvError::Disconnected) => Some(ControlSignal::SupervisorLost),
        Err(mpsc::TryRecvError::Empty) if !live.load(Ordering::Acquire) => {
            Some(ControlSignal::SupervisorLost)
        }
        Err(mpsc::TryRecvError::Empty) => None,
    }
}

fn signal_exit_code(signal: ControlSignal) -> Option<i32> {
    match signal {
        ControlSignal::Acknowledged => None,
        ControlSignal::Stop => Some(0),
        ControlSignal::SupervisorLost => Some(SUPERVISOR_LOST_EXIT),
    }
}

fn wait_for_ack(receiver: &Receiver<ControlSignal>, live: &AtomicBool) -> ControlSignal {
    loop {
        if let Some(signal) = next_control_signal(receiver, live) {
            match signal {
                ControlSignal::Acknowledged => return signal,
                ControlSignal::Stop | ControlSignal::SupervisorLost => return signal,
            }
        }
        match receiver.recv_timeout(POLL_INTERVAL) {
            Ok(signal) => match signal {
                ControlSignal::Acknowledged => return signal,
                ControlSignal::Stop | ControlSignal::SupervisorLost => return signal,
            },
            Err(RecvTimeoutError::Disconnected) => return ControlSignal::SupervisorLost,
            Err(RecvTimeoutError::Timeout) => {}
        }
    }
}

#[cfg(test)]
fn wait_before_readiness(
    receiver: &Receiver<ControlSignal>,
    live: &AtomicBool,
    delay: Duration,
) -> Option<i32> {
    let deadline = Instant::now() + delay;
    loop {
        if let Some(signal) = next_control_signal(receiver, live) {
            if let Some(code) = signal_exit_code(signal) {
                return Some(code);
            }
        }
        let remaining = deadline.saturating_duration_since(Instant::now());
        if remaining.is_zero() {
            return None;
        }
        match receiver.recv_timeout(remaining.min(POLL_INTERVAL)) {
            Ok(signal) => {
                if let Some(code) = signal_exit_code(signal) {
                    return Some(code);
                }
            }
            Err(RecvTimeoutError::Disconnected) => return Some(SUPERVISOR_LOST_EXIT),
            Err(RecvTimeoutError::Timeout) => {}
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
    let (control_receiver, control_live) = start_control_reader(input, instance_id.to_owned());

    match mode {
        HelperMode::CrashBeforeReady => return 41,
        HelperMode::ExitZeroBeforeReady => return 0,
        HelperMode::CloseStdoutThenExit => {
            drop(output);
            close_stdout_for_helper();
            return 47;
        }
        HelperMode::SlowReady => {
            if let Some(code) =
                wait_before_readiness(&control_receiver, &control_live, Duration::from_millis(900))
            {
                return code;
            }
        }
        HelperMode::CloseStdoutBeforeReady => {
            drop(output);
            close_stdout_for_helper();
            return match wait_for_ack(&control_receiver, &control_live) {
                ControlSignal::Stop => 0,
                ControlSignal::SupervisorLost => SUPERVISOR_LOST_EXIT,
                ControlSignal::Acknowledged => 0,
            };
        }
        _ => {}
    }

    let listener = if mode != HelperMode::MissingTransport {
        match transport.bind() {
            Ok(listener) => Some(listener),
            Err(_) => return 45,
        }
    } else {
        None
    };

    match mode {
        _ => {}
    }
    if let Some(signal) = next_control_signal(&control_receiver, &control_live) {
        if let Some(code) = signal_exit_code(signal) {
            return code;
        }
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

    match wait_for_ack(&control_receiver, &control_live) {
        ControlSignal::Stop => return 0,
        ControlSignal::SupervisorLost => return SUPERVISOR_LOST_EXIT,
        ControlSignal::Acknowledged => {}
    }
    if !control_live.load(Ordering::Acquire) {
        return SUPERVISOR_LOST_EXIT;
    }
    if let Some(listener) = listener {
        return serve_transport_until_stop(
            transport,
            listener,
            control_receiver,
            control_live,
            mode == HelperMode::CrashAfterReady,
            mode == HelperMode::HangOnShutdown,
        );
    }
    loop {
        match control_receiver.recv_timeout(POLL_INTERVAL) {
            Ok(ControlSignal::Stop) => return 0,
            Ok(ControlSignal::SupervisorLost) | Err(RecvTimeoutError::Disconnected) => {
                return SUPERVISOR_LOST_EXIT;
            }
            Ok(ControlSignal::Acknowledged) | Err(RecvTimeoutError::Timeout) => {}
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
    let (control_receiver, control_live) = start_control_reader(input, instance_id.to_owned());
    let listener = match transport.bind() {
        Ok(listener) => listener,
        Err(_) => return 45,
    };
    if let Some(signal) = next_control_signal(&control_receiver, &control_live) {
        if let Some(code) = signal_exit_code(signal) {
            return code;
        }
    }
    if writeln!(output, "{READY_PREFIX}{instance_id}")
        .and_then(|_| output.flush())
        .is_err()
    {
        return 43;
    }
    drop(output);

    match wait_for_ack(&control_receiver, &control_live) {
        ControlSignal::Stop => return 0,
        ControlSignal::SupervisorLost => return SUPERVISOR_LOST_EXIT,
        ControlSignal::Acknowledged => {}
    }
    if !control_live.load(Ordering::Acquire) {
        return SUPERVISOR_LOST_EXIT;
    }
    serve_transport_until_stop(
        transport,
        listener,
        control_receiver,
        control_live,
        false,
        false,
    )
}

fn serve_transport_until_stop(
    transport: ChildTransportConfig,
    listener: std::os::unix::net::UnixListener,
    control_receiver: Receiver<ControlSignal>,
    control_live: Arc<AtomicBool>,
    crash_after_authentication: bool,
    hang_after_authentication: bool,
) -> i32 {
    let mut authenticated_requests = 0;
    loop {
        if let Some(signal) = next_control_signal(&control_receiver, &control_live) {
            if let Some(code) = signal_exit_code(signal) {
                return code;
            }
        }
        match transport.serve_one_with_liveness(&listener, Duration::from_millis(10), &control_live)
        {
            Ok(true) => {
                authenticated_requests += 1;
                if authenticated_requests == 3 && crash_after_authentication {
                    return 42;
                }
                if authenticated_requests == 3 && hang_after_authentication {
                    loop {
                        thread::park_timeout(Duration::from_millis(50));
                    }
                }
            }
            Ok(false) => {}
            Err(crate::transport::TransportError::Inactive) => {
                return if next_control_signal(&control_receiver, &control_live)
                    == Some(ControlSignal::Stop)
                {
                    0
                } else {
                    SUPERVISOR_LOST_EXIT
                };
            }
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
pub fn g5_session_status(manager: tauri::State<'_, RuntimeManager>) -> String {
    manager.g5_session_status_json()
}

#[tauri::command]
pub fn g5_session_open(manager: tauri::State<'_, RuntimeManager>, passphrase: String) -> String {
    manager.g5_session_open(passphrase)
}

#[tauri::command]
pub fn g5_mission_read_grant_create(manager: tauri::State<'_, RuntimeManager>) -> String {
    manager.g5_mission_read_grant_create()
}

#[tauri::command]
pub fn g5_mission_read_grant_revoke(manager: tauri::State<'_, RuntimeManager>) -> String {
    manager.g5_mission_read_grant_revoke()
}

#[tauri::command]
pub fn g5_session_close(manager: tauri::State<'_, RuntimeManager>) -> String {
    manager.g5_session_close()
}

#[tauri::command]
pub fn g5_missions_list(manager: tauri::State<'_, RuntimeManager>) -> String {
    manager.g5_missions_list()
}

#[tauri::command]
pub fn runtime_start(manager: tauri::State<'_, RuntimeManager>) -> String {
    let result = manager.start_runtime();
    command_result(&manager, "start", result)
}

#[tauri::command]
pub fn runtime_stop(manager: tauri::State<'_, RuntimeManager>) -> String {
    let result = manager.request_stop();
    command_result(&manager, "stop", result)
}

#[tauri::command]
pub fn runtime_restart(manager: tauri::State<'_, RuntimeManager>) -> String {
    let result = manager.restart_runtime();
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
        fs,
        io::{BufRead, Read, Write},
        os::unix::{fs::PermissionsExt, net::UnixStream},
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
    fn application_protocol_encoding_and_response_parser_are_canonical() {
        let body = encode_application_fields(&[
            ("passphrase", "senha com acento: ação"),
            ("domain_id", "dom_synthetic_a"),
        ]);
        assert_eq!(
            std::str::from_utf8(&body).unwrap(),
            "passphrase=senha%20com%20acento%3A%20a%C3%A7%C3%A3o\ndomain_id=dom_synthetic_a\n"
        );

        let fields =
            parse_application_response(b"ok=true\ntitle=Miss%C3%A3o%20sint%C3%A9tica\n").unwrap();
        assert!(app_fields_match(&fields, &["ok", "title"]));
        assert_eq!(app_field(&fields, "title"), Some("Missão sintética"));
        assert!(parse_application_response(b"ok=true\nok=false\n").is_err());
        assert!(parse_application_response(b"title=%c3%a3\n").is_err());
        assert!(parse_application_response(b"title=bad+space\n").is_err());
    }

    #[test]
    fn cached_grants_follow_session_identity_and_exact_expiry_boundary() {
        let manager = manager();
        let mut inner = lock_inner(&manager.shared);
        inner.g5_session = Some(G5Session {
            runtime_instance_id: "synthetic-generation".to_owned(),
            token: SecretText::new("S1".to_owned()),
            csrf_token: SecretText::new("synthetic-csrf".to_owned()),
            expires_at: "synthetic-expiry".to_owned(),
            expires_at_unix_microseconds: 100,
        });
        inner.g5_grant = Some(G5Grant {
            session_token: SecretText::new("S1".to_owned()),
            id: "synthetic-grant".to_owned(),
            domain_id: "dom_synthetic_a".to_owned(),
            expires_at: "synthetic-expiry".to_owned(),
            expires_at_unix_microseconds: 200,
        });
        expire_cached_authorization_at(&mut inner, 99);
        assert!(inner.g5_session.is_some() && inner.g5_grant.is_some());
        inner.g5_session.as_mut().unwrap().token = SecretText::new("S2".to_owned());
        expire_cached_authorization_at(&mut inner, 99);
        assert!(inner.g5_session.is_some() && inner.g5_grant.is_none());
        inner.g5_grant = Some(G5Grant {
            session_token: SecretText::new("S2".to_owned()),
            id: "synthetic-expiring-grant".to_owned(),
            domain_id: "dom_synthetic_a".to_owned(),
            expires_at: "synthetic-expiry".to_owned(),
            expires_at_unix_microseconds: 99,
        });
        expire_cached_authorization_at(&mut inner, 98);
        assert!(inner.g5_session.is_some() && inner.g5_grant.is_some());
        expire_cached_authorization_at(&mut inner, 99);
        assert!(inner.g5_session.is_some() && inner.g5_grant.is_none());
        inner.g5_grant = Some(G5Grant {
            session_token: SecretText::new("S2".to_owned()),
            id: "synthetic-grant-2".to_owned(),
            domain_id: "dom_synthetic_a".to_owned(),
            expires_at: "synthetic-expiry".to_owned(),
            expires_at_unix_microseconds: 200,
        });
        expire_cached_authorization_at(&mut inner, 100);
        assert!(inner.g5_session.is_none() && inner.g5_grant.is_none());
    }

    #[test]
    fn fractional_grant_deadline_keeps_750ms_and_expires_without_grace() {
        let manager = manager();
        let mut inner = lock_inner(&manager.shared);
        let fields = parse_application_response(b"ok=true\nexpires_at_epoch_us=1750000\n").unwrap();
        let deadline = app_field(&fields, "expires_at_epoch_us")
            .unwrap()
            .parse::<u64>()
            .unwrap();
        assert_eq!(deadline, 1_750_000);
        inner.g5_session = Some(G5Session {
            runtime_instance_id: "synthetic-generation".to_owned(),
            token: SecretText::new("synthetic-session".to_owned()),
            csrf_token: SecretText::new("synthetic-csrf".to_owned()),
            expires_at: "synthetic-expiry".to_owned(),
            expires_at_unix_microseconds: 3_750_000,
        });
        inner.g5_grant = Some(G5Grant {
            session_token: SecretText::new("synthetic-session".to_owned()),
            id: "synthetic-grant".to_owned(),
            domain_id: "dom_synthetic_a".to_owned(),
            expires_at: "synthetic-expiry".to_owned(),
            expires_at_unix_microseconds: deadline,
        });
        expire_cached_authorization_at(&mut inner, 1_000_000);
        assert!(inner.g5_session.is_some() && inner.g5_grant.is_some());
        expire_cached_authorization_at(&mut inner, deadline - 1);
        assert!(inner.g5_session.is_some() && inner.g5_grant.is_some());
        expire_cached_authorization_at(&mut inner, deadline);
        assert!(inner.g5_session.is_some() && inner.g5_grant.is_none());
        expire_cached_authorization_at(&mut inner, 3_750_000 - 1);
        assert!(inner.g5_session.is_some());
        expire_cached_authorization_at(&mut inner, 3_750_000);
        assert!(inner.g5_session.is_none());
    }

    struct FastApiChild {
        child: Child,
        stdin: ChildStdin,
        instance_id: String,
    }

    impl FastApiChild {
        fn stop(&mut self) -> i32 {
            if self.child.try_wait().ok().flatten().is_none() {
                let _ = writeln!(self.stdin, "{STOP_PREFIX}{}", self.instance_id);
                let _ = self.stdin.flush();
            }
            let deadline = Instant::now() + Duration::from_secs(3);
            loop {
                if let Ok(Some(status)) = self.child.try_wait() {
                    return status.code().unwrap_or(-1);
                }
                if Instant::now() >= deadline {
                    let _ = self.child.kill();
                    return self
                        .child
                        .wait()
                        .ok()
                        .and_then(|status| status.code())
                        .unwrap_or(-1);
                }
                thread::sleep(Duration::from_millis(5));
            }
        }
    }

    impl Drop for FastApiChild {
        fn drop(&mut self) {
            let _ = self.stop();
        }
    }

    #[test]
    fn rust_manager_uses_fastapi_g5_over_authenticated_uds() {
        let api_root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../api");
        let python = api_root.join(".venv/bin/python");
        assert!(
            python.is_file(),
            "locked API virtualenv must be prepared before desktop integration tests"
        );

        let manager = manager();
        assert!(manager
            .g5_missions_list()
            .contains("Abra novamente a sessão"));
        let instance_id = new_instance_id();
        let session = TransportSession::create(&instance_id).unwrap();
        let database_path = session.directory_path().join("g5-integration.sqlite3");
        let seed = Command::new(&python)
            .arg("-c")
            .arg("from memory_store import SQLiteMemoryStore; from mission_repository import MissionRepository; import os; store=SQLiteMemoryStore(os.environ['JARVIS_DATABASE_PATH']); store.initialize(); MissionRepository(store).create('owner', 'Missão sintética Rust → FastAPI', 'dom_synthetic_a', 'mac003-rust-seed')")
            .current_dir(&api_root)
            .env_clear()
            .env("JARVIS_DATABASE_PATH", &database_path)
            .env("PYTHONDONTWRITEBYTECODE", "1")
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status()
            .expect("synthetic test database seeder starts");
        assert!(seed.success(), "synthetic test seed succeeds");

        let mut child = Command::new(&python)
            .arg("-u")
            .arg(api_root.join("serve.py"))
            .arg("--desktop-runtime")
            .arg(&instance_id)
            .current_dir(session.directory_path())
            .env_clear()
            .env("JARVIS_LOCAL_PASSPHRASE", "senha-sintetica-rust-mac003")
            .env("JARVIS_DATABASE_PATH", &database_path)
            .env("PYTHONDONTWRITEBYTECODE", "1")
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .spawn()
            .expect("supervised FastAPI runtime starts");
        let stdin = child.stdin.take().unwrap();
        let mut process = FastApiChild {
            child,
            stdin,
            instance_id: instance_id.clone(),
        };
        session.write_child_init(&mut process.stdin).unwrap();
        let stdout = process.child.stdout.take().unwrap();
        let (ready_sender, ready_receiver) = mpsc::channel();
        thread::spawn(move || {
            let mut line = String::new();
            let _ = BufReader::new(stdout).read_line(&mut line);
            let _ = ready_sender.send(line);
        });
        let ready = ready_receiver
            .recv_timeout(Duration::from_secs(12))
            .expect("FastAPI startup reaches READY");
        assert_eq!(ready, format!("{READY_PREFIX}{instance_id}\n"));
        writeln!(process.stdin, "{ACK_PREFIX}{instance_id}").unwrap();
        process.stdin.flush().unwrap();

        assert!(
            session.probe().is_ok(),
            "Rust validates health, version and HMAC proof"
        );
        {
            let mut inner = lock_inner(&manager.shared);
            inner.snapshot = RuntimeSnapshot {
                state: RuntimeState::Ready,
                runtime_instance_id: Some(instance_id.clone()),
                pid: Some(process.child.id()),
                started_at_unix_ms: Some(unix_time_ms()),
                ready_at_unix_ms: Some(unix_time_ms()),
                exit_code: None,
                failure_category: None,
            };
            inner.transport_snapshot = TransportSnapshot {
                state: TransportState::Ready,
                runtime_instance_id: Some(instance_id.clone()),
                endpoint_type: Some("uds"),
                protocol_version: Some("2".to_owned()),
                error_category: None,
            };
            inner.transport_session = Some(Arc::clone(&session));
        }

        let rejected = manager.g5_session_open("senha-incorreta-sintetica".to_owned());
        assert!(rejected.contains("Credencial local recusada"));
        assert!(!rejected.contains("senha-incorreta-sintetica"));
        let opened = manager.g5_session_open("senha-sintetica-rust-mac003".to_owned());
        assert!(opened.contains("\"session_active\":true"));
        assert!(!opened.contains("session_token"));
        assert!(manager.g5_missions_list().contains("concessão de leitura"));

        let granted = manager.g5_mission_read_grant_create();
        assert!(granted.contains("\"grant_active\":true"));
        assert!(!granted.contains("grant_id"));
        let missions = manager.g5_missions_list();
        assert!(missions.contains("Missão sintética Rust → FastAPI"));
        assert!(missions.contains("\"dataset\":\"api_synthetic\""));
        assert!(!missions.contains("session_token"));
        assert!(!missions.contains("csrf_token"));
        assert!(manager
            .g5_session_status_json()
            .contains("\"grant_active\":true"));

        let revoked = manager.g5_mission_read_grant_revoke();
        assert!(revoked.contains("\"grant_active\":false"));
        assert!(manager
            .g5_mission_read_grant_revoke()
            .contains("\"grant_active\":false"));
        assert!(manager.g5_missions_list().contains("concessão de leitura"));
        assert!(manager
            .g5_mission_read_grant_create()
            .contains("\"grant_active\":true"));
        let closed = manager.g5_session_close();
        assert!(closed.contains("\"session_active\":false"));
        assert!(!closed.contains("session_token"));
        assert!(manager
            .g5_session_open("senha-sintetica-rust-mac003".to_owned())
            .contains("\"session_active\":true"));
        assert!(manager
            .g5_session_status_json()
            .contains("\"grant_active\":false"));
        assert!(manager.g5_missions_list().contains("concessão de leitura"));
        assert!(manager
            .g5_mission_read_grant_create()
            .contains("\"grant_active\":true"));
        assert!(manager
            .g5_missions_list()
            .contains("Missão sintética Rust → FastAPI"));
        assert!(manager
            .g5_session_close()
            .contains("\"session_active\":false"));
        assert_eq!(process.stop(), 0);
        session.revoke();
        for suffix in ["", "-wal", "-shm"] {
            let path = PathBuf::from(format!("{}{suffix}", database_path.display()));
            let _ = fs::remove_file(path);
        }
        let _ = fs::remove_dir(session.directory_path());
    }

    #[test]
    fn stopped_starting_ready_stopping_stopped() {
        let manager = manager();
        assert_eq!(manager.snapshot().state, RuntimeState::Stopped);
        let started = manager.start_runtime().unwrap();
        assert_eq!(started.state, RuntimeState::Starting);
        let ready = manager.wait_for_state(RuntimeState::Ready, Duration::from_secs(2));
        assert_eq!(ready.runtime_instance_id, started.runtime_instance_id);
        assert!(ready.pid.is_some());
        assert!(ready.ready_at_unix_ms.is_some());
        let transport =
            manager.wait_for_transport_state(TransportState::Ready, Duration::from_secs(2));
        assert_eq!(transport.runtime_instance_id, ready.runtime_instance_id);
        assert_eq!(transport.endpoint_type, Some("uds"));
        assert_eq!(transport.protocol_version.as_deref(), Some("2"));
        let transport_session = manager.transport_session_for_test();
        assert_eq!(
            fs::symlink_metadata(transport_session.socket_path_for_test())
                .unwrap()
                .permissions()
                .mode()
                & 0o777,
            0o600
        );
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
        manager_a.start_runtime().unwrap();
        manager_b.start_runtime().unwrap();
        manager_a.wait_for_state(RuntimeState::Ready, Duration::from_secs(2));
        manager_b.wait_for_state(RuntimeState::Ready, Duration::from_secs(2));
        manager_a.wait_for_transport_state(TransportState::Ready, Duration::from_secs(2));
        manager_b.wait_for_transport_state(TransportState::Ready, Duration::from_secs(2));

        let session_a = manager_a.transport_session_for_test();
        let session_b = manager_b.transport_session_for_test();
        assert_eq!(
            session_a.probe_other_session_for_test(&session_b),
            Err(crate::transport::TransportError::PeerRejected)
        );
        assert_eq!(
            session_b.probe_other_session_for_test(&session_a),
            Err(crate::transport::TransportError::PeerRejected)
        );

        manager_a.stop_and_wait().unwrap();
        assert_eq!(
            session_a.probe(),
            Err(crate::transport::TransportError::Inactive)
        );
        assert!(session_a.is_clean_for_test());
        assert_eq!(manager_b.transport_status_json().contains("READY"), true);

        let generation_b = manager_a.start_runtime().unwrap();
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
    fn concurrent_probes_are_serialized_and_publish_first_completed_result() {
        let manager = Arc::new(manager());
        manager.start_runtime().unwrap();
        manager.wait_for_state(RuntimeState::Ready, Duration::from_secs(2));
        manager.wait_for_transport_state(TransportState::Ready, Duration::from_secs(2));

        let barrier = Arc::new(Barrier::new(3));
        let mut workers = Vec::new();
        for _ in 0..2 {
            let manager = Arc::clone(&manager);
            let barrier = Arc::clone(&barrier);
            workers.push(thread::spawn(move || {
                barrier.wait();
                manager.probe_transport_now()
            }));
        }
        barrier.wait();
        for worker in workers {
            assert_eq!(worker.join().unwrap().state, TransportState::Ready);
        }
        assert!(manager.transport_status_json().contains("READY"));
        manager.stop_and_wait().unwrap();
        assert_clean(&manager);
    }

    #[test]
    fn runtime_ready_requires_authenticated_transport() {
        let manager = manager();
        manager
            .start_mode_for_test(HelperMode::MissingTransport)
            .unwrap();
        let runtime = manager.wait_for_state(RuntimeState::Failed, Duration::from_secs(2));
        let transport =
            manager.wait_for_transport_state(TransportState::Failed, Duration::from_secs(2));
        assert_eq!(runtime.state, RuntimeState::Failed);
        assert_eq!(runtime.failure_category, Some("endpoint_unavailable"));
        assert_eq!(transport.runtime_instance_id, runtime.runtime_instance_id);
        assert_eq!(transport.error_category, Some("endpoint_unavailable"));
        assert_eq!(
            manager.stop_and_wait().unwrap().state,
            RuntimeState::Stopped
        );
        assert_clean(&manager);
    }

    #[test]
    fn late_probe_result_cannot_restore_transport_after_stop_invalidation() {
        let manager = manager();
        let instance_id = "stop-race-instance";
        let session = TransportSession::create(instance_id).unwrap();
        {
            let mut inner = lock_inner(&manager.shared);
            inner.snapshot = RuntimeSnapshot {
                state: RuntimeState::Ready,
                runtime_instance_id: Some(instance_id.to_owned()),
                pid: Some(1),
                started_at_unix_ms: Some(1),
                ready_at_unix_ms: Some(1),
                exit_code: None,
                failure_category: None,
            };
            inner.transport_snapshot = TransportSnapshot {
                state: TransportState::ProvingInstance,
                runtime_instance_id: Some(instance_id.to_owned()),
                endpoint_type: Some("uds"),
                protocol_version: None,
                error_category: None,
            };
            inner.transport_session = Some(Arc::clone(&session));
        }
        session.deactivate();
        {
            let mut inner = lock_inner(&manager.shared);
            inner.transport_snapshot.state = TransportState::Disconnected;
        }

        complete_transport_probe(&manager.shared, instance_id, Arc::clone(&session));
        assert_eq!(
            lock_inner(&manager.shared).transport_snapshot.state,
            TransportState::Disconnected
        );
        session.revoke();
        assert!(session.is_clean_for_test());
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

        manager.start_runtime().unwrap();
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
        let first = manager.start_runtime().unwrap();
        let second = manager.start_runtime();
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
        let first = manager.start_runtime().unwrap();
        manager.wait_for_state(RuntimeState::Ready, Duration::from_secs(2));
        assert_eq!(
            manager.start_runtime().unwrap_err(),
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
        manager.start_runtime().unwrap();
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

        let restarted = manager.restart_runtime().unwrap();
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
        let previous = manager.start_runtime().unwrap();
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
        manager.start_runtime().unwrap();
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
        let started = manager.start_runtime().unwrap();
        assert_eq!(started.state, RuntimeState::Starting);
        let ready = manager.wait_for_state(RuntimeState::Ready, Duration::from_secs(8));
        assert_eq!(ready.runtime_instance_id, started.runtime_instance_id);
        let transport =
            manager.wait_for_transport_state(TransportState::Ready, Duration::from_secs(8));
        assert_eq!(transport.runtime_instance_id, ready.runtime_instance_id);
        assert_eq!(transport.protocol_version.as_deref(), Some("2"));
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
            let transport_session = TransportSession::create(&instance_id).unwrap();
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
                .current_dir(transport_session.directory_path())
                .stdin(Stdio::piped())
                .stdout(Stdio::null())
                .stderr(Stdio::null())
                .spawn()
                .expect("unrelated synthetic process starts");
            let mut stdin = child.stdin.take().unwrap();
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

        manager.start_runtime().unwrap();
        manager.wait_for_state(RuntimeState::Ready, Duration::from_secs(2));
        external.assert_alive();
        manager.stop_and_wait().unwrap();
        external.assert_alive();

        manager
            .start_mode_for_test(HelperMode::CrashAfterReady)
            .unwrap();
        manager.wait_for_state(RuntimeState::Crashed, Duration::from_secs(2));
        external.assert_alive();
        manager.restart_runtime().unwrap();
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
                results.lock().unwrap().push(manager.start_runtime());
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
            start_manager.start_runtime()
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
            restart_manager.restart_runtime()
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
            manager.restart_runtime().unwrap_err(),
            ManagerError::InvalidState
        );
        assert_eq!(manager.snapshot().state, RuntimeState::Stopped);
    }

    #[test]
    fn supervisor_eof_during_starting_fails_without_readiness() {
        let manager = manager();
        manager.start_mode_for_test(HelperMode::SlowReady).unwrap();
        let session = manager.transport_session_for_test();
        let started = Instant::now();
        manager.close_control_for_test();
        let failed = manager.wait_for_state(RuntimeState::Failed, Duration::from_secs(1));
        assert_eq!(failed.failure_category, Some("supervisor_lost"));
        assert_eq!(failed.exit_code, Some(SUPERVISOR_LOST_EXIT));
        assert_eq!(failed.ready_at_unix_ms, None);
        assert!(started.elapsed() < Duration::from_millis(350));
        assert!(session.is_clean_for_test());
        assert_clean(&manager);
    }

    #[test]
    fn supervisor_eof_after_ready_revokes_capability_and_reaps_child() {
        let manager = manager();
        manager.start_runtime().unwrap();
        let ready = manager.wait_for_state(RuntimeState::Ready, Duration::from_secs(2));
        let session = manager.transport_session_for_test();
        manager.wait_for_transport_state(TransportState::Ready, Duration::from_secs(2));
        let started = Instant::now();
        manager.close_control_for_test();
        let stopped = manager.wait_for_state(RuntimeState::Stopped, Duration::from_secs(1));
        assert_eq!(stopped.runtime_instance_id, ready.runtime_instance_id);
        assert_eq!(stopped.failure_category, Some("supervisor_lost"));
        assert_eq!(stopped.exit_code, Some(SUPERVISOR_LOST_EXIT));
        assert!(started.elapsed() < Duration::from_millis(350));
        assert_eq!(
            manager.transport_status_json().contains("DISCONNECTED"),
            true
        );
        assert_eq!(
            session.probe(),
            Err(crate::transport::TransportError::Inactive)
        );
        assert!(session.is_clean_for_test());
        assert_clean(&manager);
        assert_eq!(
            manager.stop_and_wait().unwrap().state,
            RuntimeState::Stopped
        );
    }

    #[test]
    fn eof_and_stop_race_is_idempotent() {
        let manager = manager();
        manager.start_runtime().unwrap();
        manager.wait_for_state(RuntimeState::Ready, Duration::from_secs(2));
        manager.wait_for_transport_state(TransportState::Ready, Duration::from_secs(2));
        let session = manager.transport_session_for_test();
        let close_ack = manager.queue_control_close_for_test();
        let stopped = manager.stop_and_wait().unwrap();
        close_ack
            .recv_timeout(Duration::from_secs(1))
            .expect("control close request completed");
        assert_eq!(stopped.state, RuntimeState::Stopped);
        assert!(matches!(
            stopped.failure_category,
            None | Some("supervisor_lost")
        ));
        assert_eq!(
            manager.stop_and_wait().unwrap().state,
            RuntimeState::Stopped
        );
        assert!(session.is_clean_for_test());
        assert_clean(&manager);
    }

    #[test]
    fn repeated_supervisor_loss_observation_is_idempotent() {
        let (sender, receiver) = mpsc::channel();
        let live = AtomicBool::new(true);
        drop(sender);

        assert_eq!(
            next_control_signal(&receiver, &live),
            Some(ControlSignal::SupervisorLost)
        );
        assert_eq!(
            next_control_signal(&receiver, &live),
            Some(ControlSignal::SupervisorLost)
        );
    }

    #[test]
    fn supervisor_eof_during_proof_request_closes_child_without_late_response() {
        let manager = manager();
        manager.start_runtime().unwrap();
        manager.wait_for_state(RuntimeState::Ready, Duration::from_secs(2));
        manager.wait_for_transport_state(TransportState::Ready, Duration::from_secs(2));
        let session = manager.transport_session_for_test();
        let mut stream = UnixStream::connect(session.socket_path_for_test()).unwrap();
        let body = "00".repeat(32);
        let header = format!(
            "POST /v1/instance-proof HTTP/1.1\r\nHost: jarvis.local\r\nConnection: close\r\nContent-Length: {}\r\nContent-Type: text/plain\r\n\r\n",
            body.len()
        );
        stream.write_all(header.as_bytes()).unwrap();
        stream.write_all(&body.as_bytes()[..16]).unwrap();
        let close_ack = manager.queue_control_close_for_test();
        close_ack
            .recv_timeout(Duration::from_secs(1))
            .expect("supervisor dropped control pipe");
        let _ = stream.write_all(&body.as_bytes()[16..]);
        stream
            .set_read_timeout(Some(Duration::from_secs(1)))
            .unwrap();
        let mut late_response = Vec::new();
        let mut chunk = [0_u8; 256];
        loop {
            match stream.read(&mut chunk) {
                Ok(0) => break,
                Ok(count) => late_response.extend_from_slice(&chunk[..count]),
                Err(error)
                    if matches!(
                        error.kind(),
                        io::ErrorKind::ConnectionReset
                            | io::ErrorKind::TimedOut
                            | io::ErrorKind::WouldBlock
                    ) =>
                {
                    break;
                }
                Err(error) => panic!("unexpected proof socket error: {error}"),
            }
        }
        assert!(late_response.is_empty(), "proof response arrived after EOF");
        let stopped = manager.wait_for_state(RuntimeState::Stopped, Duration::from_secs(1));
        assert_eq!(stopped.failure_category, Some("supervisor_lost"));
        assert_eq!(
            manager.transport_status_json().contains("DISCONNECTED"),
            true
        );
        assert!(session.is_clean_for_test());
        assert_clean(&manager);
    }

    #[test]
    fn hard_parent_loss_closes_inherited_control_pipe_and_child_exits_bounded() {
        let instance_id = new_instance_id();
        let session = TransportSession::create(&instance_id).unwrap();
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
            .env(HELPER_MODE_ENV, "normal")
            .current_dir(session.directory_path())
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
            .unwrap();
        let mut stdin = child.stdin.take().unwrap();
        session.write_child_init(&mut stdin).unwrap();
        let stdout = child.stdout.take().unwrap();
        let (line_sender, line_receiver) = mpsc::channel();
        thread::spawn(move || {
            let mut stdout = BufReader::new(stdout);
            loop {
                let mut line = String::new();
                match stdout.read_line(&mut line) {
                    Ok(0) => return,
                    Ok(_) => {
                        if line_sender.send(line).is_err() {
                            return;
                        }
                    }
                    Err(_) => return,
                }
            }
        });
        let deadline = Instant::now() + Duration::from_secs(2);
        let mut output_lines = Vec::new();
        let ready = loop {
            let remaining = deadline.saturating_duration_since(Instant::now());
            if remaining.is_zero() {
                let _ = child.kill();
                let _ = child.wait();
                panic!("helper did not announce readiness; output={output_lines:?}");
            }
            match line_receiver.recv_timeout(remaining) {
                Ok(line) if line.trim() == format!("{READY_PREFIX}{instance_id}") => break line,
                Ok(line) => output_lines.push(line),
                Err(RecvTimeoutError::Disconnected) => {
                    let status = child.wait().unwrap();
                    let mut stderr = String::new();
                    child
                        .stderr
                        .take()
                        .unwrap()
                        .read_to_string(&mut stderr)
                        .unwrap();
                    panic!("helper exited before readiness: status={status}, stderr={stderr}, output={output_lines:?}");
                }
                Err(RecvTimeoutError::Timeout) => {}
            }
        };
        assert_eq!(ready.trim(), format!("{READY_PREFIX}{instance_id}"));
        writeln!(stdin, "{ACK_PREFIX}{instance_id}").unwrap();
        stdin.flush().unwrap();
        drop(stdin);

        let deadline = Instant::now() + Duration::from_secs(1);
        let status = loop {
            if let Some(status) = child.try_wait().unwrap() {
                break status;
            }
            assert!(
                Instant::now() < deadline,
                "helper did not exit after pipe EOF"
            );
            thread::sleep(POLL_INTERVAL);
        };
        assert_eq!(status.code(), Some(SUPERVISOR_LOST_EXIT));
        assert!(fs::symlink_metadata(session.socket_path_for_test()).is_err());
        session.revoke();
        assert!(session.is_clean_for_test());
    }

    #[test]
    #[ignore = "MAC-002.1 lifecycle stress; run explicitly"]
    fn stress_normal_transport_lifecycle_500_rounds() {
        for round in 0..500 {
            let manager = manager();
            manager
                .start_runtime()
                .unwrap_or_else(|error| panic!("round {round}: start failed: {error:?}"));
            manager.wait_for_state(RuntimeState::Ready, Duration::from_secs(2));
            manager.wait_for_transport_state(TransportState::Ready, Duration::from_secs(2));
            assert_eq!(
                manager.probe_transport_now().state,
                TransportState::Ready,
                "round {round}: authenticated request failed"
            );
            let session = manager.transport_session_for_test();
            assert_eq!(
                manager.stop_and_wait().unwrap().state,
                RuntimeState::Stopped,
                "round {round}: stop failed"
            );
            assert!(session.is_clean_for_test(), "round {round}: UDS remained");
            assert_clean(&manager);
        }
    }

    #[test]
    #[ignore = "MAC-002.1 EOF stress; run explicitly"]
    fn stress_supervisor_eof_200_rounds() {
        for round in 0..200 {
            let manager = manager();
            manager.start_runtime().unwrap();
            manager.wait_for_state(RuntimeState::Ready, Duration::from_secs(2));
            manager.wait_for_transport_state(TransportState::Ready, Duration::from_secs(2));
            let session = manager.transport_session_for_test();
            let started = Instant::now();
            manager.close_control_for_test();
            let stopped = manager.wait_for_state(RuntimeState::Stopped, Duration::from_secs(1));
            assert_eq!(
                stopped.failure_category,
                Some("supervisor_lost"),
                "round {round}"
            );
            assert!(
                started.elapsed() < Duration::from_millis(350),
                "round {round}"
            );
            assert!(session.is_clean_for_test(), "round {round}: UDS remained");
            assert_clean(&manager);
        }
    }
}
