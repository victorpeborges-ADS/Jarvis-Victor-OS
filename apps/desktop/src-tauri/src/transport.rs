use std::{
    env, fs, io,
    io::{BufRead, Read, Write},
    path::{Path, PathBuf},
    sync::{
        atomic::{AtomicBool, AtomicU32, AtomicU64, AtomicUsize, Ordering},
        Arc, Condvar, Mutex, MutexGuard,
    },
    time::{Duration, Instant},
};

#[cfg(unix)]
use std::os::unix::{
    ffi::OsStrExt,
    fs::{MetadataExt, PermissionsExt},
    io::AsRawFd,
    net::{UnixListener, UnixStream},
};

#[cfg(unix)]
use std::os::raw::{c_char, c_int, c_uint};

const INIT_PREFIX: &[u8] = b"JARVIS_TRANSPORT_INIT ";
const SOCKET_LEAF: &[u8] = b"runtime.sock\0";
pub(crate) const PROTOCOL_VERSION: &str = "3";
const RUNTIME_KIND: &str = "jarvis-synthetic";
const BUILD_ID: &str = "g6-mac-002-2-encrypted-uds-v3";
const HEALTH_ROUTE: &str = "/v1/health";
const VERSION_ROUTE: &str = "/v1/version";
const PROOF_ROUTE: &str = "/v1/instance-proof";
const APPLICATION_ENVELOPE_ROUTE: &str = "/v3/secure";
const APP_SESSION_OPEN_ROUTE: &str = "/v1/app/session/open";
const APP_SESSION_CLOSE_ROUTE: &str = "/v1/app/session/close";
const APP_GRANT_CREATE_ROUTE: &str = "/v1/app/grants/mission-read";
const APP_GRANT_REVOKE_ROUTE: &str = "/v1/app/grants/mission-read/revoke";
const APP_MISSIONS_LIST_ROUTE: &str = "/v1/app/missions/list";
const APP_CAPTURE_CREATE_ROUTE: &str = "/v1/app/captures/create";
const APP_CAPTURE_EDIT_ROUTE: &str = "/v1/app/captures/edit";
const APP_CAPTURE_DELETE_ROUTE: &str = "/v1/app/captures/delete";
const APP_CAPTURE_LIST_ROUTE: &str = "/v1/app/captures/list";
const APP_CAPTURE_CLEAR_ROUTE: &str = "/v1/app/captures/clear";
const APP_CONNECTORS_STATUS_ROUTE: &str = "/v1/app/connectors/status";
const APP_REVIEW_GRANT_ROUTE: &str = "/v1/app/grants/mission-review";
const APP_REVIEW_GRANT_REVOKE_ROUTE: &str = "/v1/app/grants/mission-review/revoke";
const APP_REVIEWS_PENDING_ROUTE: &str = "/v1/app/reviews/pending";
const APP_REVIEW_DRAFT_ROUTE: &str = "/v1/app/reviews/draft";
const APP_REVIEW_DETAIL_ROUTE: &str = "/v1/app/reviews/detail";
const APP_REVIEW_APPROVE_ROUTE: &str = "/v1/app/reviews/approve";
const APP_WORKFLOW_SUBMIT_ROUTE: &str = "/v1/app/workflows/submit";
const APP_WORKFLOW_LIST_ROUTE: &str = "/v1/app/workflows/list";
const APP_WORKFLOW_DETAIL_ROUTE: &str = "/v1/app/workflows/detail";
const APP_WORKFLOW_APPROVE_ROUTE: &str = "/v1/app/workflows/approve";
const APP_WORKFLOW_EXECUTE_ROUTE: &str = "/v1/app/workflows/execute";
const APP_WORKFLOW_PAUSE_ROUTE: &str = "/v1/app/workflows/pause";
const APP_WORKFLOW_RESUME_ROUTE: &str = "/v1/app/workflows/resume";
const APP_WORKFLOW_CANCEL_ROUTE: &str = "/v1/app/workflows/cancel";
const APP_ROUTES: [&str; 25] = [
    APP_SESSION_OPEN_ROUTE,
    APP_SESSION_CLOSE_ROUTE,
    APP_GRANT_CREATE_ROUTE,
    APP_GRANT_REVOKE_ROUTE,
    APP_MISSIONS_LIST_ROUTE,
    APP_CAPTURE_CREATE_ROUTE,
    APP_CAPTURE_EDIT_ROUTE,
    APP_CAPTURE_DELETE_ROUTE,
    APP_CAPTURE_LIST_ROUTE,
    APP_CAPTURE_CLEAR_ROUTE,
    APP_CONNECTORS_STATUS_ROUTE,
    APP_REVIEW_GRANT_ROUTE,
    APP_REVIEW_GRANT_REVOKE_ROUTE,
    APP_REVIEWS_PENDING_ROUTE,
    APP_REVIEW_DRAFT_ROUTE,
    APP_REVIEW_DETAIL_ROUTE,
    APP_REVIEW_APPROVE_ROUTE,
    APP_WORKFLOW_SUBMIT_ROUTE,
    APP_WORKFLOW_LIST_ROUTE,
    APP_WORKFLOW_DETAIL_ROUTE,
    APP_WORKFLOW_APPROVE_ROUTE,
    APP_WORKFLOW_EXECUTE_ROUTE,
    APP_WORKFLOW_PAUSE_ROUTE,
    APP_WORKFLOW_RESUME_ROUTE,
    APP_WORKFLOW_CANCEL_ROUTE,
];
const CONNECT_TIMEOUT: Duration = Duration::from_millis(350);
const REQUEST_TIMEOUT: Duration = Duration::from_millis(900);
const SERVER_REQUEST_TIMEOUT: Duration = Duration::from_millis(500);
const MAX_REQUEST_HEADER_BYTES: usize = 1024;
const MAX_REQUEST_BODY_BYTES: usize = 128;
const MAX_APP_REQUEST_BODY_BYTES: usize = 1024;
const MAX_RESPONSE_HEADER_BYTES: usize = 2048;
const MAX_RESPONSE_BODY_BYTES: usize = 2048;
const MAX_CONTROL_RESPONSE_BODY_BYTES: usize = 2048;
const MAX_INIT_BYTES: usize = 1024;
const SECRET_BYTES: usize = 32;
const NONCE_BYTES: usize = 32;
const ENVELOPE_NONCE_BYTES: usize = 16;
const ENVELOPE_SEQUENCE_BYTES: usize = 8;
const ENVELOPE_TAG_BYTES: usize = 32;
const ENVELOPE_VERSION: u8 = 3;
const MAX_ENVELOPE_REQUEST_BYTES: usize = MAX_APP_REQUEST_BODY_BYTES + 256;
const MAX_ENVELOPE_RESPONSE_BYTES: usize =
    MAX_RESPONSE_BODY_BYTES + ENVELOPE_NONCE_BYTES + ENVELOPE_TAG_BYTES + 7;

#[cfg(unix)]
#[link(name = "System")]
unsafe extern "C" {
    fn unlinkat(directory_fd: c_int, path: *const c_char, flags: c_int) -> c_int;
    fn umask(mask: c_uint) -> c_uint;
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
struct DirectoryIdentity {
    dev: u64,
    ino: u64,
}

impl DirectoryIdentity {
    fn from_metadata(metadata: &fs::Metadata) -> Self {
        Self {
            dev: metadata.dev(),
            ino: metadata.ino(),
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum TransportState {
    Disconnected,
    Discovering,
    ProvingInstance,
    Ready,
    Incompatible,
    Failed,
}

impl TransportState {
    fn as_str(self) -> &'static str {
        match self {
            Self::Disconnected => "DISCONNECTED",
            Self::Discovering => "DISCOVERING",
            Self::ProvingInstance => "PROVING_INSTANCE",
            Self::Ready => "READY",
            Self::Incompatible => "INCOMPATIBLE",
            Self::Failed => "FAILED",
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct TransportSnapshot {
    pub(crate) state: TransportState,
    pub(crate) runtime_instance_id: Option<String>,
    pub(crate) endpoint_type: Option<&'static str>,
    pub(crate) protocol_version: Option<String>,
    pub(crate) error_category: Option<&'static str>,
}

impl TransportSnapshot {
    pub(crate) fn disconnected() -> Self {
        Self {
            state: TransportState::Disconnected,
            runtime_instance_id: None,
            endpoint_type: None,
            protocol_version: None,
            error_category: None,
        }
    }

    pub(crate) fn discovering(instance_id: &str) -> Self {
        Self {
            state: TransportState::Discovering,
            runtime_instance_id: Some(instance_id.to_owned()),
            endpoint_type: Some("uds"),
            protocol_version: None,
            error_category: None,
        }
    }

    pub(crate) fn json(&self) -> String {
        format!(
            "{{\"state\":{},\"runtime_instance_id\":{},\"endpoint_type\":{},\"protocol_version\":{},\"error_category\":{}}}",
            json_string(self.state.as_str()),
            json_optional_string(self.runtime_instance_id.as_deref()),
            json_optional_string(self.endpoint_type),
            json_optional_string(self.protocol_version.as_deref()),
            json_optional_string(self.error_category),
        )
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum TransportError {
    Inactive,
    EndpointUnavailable,
    Timeout,
    MalformedResponse,
    ResponseTooLarge,
    ApplicationRequestTooLarge,
    HttpRejected,
    ProofRejected,
    PeerRejected,
    IncompatibleVersion,
    OsCryptoUnavailable,
    SetupFailed,
}

impl TransportError {
    pub(crate) fn category(self) -> &'static str {
        match self {
            Self::Inactive => "generation_inactive",
            Self::EndpointUnavailable => "endpoint_unavailable",
            Self::Timeout => "request_timeout",
            Self::MalformedResponse => "malformed_response",
            Self::ResponseTooLarge => "response_too_large",
            Self::ApplicationRequestTooLarge => "application_request_too_large",
            Self::HttpRejected => "http_rejected",
            Self::ProofRejected => "proof_rejected",
            Self::PeerRejected => "peer_rejected",
            Self::IncompatibleVersion => "incompatible_version",
            Self::OsCryptoUnavailable => "os_crypto_unavailable",
            Self::SetupFailed => "transport_setup_failed",
        }
    }

    pub(crate) fn incompatible(self) -> bool {
        self == Self::IncompatibleVersion
    }
}

struct RequestLockState {
    held: bool,
    waiters: usize,
}

struct RequestLockGuard<'a> {
    session: &'a TransportSession,
}

impl Drop for RequestLockGuard<'_> {
    fn drop(&mut self) {
        let mut state = lock(&self.session.request_state);
        self.session
            .request_lock_depth
            .fetch_sub(1, Ordering::AcqRel);
        state.held = false;
        self.session.request_cv.notify_all();
    }
}

/// Native-only transport capability. The endpoint and key are never serialized to Tauri IPC.
pub(crate) struct TransportSession {
    instance_id: String,
    socket_path: PathBuf,
    directory: PathBuf,
    directory_handle: fs::File,
    directory_identity: DirectoryIdentity,
    secret: Mutex<Option<[u8; SECRET_BYTES]>>,
    expected_peer_pid: AtomicU32,
    envelope_sequence: AtomicU64,
    active: AtomicBool,
    cleanup_done: AtomicBool,
    /// Logical transaction lock. The mutex is not held across socket IO; `held`
    /// stays true until the guard drops, and waiters block on `request_cv`.
    request_state: Mutex<RequestLockState>,
    request_cv: Condvar,
    request_lock_depth: AtomicUsize,
    #[cfg(test)]
    transaction_barrier: Mutex<Option<Arc<dyn Fn(&str) + Send + Sync>>>,
}

impl TransportSession {
    pub(crate) fn create(instance_id: &str) -> Result<Arc<Self>, TransportError> {
        let mut secret = [0_u8; SECRET_BYTES];
        let mut name = [0_u8; 16];
        os_random(&mut secret)?;
        if let Err(error) = os_random(&mut name) {
            secret.fill(0);
            return Err(error);
        }

        let directory = env::temp_dir().join(format!(".jv-{}", hex(&name)));
        name.fill(0);
        fs::create_dir(&directory).map_err(|_| {
            secret.fill(0);
            TransportError::SetupFailed
        })?;
        if fs::set_permissions(&directory, fs::Permissions::from_mode(0o700)).is_err() {
            secret.fill(0);
            return Err(TransportError::SetupFailed);
        }
        let directory_handle = fs::File::open(&directory).map_err(|_| {
            secret.fill(0);
            TransportError::SetupFailed
        })?;
        let directory_identity = directory_handle
            .metadata()
            .map(|metadata| DirectoryIdentity::from_metadata(&metadata))
            .map_err(|_| TransportError::SetupFailed)?;
        let named_identity = fs::symlink_metadata(&directory)
            .map(|metadata| DirectoryIdentity::from_metadata(&metadata));
        if named_identity.ok() != Some(directory_identity) {
            secret.fill(0);
            return Err(TransportError::SetupFailed);
        }
        let socket_path = directory.join("runtime.sock");
        if socket_path.as_os_str().as_bytes().len() >= 104 {
            secret.fill(0);
            return Err(TransportError::SetupFailed);
        }

        Ok(Arc::new(Self {
            instance_id: instance_id.to_owned(),
            socket_path,
            directory,
            directory_handle,
            directory_identity,
            secret: Mutex::new(Some(secret)),
            expected_peer_pid: AtomicU32::new(test_default_peer_pid()),
            envelope_sequence: AtomicU64::new(0),
            active: AtomicBool::new(true),
            cleanup_done: AtomicBool::new(false),
            request_state: Mutex::new(RequestLockState {
                held: false,
                waiters: 0,
            }),
            request_cv: Condvar::new(),
            request_lock_depth: AtomicUsize::new(0),
            #[cfg(test)]
            transaction_barrier: Mutex::new(None),
        }))
    }

    pub(crate) fn write_child_init(&self, writer: &mut impl Write) -> Result<(), TransportError> {
        let _request = self.lock_request();
        let secret = lock(&self.secret);
        let Some(secret) = secret.as_ref() else {
            return Err(TransportError::Inactive);
        };
        writer
            .write_all(INIT_PREFIX)
            .and_then(|_| writer.write_all(self.instance_id.as_bytes()))
            .and_then(|_| writer.write_all(b"\t"))
            .and_then(|_| write_hex(writer, secret))
            .and_then(|_| writer.write_all(b"\t"))
            .and_then(|_| {
                write!(
                    writer,
                    "{}\t{}",
                    self.directory_identity.dev, self.directory_identity.ino
                )
            })
            .and_then(|_| writer.write_all(b"\n"))
            .and_then(|_| writer.flush())
            .map_err(|_| TransportError::SetupFailed)
    }

    pub(crate) fn probe(&self) -> Result<(), TransportError> {
        self.probe_endpoint(&self.socket_path)
    }

    pub(crate) fn set_expected_peer_pid(&self, pid: u32) -> Result<(), TransportError> {
        if pid == 0 {
            return Err(TransportError::PeerRejected);
        }
        self.expected_peer_pid.store(pid, Ordering::Release);
        Ok(())
    }

    fn probe_endpoint(&self, endpoint: &std::path::Path) -> Result<(), TransportError> {
        let _serial = self.lock_request();
        self.probe_endpoint_locked(endpoint)
    }

    fn probe_endpoint_locked(&self, endpoint: &std::path::Path) -> Result<(), TransportError> {
        self.ensure_active()?;
        let health = self.exchange_at(endpoint, Verb::Get, HEALTH_ROUTE, b"")?;
        if health != b"ok\n" {
            return Err(TransportError::MalformedResponse);
        }

        let version = self.exchange_at(endpoint, Verb::Get, VERSION_ROUTE, b"")?;
        let version = parse_version(&version)?;
        if version.protocol != PROTOCOL_VERSION
            || version.runtime_kind != RUNTIME_KIND
            || version.build != BUILD_ID
        {
            return Err(TransportError::IncompatibleVersion);
        }

        let mut nonce = [0_u8; NONCE_BYTES];
        os_random(&mut nonce)?;
        let proof_body = hex(&nonce);
        let response =
            self.exchange_at(endpoint, Verb::Post, PROOF_ROUTE, proof_body.as_bytes())?;
        nonce.fill(0);
        self.verify_proof(&version, &proof_body, &response)?;
        self.ensure_active()?;
        Ok(())
    }

    /// Calls one closed MAC-003 operation after revalidating the runtime proof.
    /// The WebView cannot provide a path or HTTP method.
    pub(crate) fn call_g5_application(
        &self,
        route: &'static str,
        body: &[u8],
    ) -> Result<Vec<u8>, TransportError> {
        self.call_g5_application_after_probe(route, body, || {})
    }

    #[cfg(feature = "mac003-production-supervisor-test")]
    pub(crate) fn call_g5_application_after_probe_for_test(
        &self,
        route: &'static str,
        body: &[u8],
        after_probe: impl FnOnce(),
    ) -> Result<Vec<u8>, TransportError> {
        self.call_g5_application_after_probe(route, body, after_probe)
    }

    fn call_g5_application_after_probe(
        &self,
        route: &'static str,
        body: &[u8],
        after_probe: impl FnOnce(),
    ) -> Result<Vec<u8>, TransportError> {
        if !APP_ROUTES.contains(&route) {
            return Err(TransportError::HttpRejected);
        }
        if body.len() > MAX_APP_REQUEST_BODY_BYTES {
            return Err(TransportError::ApplicationRequestTooLarge);
        }
        let _serial = self.lock_request();
        self.ensure_active()?;
        #[cfg(test)]
        self.pause_transaction_for_test("admitted");
        self.probe_endpoint_locked(&self.socket_path)?;
        after_probe();
        let nonce = self.next_envelope_nonce_locked()?;
        let envelope = self.seal_application_request_locked(route, body, &nonce)?;
        #[cfg(test)]
        self.pause_transaction_for_test("sealed");
        let response = self.exchange_at(
            &self.socket_path,
            Verb::Post,
            APPLICATION_ENVELOPE_ROUTE,
            &envelope,
        )?;
        // Response bytes are local and the transaction lock is still held.
        // Production builds omit this pause.
        #[cfg(test)]
        self.pause_transaction_for_test("received");
        let result = self.open_application_response(&response, &nonce)?;
        // Records that opening finished before the guard drops. Not a wait.
        #[cfg(test)]
        self.pause_transaction_for_test("opened");
        self.ensure_active()?;
        Ok(result)
    }

    #[cfg(test)]
    pub(crate) fn probe_other_session_for_test(
        &self,
        other: &TransportSession,
    ) -> Result<(), TransportError> {
        self.probe_endpoint(&other.socket_path)
    }

    #[cfg(any(test, feature = "mac003-production-supervisor-test"))]
    pub(crate) fn is_clean_for_test(&self) -> bool {
        !self.active.load(Ordering::Acquire)
            && lock(&self.secret).is_none()
            && fs::symlink_metadata(&self.socket_path).is_err()
    }

    #[cfg(test)]
    pub(crate) fn instance_id_for_test(&self) -> &str {
        &self.instance_id
    }

    pub(crate) fn directory_path(&self) -> &Path {
        &self.directory
    }

    pub(crate) fn path_matches_handle(&self) -> bool {
        fs::symlink_metadata(&self.directory)
            .map(|metadata| {
                metadata.file_type().is_dir()
                    && DirectoryIdentity::from_metadata(&metadata) == self.directory_identity
            })
            .unwrap_or(false)
    }

    #[cfg(test)]
    pub(crate) fn socket_path_for_test(&self) -> &Path {
        &self.socket_path
    }

    pub(crate) fn revoke(&self) {
        self.deactivate();
        self.cleanup_endpoint();
    }

    pub(crate) fn deactivate(&self) {
        // Wait for an in-flight probe or G5 transaction before retiring the
        // capability. Callers of this method do not already hold `request_lock`;
        // acquiring it here cannot deadlock with `call_g5_application` or `probe`,
        // which release the manager lock before taking this one. The wait is
        // bounded by the connect and request timeouts of the transaction.
        let _request = self.lock_request();
        self.deactivate_locked();
    }

    fn deactivate_locked(&self) {
        // Inactivity, secret destruction, and sequence retirement stay in one
        // capability critical section. The counter is parked at u64::MAX.
        let mut secret = lock(&self.secret);
        self.active.store(false, Ordering::Release);
        if let Some(mut secret) = secret.take() {
            secret.fill(0);
            std::hint::black_box(secret);
        }
        self.envelope_sequence.store(u64::MAX, Ordering::Release);
    }

    fn cleanup_endpoint(&self) {
        if self.cleanup_done.swap(true, Ordering::AcqRel) {
            return;
        }
        unlink_socket_at(&self.directory_handle);
    }

    fn ensure_active(&self) -> Result<(), TransportError> {
        if self.active.load(Ordering::Acquire) {
            Ok(())
        } else {
            Err(TransportError::Inactive)
        }
    }

    fn exchange_at(
        &self,
        endpoint: &std::path::Path,
        verb: Verb,
        route: &'static str,
        body: &[u8],
    ) -> Result<Vec<u8>, TransportError> {
        // The caller holds the G5 transaction lock from this check through the
        // write below. `deactivate` takes that same lock first, so it cannot
        // return while this send is still running, and a later caller fails here
        // before connecting or writing.
        debug_assert!(self.request_lock_depth.load(Ordering::Acquire) > 0);
        self.ensure_active()?;
        let mut stream = connect_bounded(endpoint, CONNECT_TIMEOUT).map_err(|error| {
            eprintln!(
                "transport exchange failed instance_id={} route={route} phase=connect category={}",
                self.instance_id,
                error.category()
            );
            error
        })?;
        self.verify_peer_pid(&stream)?;
        let request_deadline = Instant::now() + REQUEST_TIMEOUT;
        stream
            .set_read_timeout(Some(REQUEST_TIMEOUT))
            .and_then(|_| stream.set_write_timeout(Some(REQUEST_TIMEOUT)))
            .map_err(|error| {
                eprintln!(
                    "transport exchange failed instance_id={} route={route} phase=timeout_setup kind={:?} os_error={:?}",
                    self.instance_id,
                    error.kind(),
                    error.raw_os_error()
                );
                TransportError::EndpointUnavailable
            })?;

        let method = match verb {
            Verb::Get => "GET",
            Verb::Post => "POST",
        };
        let content_type = if route == APPLICATION_ENVELOPE_ROUTE {
            "application/octet-stream"
        } else {
            "text/plain"
        };
        let request = format!(
            "{method} {route} HTTP/1.1\r\nHost: jarvis.local\r\nConnection: close\r\nContent-Length: {}\r\nContent-Type: {content_type}\r\n\r\n",
            body.len()
        );
        self.ensure_active()?;
        #[cfg(test)]
        self.pause_transaction_for_test("checked");
        self.ensure_active()?;
        debug_assert!(self.request_lock_depth.load(Ordering::Acquire) > 0);
        stream
            .write_all(request.as_bytes())
            .and_then(|_| stream.write_all(body))
            .and_then(|_| stream.flush())
            .map_err(|error| {
                eprintln!(
                    "transport exchange failed instance_id={} route={route} phase=request_write kind={:?} os_error={:?}",
                    self.instance_id,
                    error.kind(),
                    error.raw_os_error()
                );
                map_io_error(error)
            })?;
        read_http_response(&mut stream, request_deadline, content_type).map_err(|error| {
            eprintln!(
                "transport exchange failed instance_id={} route={route} phase=response_read category={}",
                self.instance_id,
                error.category()
            );
            error
        })
    }

    fn verify_peer_pid(&self, stream: &UnixStream) -> Result<(), TransportError> {
        let expected = self.expected_peer_pid.load(Ordering::Acquire);
        let actual = unix_peer_pid(stream)?;
        if expected == 0 || expected != actual {
            return Err(TransportError::PeerRejected);
        }
        self.ensure_active()
    }

    #[cfg(test)]
    fn next_envelope_nonce(&self) -> Result<[u8; ENVELOPE_NONCE_BYTES], TransportError> {
        let _request = self.lock_request();
        self.next_envelope_nonce_locked()
    }

    fn next_envelope_nonce_locked(&self) -> Result<[u8; ENVELOPE_NONCE_BYTES], TransportError> {
        debug_assert!(self.request_lock_depth.load(Ordering::Acquire) > 0);
        let secret = lock(&self.secret);
        if !self.active.load(Ordering::Acquire) || secret.is_none() {
            return Err(TransportError::Inactive);
        }
        let sequence = self
            .envelope_sequence
            .load(Ordering::Acquire)
            .checked_add(1)
            .ok_or(TransportError::OsCryptoUnavailable)?;
        self.envelope_sequence.store(sequence, Ordering::Release);
        let mut nonce = [0_u8; ENVELOPE_NONCE_BYTES];
        nonce[..ENVELOPE_SEQUENCE_BYTES].copy_from_slice(&sequence.to_be_bytes());
        Ok(nonce)
    }

    #[cfg(test)]
    fn seal_application_request(
        &self,
        route: &str,
        body: &[u8],
        nonce: &[u8; ENVELOPE_NONCE_BYTES],
    ) -> Result<Vec<u8>, TransportError> {
        let _request = self.lock_request();
        self.seal_application_request_locked(route, body, nonce)
    }

    fn seal_application_request_locked(
        &self,
        route: &str,
        body: &[u8],
        nonce: &[u8; ENVELOPE_NONCE_BYTES],
    ) -> Result<Vec<u8>, TransportError> {
        debug_assert!(self.request_lock_depth.load(Ordering::Acquire) > 0);
        let path = route.as_bytes();
        let path_len = u16::try_from(path.len()).map_err(|_| TransportError::HttpRejected)?;
        let body_len =
            u32::try_from(body.len()).map_err(|_| TransportError::ApplicationRequestTooLarge)?;
        let mut plaintext = Vec::with_capacity(8 + path.len() + body.len());
        plaintext.push(ENVELOPE_VERSION);
        plaintext.push(1); // POST
        plaintext.extend_from_slice(&path_len.to_be_bytes());
        plaintext.extend_from_slice(&body_len.to_be_bytes());
        plaintext.extend_from_slice(path);
        plaintext.extend_from_slice(body);
        let secret = lock(&self.secret);
        if !self.active.load(Ordering::Acquire) || secret.is_none() {
            plaintext.fill(0);
            return Err(TransportError::Inactive);
        }
        let (mut encryption_key, mut authentication_key) =
            derive_envelope_keys(secret.as_ref().unwrap(), &self.instance_id, b"request")?;
        let result = seal_message(
            &self.instance_id,
            b"request",
            &encryption_key,
            &authentication_key,
            nonce,
            &plaintext,
        );
        plaintext.fill(0);
        encryption_key.fill(0);
        authentication_key.fill(0);
        drop(secret);
        if result
            .as_ref()
            .is_ok_and(|envelope| envelope.len() > MAX_ENVELOPE_REQUEST_BYTES)
        {
            return Err(TransportError::ApplicationRequestTooLarge);
        }
        result
    }

    fn open_application_response(
        &self,
        envelope: &[u8],
        expected_nonce: &[u8; ENVELOPE_NONCE_BYTES],
    ) -> Result<Vec<u8>, TransportError> {
        debug_assert!(self.request_lock_depth.load(Ordering::Acquire) > 0);
        if envelope.len() > MAX_ENVELOPE_RESPONSE_BYTES
            || envelope.len() < ENVELOPE_NONCE_BYTES + ENVELOPE_TAG_BYTES
            || &envelope[..ENVELOPE_NONCE_BYTES] != expected_nonce
        {
            return Err(TransportError::ProofRejected);
        }
        let (mut encryption_key, mut authentication_key) =
            self.envelope_keys_locked(b"response")?;
        let opened = open_message(
            &self.instance_id,
            b"response",
            &encryption_key,
            &authentication_key,
            envelope,
        );
        encryption_key.fill(0);
        authentication_key.fill(0);
        let mut plaintext = opened?;
        if plaintext.len() < 7 || plaintext[0] != ENVELOPE_VERSION {
            plaintext.fill(0);
            return Err(TransportError::MalformedResponse);
        }
        let status = u16::from_be_bytes([plaintext[1], plaintext[2]]);
        let body_len =
            u32::from_be_bytes([plaintext[3], plaintext[4], plaintext[5], plaintext[6]]) as usize;
        if body_len != plaintext.len() - 7 || status != 200 {
            plaintext.fill(0);
            return Err(TransportError::HttpRejected);
        }
        let response = plaintext[7..].to_vec();
        plaintext.fill(0);
        Ok(response)
    }

    #[cfg(test)]
    fn envelope_keys(&self, direction: &[u8]) -> Result<([u8; 32], [u8; 32]), TransportError> {
        let _request = self.lock_request();
        self.envelope_keys_locked(direction)
    }

    fn envelope_keys_locked(
        &self,
        direction: &[u8],
    ) -> Result<([u8; 32], [u8; 32]), TransportError> {
        debug_assert!(self.request_lock_depth.load(Ordering::Acquire) > 0);
        let secret = lock(&self.secret);
        if !self.active.load(Ordering::Acquire) {
            return Err(TransportError::Inactive);
        }
        let Some(secret) = secret.as_ref() else {
            return Err(TransportError::Inactive);
        };
        derive_envelope_keys(secret, &self.instance_id, direction)
    }

    fn verify_proof(
        &self,
        version: &Version,
        nonce_hex: &str,
        response: &[u8],
    ) -> Result<(), TransportError> {
        let lines = parse_fields(response, 6)?;
        if lines[0] != ("protocol_version", PROTOCOL_VERSION)
            || lines[1] != ("runtime_kind", RUNTIME_KIND)
            || lines[2] != ("instance_id", self.instance_id.as_str())
            || lines[3] != ("build", BUILD_ID)
            || lines[4].0 != "operation_result"
            || lines[4].1 != format!("pong:{}", self.instance_id)
            || lines[5].0 != "proof"
            || version.instance_id != self.instance_id
        {
            return Err(TransportError::ProofRejected);
        }
        let proof = decode_hex_32(lines[5].1).ok_or(TransportError::MalformedResponse)?;
        let message = proof_message(version, nonce_hex, lines[4].1);
        let secret = lock(&self.secret);
        let Some(secret) = secret.as_ref() else {
            return Err(TransportError::Inactive);
        };
        let expected = hmac_sha256(secret, message.as_bytes())?;
        if !constant_time_equal(&proof, &expected) {
            return Err(TransportError::ProofRejected);
        }
        self.ensure_active()
    }

    /// Serializes probe, seal, send, and response open. The state mutex is not
    /// held during socket IO; `held` remains true until the guard drops.
    fn lock_request(&self) -> RequestLockGuard<'_> {
        let mut state = lock(&self.request_state);
        while state.held {
            state.waiters += 1;
            self.request_cv.notify_all();
            state = self
                .request_cv
                .wait(state)
                .unwrap_or_else(|error| error.into_inner());
            state.waiters -= 1;
        }
        state.held = true;
        self.request_lock_depth.fetch_add(1, Ordering::Release);
        RequestLockGuard { session: self }
    }

    #[cfg(test)]
    fn pause_transaction_for_test(&self, phase: &str) {
        let hook = lock(&self.transaction_barrier).clone();
        if let Some(hook) = hook {
            hook(phase);
        }
    }

    #[cfg(test)]
    fn wait_until_request_contended_for_test(&self) {
        let mut state = lock(&self.request_state);
        while state.waiters == 0 {
            state = self
                .request_cv
                .wait(state)
                .unwrap_or_else(|error| error.into_inner());
        }
    }
}

impl Drop for TransportSession {
    fn drop(&mut self) {
        self.revoke();
        #[cfg(test)]
        if self.path_matches_handle() && fs::symlink_metadata(&self.socket_path).is_err() {
            let _ = fs::remove_dir(&self.directory);
        }
    }
}

#[derive(Clone, Copy)]
enum Verb {
    Get,
    Post,
}

struct Version {
    protocol: String,
    runtime_kind: String,
    instance_id: String,
    build: String,
}

fn parse_version(body: &[u8]) -> Result<Version, TransportError> {
    let fields = parse_fields(body, 4)?;
    if fields[0].0 != "protocol_version"
        || fields[1].0 != "runtime_kind"
        || fields[2].0 != "instance_id"
        || fields[3].0 != "build"
    {
        return Err(TransportError::MalformedResponse);
    }
    Ok(Version {
        protocol: fields[0].1.to_owned(),
        runtime_kind: fields[1].1.to_owned(),
        instance_id: fields[2].1.to_owned(),
        build: fields[3].1.to_owned(),
    })
}

fn parse_fields<'a>(
    body: &'a [u8],
    expected: usize,
) -> Result<Vec<(&'a str, &'a str)>, TransportError> {
    let text = std::str::from_utf8(body).map_err(|_| TransportError::MalformedResponse)?;
    let text = text
        .strip_suffix('\n')
        .ok_or(TransportError::MalformedResponse)?;
    let mut fields = Vec::with_capacity(expected);
    for line in text.split('\n') {
        let (name, value) = line
            .split_once('=')
            .ok_or(TransportError::MalformedResponse)?;
        if name.is_empty() || value.is_empty() || value.contains(['\r', '\n']) {
            return Err(TransportError::MalformedResponse);
        }
        if fields.iter().any(|(existing, _)| *existing == name) {
            return Err(TransportError::MalformedResponse);
        }
        fields.push((name, value));
    }
    if fields.len() != expected {
        return Err(TransportError::MalformedResponse);
    }
    Ok(fields)
}

fn proof_message(version: &Version, nonce_hex: &str, operation_result: &str) -> String {
    format!(
        "jarvis-local-transport-proof-v3\n{}\n{}\n{}\n{}\n{}\n{}",
        version.protocol,
        version.runtime_kind,
        version.instance_id,
        version.build,
        nonce_hex,
        operation_result
    )
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

fn lock<T>(mutex: &Mutex<T>) -> MutexGuard<'_, T> {
    mutex.lock().unwrap_or_else(|error| error.into_inner())
}

fn hex(bytes: &[u8]) -> String {
    const DIGITS: &[u8; 16] = b"0123456789abcdef";
    let mut result = String::with_capacity(bytes.len() * 2);
    for byte in bytes {
        result.push(char::from(DIGITS[(byte >> 4) as usize]));
        result.push(char::from(DIGITS[(byte & 0x0f) as usize]));
    }
    result
}

fn write_hex(writer: &mut impl Write, bytes: &[u8]) -> io::Result<()> {
    const DIGITS: &[u8; 16] = b"0123456789abcdef";
    for byte in bytes {
        writer.write_all(&[DIGITS[(byte >> 4) as usize], DIGITS[(byte & 0x0f) as usize]])?;
    }
    Ok(())
}

fn decode_hex_32(value: &str) -> Option<[u8; 32]> {
    decode_hex_array::<32>(value.as_bytes())
}

fn decode_hex_array<const N: usize>(value: &[u8]) -> Option<[u8; N]> {
    if value.len() != N * 2 {
        return None;
    }
    let mut output = [0_u8; N];
    for (index, pair) in value.chunks_exact(2).enumerate() {
        output[index] = (hex_nibble(pair[0])? << 4) | hex_nibble(pair[1])?;
    }
    Some(output)
}

fn hex_nibble(value: u8) -> Option<u8> {
    match value {
        b'0'..=b'9' => Some(value - b'0'),
        b'a'..=b'f' => Some(value - b'a' + 10),
        b'A'..=b'F' => Some(value - b'A' + 10),
        _ => None,
    }
}

fn constant_time_equal(left: &[u8], right: &[u8]) -> bool {
    if left.len() != right.len() {
        return false;
    }
    left.iter()
        .zip(right)
        .fold(0_u8, |difference, (left, right)| {
            difference | (left ^ right)
        })
        == 0
}

fn map_io_error(error: io::Error) -> TransportError {
    match error.kind() {
        io::ErrorKind::TimedOut | io::ErrorKind::WouldBlock => TransportError::Timeout,
        io::ErrorKind::NotFound | io::ErrorKind::ConnectionRefused | io::ErrorKind::BrokenPipe => {
            TransportError::EndpointUnavailable
        }
        _ => TransportError::EndpointUnavailable,
    }
}

fn map_framing_io_error(error: io::Error) -> TransportError {
    match error.kind() {
        io::ErrorKind::ConnectionReset
        | io::ErrorKind::BrokenPipe
        | io::ErrorKind::UnexpectedEof => TransportError::MalformedResponse,
        _ => map_io_error(error),
    }
}

#[cfg(unix)]
fn unlink_socket_at(directory: &fs::File) {
    let result = unsafe { unlinkat(directory.as_raw_fd(), SOCKET_LEAF.as_ptr().cast(), 0) };
    if result == 0 {
        eprintln!("transport socket cleanup result=removed_at_owned_directory");
    } else {
        let error = io::Error::last_os_error();
        if error.kind() != io::ErrorKind::NotFound {
            eprintln!(
                "transport socket cleanup result=preserved category={:?}",
                error.kind()
            );
        }
    }
}

fn read_http_response(
    stream: &mut UnixStream,
    deadline: Instant,
    expected_content_type: &str,
) -> Result<Vec<u8>, TransportError> {
    let body_limit = if expected_content_type == "application/octet-stream" {
        MAX_ENVELOPE_RESPONSE_BYTES
    } else {
        MAX_CONTROL_RESPONSE_BODY_BYTES
    };
    let mut wire = Vec::new();
    let mut buffer = [0_u8; 512];
    let header_end = loop {
        let remaining = deadline.saturating_duration_since(Instant::now());
        if remaining.is_zero() {
            return Err(TransportError::Timeout);
        }
        let _ = stream.set_read_timeout(Some(remaining));
        let count = stream.read(&mut buffer).map_err(map_framing_io_error)?;
        if count == 0 {
            return Err(TransportError::MalformedResponse);
        }
        wire.extend_from_slice(&buffer[..count]);
        if wire.len() > MAX_RESPONSE_HEADER_BYTES + body_limit {
            return Err(TransportError::ResponseTooLarge);
        }
        if let Some(index) = wire.windows(4).position(|window| window == b"\r\n\r\n") {
            if index + 4 > MAX_RESPONSE_HEADER_BYTES {
                return Err(TransportError::ResponseTooLarge);
            }
            break index + 4;
        }
        if wire.len() > MAX_RESPONSE_HEADER_BYTES {
            return Err(TransportError::ResponseTooLarge);
        }
    };

    let header =
        std::str::from_utf8(&wire[..header_end]).map_err(|_| TransportError::MalformedResponse)?;
    let mut lines = header.split("\r\n");
    let status = lines.next().ok_or(TransportError::MalformedResponse)?;
    if !status.starts_with("HTTP/1.1 ") {
        return Err(TransportError::MalformedResponse);
    }
    if status != "HTTP/1.1 200 OK" {
        return Err(TransportError::HttpRejected);
    }
    let mut content_length = None;
    let mut content_type_ok = false;
    let mut content_type_seen = false;
    for line in lines.filter(|line| !line.is_empty()) {
        let (name, value) = line
            .split_once(':')
            .ok_or(TransportError::MalformedResponse)?;
        if name.eq_ignore_ascii_case("content-length") {
            if content_length.is_some() {
                return Err(TransportError::MalformedResponse);
            }
            content_length = Some(
                value
                    .trim()
                    .parse::<usize>()
                    .map_err(|_| TransportError::MalformedResponse)?,
            );
        } else if name.eq_ignore_ascii_case("content-type") {
            if content_type_seen {
                return Err(TransportError::MalformedResponse);
            }
            content_type_seen = true;
            let value = value.trim();
            content_type_ok = value.eq_ignore_ascii_case(expected_content_type)
                || (expected_content_type == "text/plain"
                    && value.eq_ignore_ascii_case("text/plain; charset=utf-8"));
        } else if name.eq_ignore_ascii_case("transfer-encoding") {
            return Err(TransportError::MalformedResponse);
        } else if name.eq_ignore_ascii_case("connection") {
            if !value.trim().eq_ignore_ascii_case("close") {
                return Err(TransportError::MalformedResponse);
            }
        } else if name.eq_ignore_ascii_case("date") || name.eq_ignore_ascii_case("server") {
            // Uvicorn may add harmless standard headers; they do not affect the envelope.
        } else {
            return Err(TransportError::MalformedResponse);
        }
    }
    let content_length = content_length.ok_or(TransportError::MalformedResponse)?;
    if content_length > body_limit {
        return Err(TransportError::ResponseTooLarge);
    }
    let secure_envelope = expected_content_type == "application/octet-stream";
    if (secure_envelope && !content_type_seen) || (content_type_seen && !content_type_ok) {
        return Err(TransportError::HttpRejected);
    }
    let mut body = wire[header_end..].to_vec();
    if body.len() > content_length {
        return Err(TransportError::MalformedResponse);
    }
    let prior = body.len();
    body.resize(content_length, 0);
    read_exact_deadline(stream, &mut body[prior..], deadline)?;
    Ok(body)
}

fn read_exact_deadline(
    stream: &mut UnixStream,
    mut output: &mut [u8],
    deadline: Instant,
) -> Result<(), TransportError> {
    while !output.is_empty() {
        let remaining = deadline.saturating_duration_since(Instant::now());
        if remaining.is_zero() {
            return Err(TransportError::Timeout);
        }
        let _ = stream.set_read_timeout(Some(remaining));
        let count = stream.read(output).map_err(map_framing_io_error)?;
        if count == 0 {
            return Err(TransportError::MalformedResponse);
        }
        output = &mut output[count..];
    }
    Ok(())
}

fn connect_bounded(
    path: &std::path::Path,
    timeout: Duration,
) -> Result<UnixStream, TransportError> {
    #[cfg(target_os = "macos")]
    {
        return connect_bounded_macos(path, timeout);
    }
    #[cfg(not(target_os = "macos"))]
    {
        let _ = timeout;
        UnixStream::connect(path).map_err(map_io_error)
    }
}

#[cfg(target_os = "macos")]
fn connect_bounded_macos(
    path: &std::path::Path,
    timeout: Duration,
) -> Result<UnixStream, TransportError> {
    use std::{
        mem::{size_of, zeroed},
        os::fd::{FromRawFd, OwnedFd},
        os::unix::ffi::OsStrExt,
    };

    const AF_UNIX: i32 = 1;
    const SOCK_STREAM: i32 = 1;
    const F_GETFL: i32 = 3;
    const F_SETFL: i32 = 4;
    const O_NONBLOCK: i32 = 0x0004;
    const EINTR: i32 = 4;
    const EINPROGRESS: i32 = 36;
    const EAGAIN: i32 = 35;
    const POLLOUT: i16 = 0x0004;
    const SOL_SOCKET: i32 = 0xffff;
    const SO_ERROR: i32 = 0x1007;

    #[repr(C)]
    struct SockAddrUn {
        sun_len: u8,
        sun_family: u8,
        sun_path: [i8; 104],
    }
    #[repr(C)]
    struct PollFd {
        fd: i32,
        events: i16,
        revents: i16,
    }
    unsafe extern "C" {
        fn socket(domain: i32, kind: i32, protocol: i32) -> i32;
        fn connect(fd: i32, address: *const SockAddrUn, length: u32) -> i32;
        fn fcntl(fd: i32, command: i32, ...) -> i32;
        fn poll(descriptors: *mut PollFd, count: u32, timeout_ms: i32) -> i32;
        fn getsockopt(fd: i32, level: i32, option: i32, value: *mut i32, length: *mut u32) -> i32;
    }

    let bytes = path.as_os_str().as_bytes();
    if bytes.is_empty() || bytes.len() >= 104 || bytes.contains(&0) {
        return Err(TransportError::SetupFailed);
    }
    let raw_fd = unsafe { socket(AF_UNIX, SOCK_STREAM, 0) };
    if raw_fd < 0 {
        return Err(TransportError::EndpointUnavailable);
    }
    let owned = unsafe { OwnedFd::from_raw_fd(raw_fd) };
    let current_flags = unsafe { fcntl(raw_fd, F_GETFL) };
    if current_flags < 0 || unsafe { fcntl(raw_fd, F_SETFL, current_flags | O_NONBLOCK) } < 0 {
        return Err(TransportError::EndpointUnavailable);
    }
    let mut address: SockAddrUn = unsafe { zeroed() };
    address.sun_len = (2 + bytes.len() + 1) as u8;
    address.sun_family = AF_UNIX as u8;
    for (slot, byte) in address.sun_path.iter_mut().zip(bytes) {
        *slot = *byte as i8;
    }
    let result = unsafe { connect(raw_fd, &address, u32::from(address.sun_len)) };
    if result != 0 {
        let error = io::Error::last_os_error();
        if !matches!(error.raw_os_error(), Some(EINPROGRESS | EAGAIN)) {
            return Err(map_io_error(error));
        }
        let deadline = Instant::now() + timeout;
        loop {
            let remaining = deadline.saturating_duration_since(Instant::now());
            if remaining.is_zero() {
                return Err(TransportError::Timeout);
            }
            let millis = remaining.as_millis().clamp(1, i32::MAX as u128) as i32;
            let mut descriptor = PollFd {
                fd: raw_fd,
                events: POLLOUT,
                revents: 0,
            };
            let poll_result = unsafe { poll(&mut descriptor, 1_u32, millis) };
            if poll_result < 0 {
                if io::Error::last_os_error().raw_os_error() == Some(EINTR) {
                    continue;
                }
                return Err(TransportError::EndpointUnavailable);
            }
            if poll_result == 0 {
                return Err(TransportError::Timeout);
            }
            let mut socket_error = 0_i32;
            let mut socket_error_len = size_of::<i32>() as u32;
            if unsafe {
                getsockopt(
                    raw_fd,
                    SOL_SOCKET,
                    SO_ERROR,
                    &mut socket_error,
                    &mut socket_error_len,
                )
            } != 0
            {
                return Err(TransportError::EndpointUnavailable);
            }
            if socket_error != 0 {
                return Err(map_io_error(io::Error::from_raw_os_error(socket_error)));
            }
            break;
        }
    }
    let stream = UnixStream::from(owned);
    stream
        .set_nonblocking(false)
        .map_err(|_| TransportError::EndpointUnavailable)?;
    Ok(stream)
}

/// Reads the one bounded initialization record from the parent-owned stdin pipe.
pub(crate) fn read_child_init(
    reader: &mut impl io::BufRead,
    expected_instance_id: &str,
) -> Result<ChildTransportConfig, TransportError> {
    let mut record = Vec::with_capacity(MAX_INIT_BYTES);
    let count = match reader
        .take((MAX_INIT_BYTES + 1) as u64)
        .read_until(b'\n', &mut record)
    {
        Ok(count) => count,
        Err(_) => {
            record.fill(0);
            return Err(TransportError::SetupFailed);
        }
    };
    if count == 0 || count > MAX_INIT_BYTES || record.last() != Some(&b'\n') {
        record.fill(0);
        return Err(TransportError::SetupFailed);
    }
    record.pop();
    if !record.starts_with(INIT_PREFIX) {
        record.fill(0);
        return Err(TransportError::SetupFailed);
    }
    let parsed = (|| {
        let payload = &record[INIT_PREFIX.len()..];
        let mut fields = payload.split(|byte| *byte == b'\t');
        let instance_id = fields.next().ok_or(TransportError::SetupFailed)?;
        let secret_hex = fields.next().ok_or(TransportError::SetupFailed)?;
        let dev = fields
            .next()
            .and_then(|value| std::str::from_utf8(value).ok())
            .and_then(|value| value.parse::<u64>().ok())
            .ok_or(TransportError::SetupFailed)?;
        let ino = fields
            .next()
            .and_then(|value| std::str::from_utf8(value).ok())
            .and_then(|value| value.parse::<u64>().ok())
            .ok_or(TransportError::SetupFailed)?;
        if fields.next().is_some() || instance_id != expected_instance_id.as_bytes() {
            return Err(TransportError::SetupFailed);
        }
        let mut secret =
            decode_hex_array::<SECRET_BYTES>(secret_hex).ok_or(TransportError::SetupFailed)?;
        let directory = match fs::File::open(".") {
            Ok(directory) => directory,
            Err(_) => {
                secret.fill(0);
                return Err(TransportError::SetupFailed);
            }
        };
        let metadata = match directory.metadata() {
            Ok(metadata) => metadata,
            Err(_) => {
                secret.fill(0);
                return Err(TransportError::SetupFailed);
            }
        };
        if !metadata.is_dir()
            || DirectoryIdentity::from_metadata(&metadata) != (DirectoryIdentity { dev, ino })
        {
            secret.fill(0);
            return Err(TransportError::SetupFailed);
        }
        Ok((secret, directory))
    })();
    record.fill(0);
    let (secret, directory) = parsed?;
    Ok(ChildTransportConfig {
        instance_id: expected_instance_id.to_owned(),
        secret,
        directory,
    })
}

pub(crate) struct ChildTransportConfig {
    instance_id: String,
    secret: [u8; SECRET_BYTES],
    directory: fs::File,
}

impl Drop for ChildTransportConfig {
    fn drop(&mut self) {
        self.secret.fill(0);
        std::hint::black_box(self.secret);
        unlink_socket_at(&self.directory);
    }
}

impl ChildTransportConfig {
    pub(crate) fn bind(&self) -> Result<UnixListener, TransportError> {
        let previous_mask = unsafe { umask(0o177) };
        let bind_result = UnixListener::bind("runtime.sock");
        unsafe { umask(previous_mask) };
        let listener = bind_result.map_err(|_| TransportError::SetupFailed)?;
        listener
            .set_nonblocking(true)
            .map_err(|_| TransportError::SetupFailed)?;
        Ok(listener)
    }

    fn proof_response(&self, nonce_hex: &str) -> Result<Vec<u8>, TransportError> {
        if decode_hex_32(nonce_hex).is_none() {
            return Err(TransportError::MalformedResponse);
        }
        let version = Version {
            protocol: PROTOCOL_VERSION.to_owned(),
            runtime_kind: RUNTIME_KIND.to_owned(),
            instance_id: self.instance_id.clone(),
            build: BUILD_ID.to_owned(),
        };
        let operation_result = format!("pong:{}", self.instance_id);
        let proof = hmac_sha256(
            &self.secret,
            proof_message(&version, nonce_hex, &operation_result).as_bytes(),
        )?;
        Ok(format!(
            "protocol_version={}\nruntime_kind={}\ninstance_id={}\nbuild={}\noperation_result={}\nproof={}\n",
            version.protocol,
            version.runtime_kind,
            version.instance_id,
            version.build,
            operation_result,
            hex(&proof)
        )
        .into_bytes())
    }

    #[cfg(test)]
    pub(crate) fn serve_one(
        &self,
        listener: &UnixListener,
        wait: Duration,
    ) -> Result<bool, TransportError> {
        let live = AtomicBool::new(true);
        self.serve_one_with_liveness(listener, wait, &live)
    }

    pub(crate) fn serve_one_with_liveness(
        &self,
        listener: &UnixListener,
        wait: Duration,
        live: &AtomicBool,
    ) -> Result<bool, TransportError> {
        self.serve_one_inner(listener, wait, live, || {})
    }

    #[cfg(test)]
    fn serve_one_with_accept_hook_for_test(
        &self,
        listener: &UnixListener,
        wait: Duration,
        live: &AtomicBool,
        accepted: std::sync::mpsc::Sender<()>,
    ) -> Result<bool, TransportError> {
        self.serve_one_inner(listener, wait, live, move || {
            let _ = accepted.send(());
        })
    }

    fn serve_one_inner(
        &self,
        listener: &UnixListener,
        wait: Duration,
        live: &AtomicBool,
        after_accept: impl Fn(),
    ) -> Result<bool, TransportError> {
        let deadline = Instant::now() + wait;
        loop {
            if !live.load(Ordering::Acquire) {
                return Err(TransportError::Inactive);
            }
            match listener.accept() {
                Ok((mut stream, _)) => {
                    after_accept();
                    stream
                        .set_read_timeout(Some(SERVER_REQUEST_TIMEOUT))
                        .and_then(|_| stream.set_write_timeout(Some(SERVER_REQUEST_TIMEOUT)))
                        .map_err(|_| TransportError::EndpointUnavailable)?;
                    let response = self.handle_request(&mut stream);
                    if !live.load(Ordering::Acquire) {
                        return Err(TransportError::Inactive);
                    }
                    let (status, body) = match response {
                        Ok(body) => ("200 OK", body),
                        Err(error) => ("400 Bad Request", error.category().as_bytes().to_vec()),
                    };
                    let header = format!(
                        "HTTP/1.1 {status}\r\nContent-Length: {}\r\nConnection: close\r\nContent-Type: text/plain\r\n\r\n",
                        body.len()
                    );
                    stream
                        .write_all(header.as_bytes())
                        .and_then(|_| stream.write_all(&body))
                        .and_then(|_| stream.flush())
                        .map_err(map_io_error)?;
                    if !live.load(Ordering::Acquire) {
                        return Err(TransportError::Inactive);
                    }
                    return Ok(true);
                }
                Err(error) if error.kind() == io::ErrorKind::WouldBlock => {
                    let remaining = deadline.saturating_duration_since(Instant::now());
                    if remaining.is_zero() {
                        return Ok(false);
                    }
                    std::thread::sleep(remaining.min(Duration::from_millis(5)));
                }
                Err(error) => return Err(map_io_error(error)),
            }
        }
    }

    fn handle_request(&self, stream: &mut UnixStream) -> Result<Vec<u8>, TransportError> {
        let deadline = Instant::now() + SERVER_REQUEST_TIMEOUT;
        let mut request = Vec::new();
        let mut buffer = [0_u8; 256];
        let header_end = loop {
            let remaining = deadline.saturating_duration_since(Instant::now());
            if remaining.is_zero() {
                return Err(TransportError::Timeout);
            }
            stream
                .set_read_timeout(Some(remaining))
                .map_err(|_| TransportError::EndpointUnavailable)?;
            let count = stream.read(&mut buffer).map_err(map_io_error)?;
            if count == 0 {
                return Err(TransportError::MalformedResponse);
            }
            request.extend_from_slice(&buffer[..count]);
            if let Some(index) = request.windows(4).position(|window| window == b"\r\n\r\n") {
                if index + 4 > MAX_REQUEST_HEADER_BYTES {
                    return Err(TransportError::ResponseTooLarge);
                }
                break index + 4;
            }
            if request.len() > MAX_REQUEST_HEADER_BYTES {
                return Err(TransportError::ResponseTooLarge);
            }
        };
        let header = std::str::from_utf8(&request[..header_end])
            .map_err(|_| TransportError::MalformedResponse)?;
        let mut lines = header.split("\r\n");
        let start = lines.next().ok_or(TransportError::MalformedResponse)?;
        let mut host_ok = false;
        let mut host_seen = false;
        let mut connection_close = false;
        let mut connection_seen = false;
        let mut content_type_ok = false;
        let mut content_type_seen = false;
        let mut content_length = None;
        for line in lines.filter(|line| !line.is_empty()) {
            let (name, value) = line
                .split_once(':')
                .ok_or(TransportError::MalformedResponse)?;
            if name.eq_ignore_ascii_case("host") {
                if host_seen {
                    return Err(TransportError::MalformedResponse);
                }
                host_seen = true;
                host_ok = value.trim() == "jarvis.local";
            } else if name.eq_ignore_ascii_case("content-length") {
                if content_length.is_some() {
                    return Err(TransportError::MalformedResponse);
                }
                content_length = Some(
                    value
                        .trim()
                        .parse::<usize>()
                        .map_err(|_| TransportError::MalformedResponse)?,
                );
            } else if name.eq_ignore_ascii_case("connection") {
                if connection_seen {
                    return Err(TransportError::MalformedResponse);
                }
                connection_seen = true;
                connection_close = value.trim().eq_ignore_ascii_case("close");
            } else if name.eq_ignore_ascii_case("content-type") {
                if content_type_seen {
                    return Err(TransportError::MalformedResponse);
                }
                content_type_seen = true;
                content_type_ok = value.trim().eq_ignore_ascii_case("text/plain");
            } else if name.eq_ignore_ascii_case("origin") {
                return Err(TransportError::HttpRejected);
            } else {
                return Err(TransportError::HttpRejected);
            }
        }
        if !host_ok || !connection_close || !content_type_ok {
            return Err(TransportError::HttpRejected);
        }
        let content_length = content_length.ok_or(TransportError::MalformedResponse)?;
        if content_length > MAX_REQUEST_BODY_BYTES {
            return Err(TransportError::ResponseTooLarge);
        }
        let mut body = request[header_end..].to_vec();
        if body.len() > content_length {
            return Err(TransportError::MalformedResponse);
        }
        let prior = body.len();
        body.resize(content_length, 0);
        read_exact_deadline(stream, &mut body[prior..], deadline)?;

        match start {
            line if line == format!("GET {HEALTH_ROUTE} HTTP/1.1") && body.is_empty() => Ok(b"ok\n".to_vec()),
            line if line == format!("GET {VERSION_ROUTE} HTTP/1.1") && body.is_empty() => Ok(format!(
                "protocol_version={PROTOCOL_VERSION}\nruntime_kind={RUNTIME_KIND}\ninstance_id={}\nbuild={BUILD_ID}\n",
                self.instance_id
            ).into_bytes()),
            line if line == format!("POST {PROOF_ROUTE} HTTP/1.1") => {
                let nonce = std::str::from_utf8(&body).map_err(|_| TransportError::MalformedResponse)?;
                self.proof_response(nonce)
            }
            _ => Err(TransportError::HttpRejected),
        }
    }
}

fn os_random(bytes: &mut [u8]) -> Result<(), TransportError> {
    #[cfg(target_os = "macos")]
    {
        use std::ffi::c_void;
        #[link(name = "Security", kind = "framework")]
        unsafe extern "C" {
            fn SecRandomCopyBytes(random: *const c_void, count: usize, bytes: *mut u8) -> i32;
        }
        // Apple documents a null random reference as kSecRandomDefault.
        let result =
            unsafe { SecRandomCopyBytes(std::ptr::null(), bytes.len(), bytes.as_mut_ptr()) };
        if result == 0 {
            return Ok(());
        }
    }
    let _ = bytes;
    Err(TransportError::OsCryptoUnavailable)
}

fn test_default_peer_pid() -> u32 {
    #[cfg(test)]
    {
        std::process::id()
    }
    #[cfg(not(test))]
    {
        0
    }
}

#[cfg(target_os = "macos")]
fn unix_peer_pid(stream: &UnixStream) -> Result<u32, TransportError> {
    #[link(name = "System")]
    unsafe extern "C" {
        fn getsockopt(
            socket: c_int,
            level: c_int,
            option: c_int,
            value: *mut i32,
            length: *mut u32,
        ) -> c_int;
    }

    let mut pid = 0_i32;
    let mut length = std::mem::size_of::<i32>() as u32;
    // Darwin's SOL_LOCAL / LOCAL_PEERPID values are 0 and 2 in sys/un.h.
    let result = unsafe { getsockopt(stream.as_raw_fd(), 0, 2, &mut pid, &mut length) };
    if result != 0 || length as usize != std::mem::size_of::<i32>() || pid <= 0 {
        return Err(TransportError::PeerRejected);
    }
    Ok(pid as u32)
}

#[cfg(not(target_os = "macos"))]
fn unix_peer_pid(_stream: &UnixStream) -> Result<u32, TransportError> {
    Err(TransportError::PeerRejected)
}

fn derive_envelope_keys(
    secret: &[u8; SECRET_BYTES],
    instance_id: &str,
    direction: &[u8],
) -> Result<([u8; 32], [u8; 32]), TransportError> {
    let mut encryption_context = envelope_key_context(b"encryption", direction, instance_id);
    let mut authentication_context =
        envelope_key_context(b"authentication", direction, instance_id);
    let encryption_key = hmac_sha256(secret, &encryption_context)?;
    let authentication_key = hmac_sha256(secret, &authentication_context)?;
    encryption_context.fill(0);
    authentication_context.fill(0);
    Ok((encryption_key, authentication_key))
}

fn envelope_key_context(purpose: &[u8], direction: &[u8], instance_id: &str) -> Vec<u8> {
    let mut context = b"jarvis-local-envelope-v3\0".to_vec();
    context.extend_from_slice(purpose);
    context.push(0);
    context.extend_from_slice(direction);
    context.push(0);
    context.extend_from_slice(instance_id.as_bytes());
    context
}

fn envelope_mac_message(
    instance_id: &str,
    direction: &[u8],
    nonce: &[u8; ENVELOPE_NONCE_BYTES],
    ciphertext: &[u8],
) -> Vec<u8> {
    let mut message = b"jarvis-local-envelope-v3\0".to_vec();
    message.extend_from_slice(instance_id.as_bytes());
    message.push(0);
    message.extend_from_slice(direction);
    message.push(0);
    message.extend_from_slice(APPLICATION_ENVELOPE_ROUTE.as_bytes());
    message.push(0);
    message.extend_from_slice(nonce);
    message.extend_from_slice(ciphertext);
    message
}

// Sequence s owns counters s*2^64 through s*2^64 + ceil(size/16)-1.
// Payload caps use at most 129 blocks, so the low half never carries into s.
fn validate_counter_partition(
    direction: &[u8],
    nonce: &[u8; 16],
    size: usize,
) -> Result<(), TransportError> {
    let limit = match direction {
        b"request" => MAX_ENVELOPE_REQUEST_BYTES - ENVELOPE_NONCE_BYTES - ENVELOPE_TAG_BYTES,
        b"response" => MAX_RESPONSE_BODY_BYTES + 7,
        _ => return Err(TransportError::HttpRejected),
    };
    if size > limit || nonce[..8] == [0_u8; 8] || nonce[8..] != [0_u8; 8] {
        return Err(TransportError::HttpRejected);
    }
    Ok(())
}

fn seal_message(
    instance_id: &str,
    direction: &[u8],
    encryption_key: &[u8; 32],
    authentication_key: &[u8; 32],
    nonce: &[u8; ENVELOPE_NONCE_BYTES],
    plaintext: &[u8],
) -> Result<Vec<u8>, TransportError> {
    validate_counter_partition(direction, nonce, plaintext.len())?;
    let mut ciphertext = aes_ctr_xor(encryption_key, nonce, plaintext)?;
    let mut mac_message = envelope_mac_message(instance_id, direction, nonce, &ciphertext);
    let tag = hmac_sha256(authentication_key, &mac_message)?;
    let mut envelope = Vec::with_capacity(ENVELOPE_NONCE_BYTES + ciphertext.len() + tag.len());
    envelope.extend_from_slice(nonce);
    envelope.append(&mut ciphertext);
    envelope.extend_from_slice(&tag);
    mac_message.fill(0);
    Ok(envelope)
}

fn open_message(
    instance_id: &str,
    direction: &[u8],
    encryption_key: &[u8; 32],
    authentication_key: &[u8; 32],
    envelope: &[u8],
) -> Result<Vec<u8>, TransportError> {
    if envelope.len() < ENVELOPE_NONCE_BYTES + ENVELOPE_TAG_BYTES {
        return Err(TransportError::MalformedResponse);
    }
    let nonce: &[u8; ENVELOPE_NONCE_BYTES] = envelope[..ENVELOPE_NONCE_BYTES]
        .try_into()
        .map_err(|_| TransportError::MalformedResponse)?;
    let tag_start = envelope.len() - ENVELOPE_TAG_BYTES;
    let ciphertext = &envelope[ENVELOPE_NONCE_BYTES..tag_start];
    let received_tag = &envelope[tag_start..];
    let mut mac_message = envelope_mac_message(instance_id, direction, nonce, ciphertext);
    let expected_tag = hmac_sha256(authentication_key, &mac_message)?;
    mac_message.fill(0);
    if !constant_time_equal(received_tag, &expected_tag) {
        return Err(TransportError::ProofRejected);
    }
    validate_counter_partition(direction, nonce, ciphertext.len())?;
    aes_ctr_xor(encryption_key, nonce, ciphertext)
}

fn aes_ctr_xor(
    key: &[u8; 32],
    nonce: &[u8; ENVELOPE_NONCE_BYTES],
    input: &[u8],
) -> Result<Vec<u8>, TransportError> {
    #[cfg(target_os = "macos")]
    {
        use std::ffi::c_void;
        #[link(name = "System")]
        unsafe extern "C" {
            fn CCCryptorCreateWithMode(
                operation: u32,
                mode: u32,
                algorithm: u32,
                padding: u32,
                iv: *const c_void,
                key: *const c_void,
                key_length: usize,
                tweak: *const c_void,
                tweak_length: usize,
                rounds: i32,
                options: u32,
                cryptor: *mut *mut c_void,
            ) -> i32;
            fn CCCryptorUpdate(
                cryptor: *mut c_void,
                input: *const c_void,
                input_length: usize,
                output: *mut c_void,
                output_capacity: usize,
                output_length: *mut usize,
            ) -> i32;
            fn CCCryptorRelease(cryptor: *mut c_void) -> i32;
        }

        let mut cryptor = std::ptr::null_mut();
        // CommonCrypto: kCCEncrypt=0, kCCModeCTR=4, kCCAlgorithmAES=0,
        // ccNoPadding=0. CTR is symmetric, so this operation encrypts and decrypts.
        let created = unsafe {
            CCCryptorCreateWithMode(
                0,
                4,
                0,
                0,
                nonce.as_ptr().cast(),
                key.as_ptr().cast(),
                key.len(),
                std::ptr::null(),
                0,
                0,
                2, // kCCModeOptionCTR_BE
                &mut cryptor,
            )
        };
        if created != 0 || cryptor.is_null() {
            return Err(TransportError::OsCryptoUnavailable);
        }
        let mut output = vec![0_u8; input.len()];
        let mut output_length = 0_usize;
        let updated = unsafe {
            CCCryptorUpdate(
                cryptor,
                input.as_ptr().cast(),
                input.len(),
                output.as_mut_ptr().cast(),
                output.len(),
                &mut output_length,
            )
        };
        let released = unsafe { CCCryptorRelease(cryptor) };
        if updated != 0 || released != 0 || output_length != input.len() {
            output.fill(0);
            return Err(TransportError::OsCryptoUnavailable);
        }
        Ok(output)
    }
    #[cfg(not(target_os = "macos"))]
    {
        let _ = (key, nonce, input);
        Err(TransportError::OsCryptoUnavailable)
    }
}

fn hmac_sha256(key: &[u8], message: &[u8]) -> Result<[u8; 32], TransportError> {
    #[cfg(target_os = "macos")]
    {
        use std::ffi::c_void;
        #[link(name = "System")]
        unsafe extern "C" {
            fn CCHmac(
                algorithm: u32,
                key: *const c_void,
                key_length: usize,
                data: *const c_void,
                data_length: usize,
                mac_out: *mut c_void,
            );
        }
        let mut output = [0_u8; 32];
        // CommonCrypto's kCCHmacAlgSHA256 is 2; the system routine performs HMAC-SHA-256.
        unsafe {
            CCHmac(
                2,
                key.as_ptr().cast(),
                key.len(),
                message.as_ptr().cast(),
                message.len(),
                output.as_mut_ptr().cast(),
            );
        }
        Ok(output)
    }
    #[cfg(not(target_os = "macos"))]
    {
        let _ = (key, message);
        Err(TransportError::OsCryptoUnavailable)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::{
        process::{Child, Command, Stdio},
        thread::{self, JoinHandle},
    };

    enum FakeReply {
        Body(Vec<u8>),
        Wire(Vec<u8>),
        Hang(Duration),
        Close,
    }

    #[test]
    fn g5_calls_are_route_closed_and_body_bounded_before_connecting() {
        let session = TransportSession::create("application-route-allowlist").unwrap();
        assert_eq!(
            session.call_g5_application("/real/missions", b""),
            Err(TransportError::HttpRejected)
        );
        assert_eq!(
            session.call_g5_application(APP_SESSION_OPEN_ROUTE, &vec![b'x'; 1025]),
            Err(TransportError::ApplicationRequestTooLarge)
        );
        session.revoke();
    }

    struct Canaries {
        root: PathBuf,
    }

    impl Canaries {
        fn create() -> Self {
            let mut random = [0_u8; 16];
            os_random(&mut random).unwrap();
            let root = env::temp_dir().join(format!(".jv-canary-{}", hex(&random)));
            random.fill(0);
            fs::create_dir(&root).unwrap();
            fs::create_dir(root.join("nested")).unwrap();
            fs::write(root.join("canary.txt"), b"outside-text-canary\n").unwrap();
            fs::write(root.join("runtime.sock"), b"outside-socket-canary\n").unwrap();
            fs::write(root.join("nested/canary2"), b"outside-nested-canary\n").unwrap();
            Self { root }
        }

        fn assert_intact(&self) {
            assert_eq!(
                fs::read(self.root.join("canary.txt")).unwrap(),
                b"outside-text-canary\n"
            );
            assert_eq!(
                fs::read(self.root.join("runtime.sock")).unwrap(),
                b"outside-socket-canary\n"
            );
            assert_eq!(
                fs::read(self.root.join("nested/canary2")).unwrap(),
                b"outside-nested-canary\n"
            );
        }
    }

    impl Drop for Canaries {
        fn drop(&mut self) {
            let _ = fs::remove_file(self.root.join("canary.txt"));
            let _ = fs::remove_file(self.root.join("runtime.sock"));
            let _ = fs::remove_file(self.root.join("nested/canary2"));
            let _ = fs::remove_dir(self.root.join("nested"));
            let _ = fs::remove_dir(&self.root);
        }
    }

    fn fake_listener(session: &TransportSession) -> UnixListener {
        session.set_expected_peer_pid(std::process::id()).unwrap();
        let listener = UnixListener::bind(&session.socket_path).unwrap();
        fs::set_permissions(&session.socket_path, fs::Permissions::from_mode(0o600)).unwrap();
        listener
    }

    fn fake_server(session: &TransportSession, replies: Vec<FakeReply>) -> JoinHandle<()> {
        let listener = fake_listener(session);
        let directory = session.directory_handle.try_clone().unwrap();
        thread::spawn(move || {
            for reply in replies {
                let (mut stream, _) = listener.accept().unwrap();
                let _ = read_fake_request(&mut stream);
                match reply {
                    FakeReply::Body(body) => write_fake_response(&mut stream, "200 OK", &body),
                    FakeReply::Wire(wire) => {
                        let _ = stream.write_all(&wire);
                    }
                    FakeReply::Hang(duration) => thread::sleep(duration),
                    FakeReply::Close => {}
                }
            }
            drop(listener);
            unlink_socket_at(&directory);
        })
    }

    fn read_fake_request(stream: &mut UnixStream) -> (String, Vec<u8>) {
        stream
            .set_read_timeout(Some(Duration::from_secs(1)))
            .unwrap();
        let mut wire = Vec::new();
        let mut buffer = [0_u8; 256];
        let header_end = loop {
            let count = stream.read(&mut buffer).unwrap();
            assert_ne!(count, 0);
            wire.extend_from_slice(&buffer[..count]);
            if let Some(index) = wire.windows(4).position(|window| window == b"\r\n\r\n") {
                break index + 4;
            }
            assert!(wire.len() < MAX_REQUEST_HEADER_BYTES);
        };
        let header = std::str::from_utf8(&wire[..header_end]).unwrap();
        let mut lines = header.split("\r\n");
        let start = lines.next().unwrap().to_owned();
        let mut content_length = 0;
        for line in lines {
            if let Some((name, value)) = line.split_once(':') {
                if name.eq_ignore_ascii_case("content-length") {
                    content_length = value.trim().parse::<usize>().unwrap();
                }
            }
        }
        let mut body = wire[header_end..].to_vec();
        let prior = body.len();
        body.resize(content_length, 0);
        stream.read_exact(&mut body[prior..]).unwrap();
        (start, body)
    }

    fn write_fake_response(stream: &mut UnixStream, status: &str, body: &[u8]) {
        let header = format!(
            "HTTP/1.1 {status}\r\nContent-Length: {}\r\nConnection: close\r\nContent-Type: text/plain\r\n\r\n",
            body.len()
        );
        let _ = stream
            .write_all(header.as_bytes())
            .and_then(|_| stream.write_all(body));
    }

    fn version_body(instance_id: &str, protocol: &str) -> Vec<u8> {
        format!(
            "protocol_version={protocol}\nruntime_kind={RUNTIME_KIND}\ninstance_id={instance_id}\nbuild={BUILD_ID}\n"
        )
        .into_bytes()
    }

    fn proof_body(instance_id: &str, nonce_hex: &str, secret: &[u8]) -> Vec<u8> {
        let version = Version {
            protocol: PROTOCOL_VERSION.to_owned(),
            runtime_kind: RUNTIME_KIND.to_owned(),
            instance_id: instance_id.to_owned(),
            build: BUILD_ID.to_owned(),
        };
        let operation_result = format!("pong:{instance_id}");
        let proof = hmac_sha256(
            secret,
            proof_message(&version, nonce_hex, &operation_result).as_bytes(),
        )
        .unwrap();
        format!(
            "protocol_version={}\nruntime_kind={}\ninstance_id={}\nbuild={}\noperation_result={}\nproof={}\n",
            version.protocol,
            version.runtime_kind,
            version.instance_id,
            version.build,
            operation_result,
            hex(&proof)
        )
        .into_bytes()
    }

    #[test]
    #[ignore = "spawned only by the fake-runtime adversarial test"]
    fn fake_runtime_process_entry() {
        let path = PathBuf::from(env::var_os("JARVIS_FAKE_SOCKET").unwrap());
        let instance_id = env::var("JARVIS_FAKE_INSTANCE").unwrap();
        let crash_on_proof = env::var("JARVIS_FAKE_CRASH_ON_PROOF").as_deref() == Ok("1");
        let listener = UnixListener::bind(&path).unwrap();
        fs::set_permissions(&path, fs::Permissions::from_mode(0o600)).unwrap();
        let stdout = io::stdout();
        let mut stdout = stdout.lock();
        writeln!(stdout, "JARVIS_FAKE_RUNTIME_READY {instance_id}").unwrap();
        stdout.flush().unwrap();
        drop(stdout);
        loop {
            let (mut stream, _) = listener.accept().unwrap();
            let (start, _) = read_fake_request(&mut stream);
            let route = start.split_whitespace().nth(1).unwrap_or_default();
            match route {
                HEALTH_ROUTE => write_fake_response(&mut stream, "200 OK", b"ok\n"),
                VERSION_ROUTE => write_fake_response(
                    &mut stream,
                    "200 OK",
                    &version_body(&instance_id, PROTOCOL_VERSION),
                ),
                PROOF_ROUTE => {
                    if crash_on_proof {
                        std::process::exit(42);
                    }
                    let forged = format!(
                        "protocol_version={PROTOCOL_VERSION}\nruntime_kind={RUNTIME_KIND}\ninstance_id={instance_id}\nbuild={BUILD_ID}\noperation_result=pong:{instance_id}\nproof={}\n",
                        "00".repeat(32)
                    );
                    write_fake_response(&mut stream, "200 OK", forged.as_bytes());
                }
                _ => write_fake_response(&mut stream, "404 Not Found", b"not-found"),
            }
        }
    }

    struct FakeProcess(Child);

    impl FakeProcess {
        fn wait_for_exit(&mut self) -> std::process::ExitStatus {
            self.0.wait().unwrap()
        }
    }

    impl Drop for FakeProcess {
        fn drop(&mut self) {
            let _ = self.0.kill();
            let _ = self.0.wait();
        }
    }

    fn spawn_fake_process(session: &TransportSession, crash_on_proof: bool) -> FakeProcess {
        let executable = env::current_exe().unwrap();
        let child = Command::new(executable)
            .arg("--ignored")
            .arg("--exact")
            .arg("transport::tests::fake_runtime_process_entry")
            .arg("--format=terse")
            .arg("--nocapture")
            .arg("--test-threads=1")
            .env_clear()
            .env("JARVIS_FAKE_SOCKET", &session.socket_path)
            .env("JARVIS_FAKE_INSTANCE", &session.instance_id)
            .env(
                "JARVIS_FAKE_CRASH_ON_PROOF",
                if crash_on_proof { "1" } else { "0" },
            )
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .spawn()
            .unwrap();
        session.set_expected_peer_pid(child.id()).unwrap();
        let mut fake = FakeProcess(child);
        let stdout = fake.0.stdout.take().unwrap();
        let (ready_sender, ready_receiver) = std::sync::mpsc::channel();
        let instance_id = session.instance_id.clone();
        let ready_line = format!("JARVIS_FAKE_RUNTIME_READY {instance_id}");
        let expected_ready_line = ready_line.clone();
        thread::spawn(move || {
            for line in std::io::BufReader::new(stdout).lines().flatten() {
                if line == expected_ready_line {
                    let _ = ready_sender.send(line);
                    return;
                }
            }
            let _ = ready_sender.send(String::new());
        });
        let ready = ready_receiver
            .recv_timeout(Duration::from_secs(2))
            .expect("fake runtime signals readiness after UDS bind");
        assert_eq!(ready, ready_line);
        fake
    }

    fn helper_http_response(
        session: &TransportSession,
        host: &str,
        extra_headers: &str,
    ) -> Vec<u8> {
        let config = ChildTransportConfig {
            instance_id: session.instance_id.clone(),
            secret: lock(&session.secret).as_ref().unwrap().to_owned(),
            directory: session.directory_handle.try_clone().unwrap(),
        };
        let listener = fake_listener(session);
        let socket_path = session.socket_path.clone();
        let server = thread::spawn(move || {
            assert!(config
                .serve_one(&listener, Duration::from_millis(300))
                .unwrap());
        });
        let mut stream = UnixStream::connect(socket_path).unwrap();
        let request = format!(
            "GET {HEALTH_ROUTE} HTTP/1.1\r\nHost: {host}\r\nConnection: close\r\nContent-Length: 0\r\nContent-Type: text/plain\r\n{extra_headers}\r\n"
        );
        stream.write_all(request.as_bytes()).unwrap();
        let mut response = Vec::new();
        stream.read_to_end(&mut response).unwrap();
        server.join().unwrap();
        response
    }

    #[test]
    fn hmac_matches_known_sha256_vector() {
        let result = hmac_sha256(&[0x0b; 20], b"Hi There").unwrap();
        assert_eq!(
            hex(&result),
            "b0344c61d8db38535ca8afceaf0bf12b881dc200c9833da726e9376c2e32cff7"
        );
    }

    #[test]
    fn consecutive_multiblock_messages_do_not_reuse_keystream() {
        let session = TransportSession::create("ctr-regression").unwrap();
        let first = session.next_envelope_nonce().unwrap();
        let second = session.next_envelope_nonce().unwrap();
        for direction in [b"request".as_slice(), b"response".as_slice()] {
            let (mut encryption, mut authentication) = session.envelope_keys(direction).unwrap();
            let mut unknown = [0_u8; 100];
            os_random(&mut unknown).unwrap();
            let known = [0_u8; 100];
            let a = seal_message(
                &session.instance_id,
                direction,
                &encryption,
                &authentication,
                &first,
                &unknown,
            )
            .unwrap();
            let b = seal_message(
                &session.instance_id,
                direction,
                &encryption,
                &authentication,
                &second,
                &known,
            )
            .unwrap();
            let v3_shared = shared_keystream_blocks(
                &a[16..a.len() - 32],
                &unknown,
                &b[16..b.len() - 32],
                &known,
            );
            let prefix = [0x11_u8; 8];
            let mut old_first = [0_u8; 16];
            let mut old_second = [0_u8; 16];
            old_first[..8].copy_from_slice(&prefix);
            old_second[..8].copy_from_slice(&prefix);
            old_first[8..].copy_from_slice(&1_u64.to_be_bytes());
            old_second[8..].copy_from_slice(&2_u64.to_be_bytes());
            let old_a = aes_ctr_xor(&encryption, &old_first, &unknown).unwrap();
            let old_b = aes_ctr_xor(&encryption, &old_second, &known).unwrap();
            let old_shared = shared_keystream_blocks(&old_a, &unknown, &old_b, &known);
            unknown.fill(0);
            encryption.fill(0);
            authentication.fill(0);
            assert!(old_shared > 0, "old counter layout was not detected");
            assert_eq!(v3_shared, 0, "consecutive messages reused CTR keystream");
        }
        session.revoke();
    }

    fn shared_keystream_blocks(
        left_ciphertext: &[u8],
        left_plaintext: &[u8],
        right_ciphertext: &[u8],
        right_plaintext: &[u8],
    ) -> usize {
        let left = keystream_blocks(left_ciphertext, left_plaintext);
        let right = keystream_blocks(right_ciphertext, right_plaintext);
        left.iter().filter(|block| right.contains(block)).count()
    }

    fn keystream_blocks(ciphertext: &[u8], plaintext: &[u8]) -> Vec<Vec<u8>> {
        let mut blocks = Vec::new();
        let mut offset = 0;
        while offset < ciphertext.len() {
            let end = (offset + 16).min(ciphertext.len());
            blocks.push(
                ciphertext[offset..end]
                    .iter()
                    .zip(&plaintext[offset..end])
                    .map(|(cipher_byte, plain_byte)| cipher_byte ^ plain_byte)
                    .collect(),
            );
            offset = end;
        }
        blocks
    }

    #[test]
    fn deactivation_is_synchronized_and_concurrent_seals_do_not_reuse_sequence() {
        let session = TransportSession::create("deactivate-race").unwrap();
        let first = session.next_envelope_nonce().unwrap();
        assert!(session
            .seal_application_request(APP_SESSION_OPEN_ROUTE, b"k=v\n", &first)
            .is_ok());
        let allocated = Arc::new(Mutex::new(Vec::<[u8; ENVELOPE_NONCE_BYTES]>::new()));
        let start = Arc::new(std::sync::Barrier::new(5));
        let mut workers = Vec::new();
        for _ in 0..4 {
            let session = Arc::clone(&session);
            let allocated = Arc::clone(&allocated);
            let start = Arc::clone(&start);
            workers.push(thread::spawn(move || {
                start.wait();
                for _ in 0..10_000 {
                    let Ok(nonce) = session.next_envelope_nonce() else {
                        break;
                    };
                    if session
                        .seal_application_request(APP_SESSION_OPEN_ROUTE, b"k=v\n", &nonce)
                        .is_ok()
                    {
                        allocated.lock().unwrap().push(nonce);
                    }
                }
            }));
        }
        start.wait();
        session.deactivate();
        for worker in workers {
            worker.join().unwrap();
        }
        let allocated = allocated.lock().unwrap();
        let mut unique = allocated.clone();
        unique.sort();
        unique.dedup();
        assert_eq!(unique.len(), allocated.len());
        assert!(session.next_envelope_nonce().is_err());
        assert!(session
            .seal_application_request(APP_SESSION_OPEN_ROUTE, b"k=v\n", &first)
            .is_err());
        assert_eq!(
            {
                let _request = session.lock_request();
                session.exchange_at(
                    &session.socket_path,
                    Verb::Post,
                    APPLICATION_ENVELOPE_ROUTE,
                    b"",
                )
            },
            Err(TransportError::Inactive)
        );
        assert!(lock(&session.secret).is_none());
        assert_eq!(session.envelope_sequence.load(Ordering::Acquire), u64::MAX);
        session.revoke();
    }

    #[test]
    fn inflight_send_finishes_before_deactivate_and_later_send_writes_nothing() {
        use std::sync::mpsc;

        let session = TransportSession::create("send-lifecycle-inflight").unwrap();
        let (entered_tx, entered_rx) = mpsc::channel();
        let entered = Arc::new(Mutex::new(Some(entered_tx)));
        let release = Arc::new(std::sync::Barrier::new(2));
        let entered_hook = Arc::clone(&entered);
        let release_hook = Arc::clone(&release);
        {
            let mut hook = lock(&session.transaction_barrier);
            *hook = Some(Arc::new(move |phase: &str| {
                if phase != "checked" {
                    return;
                }
                if let Some(sender) = entered_hook.lock().unwrap().take() {
                    sender.send(()).unwrap();
                }
                release_hook.wait();
            }));
        }

        let received = Arc::new(AtomicUsize::new(0));
        let received_server = Arc::clone(&received);
        let listener = fake_listener(&session);
        let server = thread::spawn(move || {
            let (mut stream, _) = listener.accept().unwrap();
            stream
                .set_read_timeout(Some(Duration::from_secs(2)))
                .unwrap();
            let mut payload = Vec::new();
            let mut buffer = [0_u8; 1024];
            loop {
                match stream.read(&mut buffer) {
                    Ok(0) => break,
                    Ok(count) => {
                        payload.extend_from_slice(&buffer[..count]);
                        if payload.windows(4).any(|window| window == b"\r\n\r\n") {
                            break;
                        }
                    }
                    Err(_) => break,
                }
            }
            received_server.store(payload.len(), Ordering::Release);
            let body = b"ok\n";
            let response = format!(
                "HTTP/1.1 200 OK\r\nContent-Length: {}\r\nContent-Type: text/plain\r\nConnection: close\r\n\r\n",
                body.len()
            );
            let _ = stream.write_all(response.as_bytes());
            let _ = stream.write_all(body);
        });

        let sending = Arc::clone(&session);
        let sender = thread::spawn(move || {
            let _request = sending.lock_request();
            sending.exchange_at(&sending.socket_path, Verb::Get, HEALTH_ROUTE, b"")
        });
        entered_rx
            .recv_timeout(Duration::from_secs(2))
            .expect("send reached the barrier between the activity check and the socket write");

        let deactivated = Arc::new(AtomicBool::new(false));
        let deactivated_flag = Arc::clone(&deactivated);
        let retiring = Arc::clone(&session);
        let retirement = thread::spawn(move || {
            retiring.deactivate();
            deactivated_flag.store(true, Ordering::Release);
        });
        session.wait_until_request_contended_for_test();
        assert!(
            !deactivated.load(Ordering::Acquire),
            "deactivate returned while the in-flight send still held the transaction"
        );
        release.wait();

        assert!(sender.join().unwrap().is_ok());
        retirement.join().unwrap();
        server.join().unwrap();
        let inflight_bytes = received.load(Ordering::Acquire);
        assert!(inflight_bytes > 0, "in-flight send wrote no bytes");

        {
            let mut hook = lock(&session.transaction_barrier);
            *hook = None;
        }
        let after = {
            let _request = session.lock_request();
            session.exchange_at(&session.socket_path, Verb::Get, HEALTH_ROUTE, b"")
        };
        assert_eq!(after, Err(TransportError::Inactive));
        assert_eq!(received.load(Ordering::Acquire), inflight_bytes);
        assert!(lock(&session.secret).is_none());
        assert_eq!(session.envelope_sequence.load(Ordering::Acquire), u64::MAX);
        assert!(session.next_envelope_nonce().is_err());
        assert!(session
            .seal_application_request(APP_SESSION_OPEN_ROUTE, b"k=v\n", &[0; 16])
            .is_err());
        session.revoke();

        let blocked = TransportSession::create("send-lifecycle-deactivate-first").unwrap();
        blocked.deactivate();
        let listener = fake_listener(&blocked);
        listener.set_nonblocking(true).unwrap();
        let rejected = {
            let _request = blocked.lock_request();
            blocked.exchange_at(&blocked.socket_path, Verb::Get, HEALTH_ROUTE, b"")
        };
        assert_eq!(rejected, Err(TransportError::Inactive));
        match listener.accept() {
            Err(error) if error.kind() == io::ErrorKind::WouldBlock => {}
            Ok(_) => panic!("deactivate-first send connected"),
            Err(error) => panic!("deactivate-first accept failed: {error}"),
        }
        assert!(lock(&blocked.secret).is_none());
        assert_eq!(blocked.envelope_sequence.load(Ordering::Acquire), u64::MAX);
        assert!(blocked.next_envelope_nonce().is_err());
        blocked.revoke();

        let session = TransportSession::create("send-lifecycle-response-open").unwrap();
        let order = Arc::new(Mutex::new(Vec::new()));
        let (entered_tx, entered_rx) = mpsc::channel();
        let entered = Arc::new(Mutex::new(Some(entered_tx)));
        let release = Arc::new(std::sync::Barrier::new(2));
        let entered_hook = Arc::clone(&entered);
        let release_hook = Arc::clone(&release);
        let order_hook = Arc::clone(&order);
        {
            let mut hook = lock(&session.transaction_barrier);
            *hook = Some(Arc::new(move |phase: &str| {
                if phase == "received" {
                    if let Some(sender) = entered_hook.lock().unwrap().take() {
                        sender.send(()).unwrap();
                    }
                    release_hook.wait();
                } else if phase == "opened" {
                    order_hook.lock().unwrap().push("opened");
                }
            }));
        }
        let accepts = Arc::new(AtomicUsize::new(0));
        let stop = Arc::new(AtomicBool::new(false));
        let server = serve_openable_response(&session, Arc::clone(&accepts), Arc::clone(&stop));
        let worker = Arc::clone(&session);
        let call =
            thread::spawn(move || worker.call_g5_application(APP_SESSION_OPEN_ROUTE, b"k=v\n"));
        entered_rx
            .recv_timeout(Duration::from_secs(2))
            .expect("response was not paused after the read and before open");
        assert!(order.lock().unwrap().is_empty());
        let deactivated = Arc::new(AtomicBool::new(false));
        let deactivated_flag = Arc::clone(&deactivated);
        let order_retirement = Arc::clone(&order);
        let retiring = Arc::clone(&session);
        let retirement = thread::spawn(move || {
            retiring.deactivate();
            order_retirement.lock().unwrap().push("deactivated");
            deactivated_flag.store(true, Ordering::Release);
        });
        session.wait_until_request_contended_for_test();
        assert!(
            !deactivated.load(Ordering::Acquire),
            "deactivate returned while the response was paused before open"
        );
        assert!(order.lock().unwrap().is_empty());
        release.wait();
        assert_eq!(call.join().unwrap(), Ok(b"ok".to_vec()));
        retirement.join().unwrap();
        assert_eq!(order.lock().unwrap().as_slice(), ["opened", "deactivated"]);
        assert!(deactivated.load(Ordering::Acquire));
        let accepts_after_open = accepts.load(Ordering::Acquire);
        assert_eq!(accepts_after_open, 4);
        {
            let mut hook = lock(&session.transaction_barrier);
            *hook = None;
        }
        assert_eq!(
            session.call_g5_application(APP_SESSION_OPEN_ROUTE, b"k=v\n"),
            Err(TransportError::Inactive)
        );
        assert_eq!(accepts.load(Ordering::Acquire), accepts_after_open);
        assert!(lock(&session.secret).is_none());
        assert_eq!(session.envelope_sequence.load(Ordering::Acquire), u64::MAX);
        assert!(session.next_envelope_nonce().is_err());
        stop.store(true, Ordering::Release);
        server.join().unwrap();
        session.revoke();
    }

    fn serve_openable_response(
        session: &TransportSession,
        accepts: Arc<AtomicUsize>,
        stop: Arc<AtomicBool>,
    ) -> JoinHandle<()> {
        let instance_id = session.instance_id.clone();
        let mut secret = lock(&session.secret).as_ref().unwrap().to_owned();
        let (mut encryption_key, mut authentication_key) =
            derive_envelope_keys(&secret, &instance_id, b"response").unwrap();
        let listener = fake_listener(session);
        listener.set_nonblocking(true).unwrap();
        thread::spawn(move || {
            let deadline = Instant::now() + Duration::from_secs(3);
            while !stop.load(Ordering::Acquire) && Instant::now() < deadline {
                let mut stream = match listener.accept() {
                    Ok((stream, _)) => stream,
                    Err(error) if error.kind() == io::ErrorKind::WouldBlock => {
                        thread::sleep(Duration::from_millis(5));
                        continue;
                    }
                    Err(_) => break,
                };
                stream.set_nonblocking(false).unwrap();
                accepts.fetch_add(1, Ordering::Release);
                let (start, body) = read_fake_request(&mut stream);
                let route = start.split_whitespace().nth(1).unwrap_or_default();
                if route == APPLICATION_ENVELOPE_ROUTE {
                    let nonce: [u8; ENVELOPE_NONCE_BYTES] =
                        body[..ENVELOPE_NONCE_BYTES].try_into().unwrap();
                    let frame = [ENVELOPE_VERSION, 0, 200, 0, 0, 0, 2, b'o', b'k'];
                    let envelope = seal_message(
                        &instance_id,
                        b"response",
                        &encryption_key,
                        &authentication_key,
                        &nonce,
                        &frame,
                    )
                    .unwrap();
                    let header = format!(
                        "HTTP/1.1 200 OK\r\nContent-Length: {}\r\nConnection: close\r\nContent-Type: application/octet-stream\r\n\r\n",
                        envelope.len()
                    );
                    let _ = stream.write_all(header.as_bytes());
                    let _ = stream.write_all(&envelope);
                } else {
                    let response = if route == HEALTH_ROUTE {
                        b"ok\n".to_vec()
                    } else if route == VERSION_ROUTE {
                        version_body(&instance_id, PROTOCOL_VERSION)
                    } else if route == PROOF_ROUTE {
                        let nonce = std::str::from_utf8(&body).unwrap();
                        proof_body(&instance_id, nonce, &secret)
                    } else {
                        b"no\n".to_vec()
                    };
                    write_fake_response(&mut stream, "200 OK", &response);
                }
            }
            secret.fill(0);
            encryption_key.fill(0);
            authentication_key.fill(0);
        })
    }

    #[test]
    fn g5_transaction_barriers_cover_admission_seal_and_prewrite_check() {
        use std::sync::mpsc;

        fn arm(
            session: &TransportSession,
            phase: &'static str,
        ) -> (mpsc::Receiver<()>, Arc<std::sync::Barrier>) {
            let (entered_tx, entered_rx) = mpsc::channel();
            let entered = Arc::new(Mutex::new(Some(entered_tx)));
            let release = Arc::new(std::sync::Barrier::new(2));
            let entered_hook = Arc::clone(&entered);
            let release_hook = Arc::clone(&release);
            let mut hook = lock(&session.transaction_barrier);
            *hook = Some(Arc::new(move |current: &str| {
                if current != phase {
                    return;
                }
                if let Some(sender) = entered_hook.lock().unwrap().take() {
                    sender.send(()).unwrap();
                }
                release_hook.wait();
            }));
            (entered_rx, release)
        }

        fn serve_probe(
            session: &TransportSession,
            secure_bytes: Arc<AtomicUsize>,
            accepts: Arc<AtomicUsize>,
            stop: Arc<AtomicBool>,
        ) -> JoinHandle<()> {
            let instance_id = session.instance_id.clone();
            let mut secret = lock(&session.secret).as_ref().unwrap().to_owned();
            let listener = fake_listener(session);
            listener.set_nonblocking(true).unwrap();
            thread::spawn(move || {
                let deadline = Instant::now() + Duration::from_secs(3);
                while !stop.load(Ordering::Acquire) && Instant::now() < deadline {
                    let mut stream = match listener.accept() {
                        Ok((stream, _)) => stream,
                        Err(error) if error.kind() == io::ErrorKind::WouldBlock => {
                            thread::sleep(Duration::from_millis(5));
                            continue;
                        }
                        Err(_) => break,
                    };
                    stream.set_nonblocking(false).unwrap();
                    accepts.fetch_add(1, Ordering::Release);
                    let (start, body) = read_fake_request(&mut stream);
                    let route = start.split_whitespace().nth(1).unwrap_or_default();
                    if route == APPLICATION_ENVELOPE_ROUTE {
                        secure_bytes.fetch_add(body.len(), Ordering::Release);
                        let response = b"x";
                        let header = format!(
                            "HTTP/1.1 200 OK\r\nContent-Length: {}\r\nConnection: close\r\nContent-Type: application/octet-stream\r\n\r\n",
                            response.len()
                        );
                        let _ = stream.write_all(header.as_bytes());
                        let _ = stream.write_all(response);
                    } else {
                        let response = if route == HEALTH_ROUTE {
                            b"ok\n".to_vec()
                        } else if route == VERSION_ROUTE {
                            version_body(&instance_id, PROTOCOL_VERSION)
                        } else if route == PROOF_ROUTE {
                            let nonce = std::str::from_utf8(&body).unwrap();
                            proof_body(&instance_id, nonce, &secret)
                        } else {
                            b"no\n".to_vec()
                        };
                        write_fake_response(&mut stream, "200 OK", &response);
                    }
                }
                secret.fill(0);
            })
        }

        for phase in ["admitted", "sealed"] {
            let session = TransportSession::create(&format!("g5-barrier-{phase}")).unwrap();
            let secure_bytes = Arc::new(AtomicUsize::new(0));
            let accepts = Arc::new(AtomicUsize::new(0));
            let stop = Arc::new(AtomicBool::new(false));
            let server = serve_probe(
                &session,
                Arc::clone(&secure_bytes),
                Arc::clone(&accepts),
                Arc::clone(&stop),
            );
            let (entered_rx, release) = arm(&session, phase);
            let worker = Arc::clone(&session);
            let call =
                thread::spawn(move || worker.call_g5_application(APP_SESSION_OPEN_ROUTE, b"k=v\n"));
            entered_rx
                .recv_timeout(Duration::from_secs(2))
                .unwrap_or_else(|_| panic!("{phase} barrier was not reached"));
            if phase == "admitted" {
                assert_eq!(accepts.load(Ordering::Acquire), 0);
            } else {
                assert_eq!(secure_bytes.load(Ordering::Acquire), 0);
                assert_eq!(accepts.load(Ordering::Acquire), 3);
            }
            let done = Arc::new(AtomicBool::new(false));
            let done_flag = Arc::clone(&done);
            let retiring = Arc::clone(&session);
            let retirement = thread::spawn(move || {
                retiring.deactivate();
                done_flag.store(true, Ordering::Release);
            });
            session.wait_until_request_contended_for_test();
            assert!(!done.load(Ordering::Acquire));
            release.wait();
            let _ = call.join().unwrap();
            retirement.join().unwrap();
            stop.store(true, Ordering::Release);
            server.join().unwrap();
            if phase == "sealed" {
                assert!(secure_bytes.load(Ordering::Acquire) > 0);
            }
            let accepts_after = accepts.load(Ordering::Acquire);
            {
                let mut hook = lock(&session.transaction_barrier);
                *hook = None;
            }
            assert_eq!(
                session.call_g5_application(APP_SESSION_OPEN_ROUTE, b"k=v\n"),
                Err(TransportError::Inactive)
            );
            assert_eq!(accepts.load(Ordering::Acquire), accepts_after);
            assert!(lock(&session.secret).is_none());
            assert_eq!(session.envelope_sequence.load(Ordering::Acquire), u64::MAX);
            assert!(session.next_envelope_nonce().is_err());
            session.revoke();
        }

        let blocked = TransportSession::create("g5-barrier-deactivate-first").unwrap();
        blocked.deactivate();
        let listener = fake_listener(&blocked);
        listener.set_nonblocking(true).unwrap();
        assert_eq!(
            blocked.call_g5_application(APP_SESSION_OPEN_ROUTE, b"k=v\n"),
            Err(TransportError::Inactive)
        );
        match listener.accept() {
            Err(error) if error.kind() == io::ErrorKind::WouldBlock => {}
            Ok(_) => panic!("call after deactivate connected"),
            Err(error) => panic!("accept after deactivate failed: {error}"),
        }
        assert!(lock(&blocked.secret).is_none());
        assert_eq!(blocked.envelope_sequence.load(Ordering::Acquire), u64::MAX);
        blocked.revoke();
    }

    #[test]
    fn ctr_partition_bounds_sequence_wrap_and_real_block_progression() {
        let session = TransportSession::create("ctr-boundary").unwrap();
        for sequence in [1_u64, 2, u64::MAX - 1, u64::MAX] {
            let mut nonce = [0_u8; 16];
            nonce[..8].copy_from_slice(&sequence.to_be_bytes());
            for (direction, limit) in [
                (b"request".as_slice(), MAX_ENVELOPE_REQUEST_BYTES - 48),
                (b"response".as_slice(), MAX_RESPONSE_BODY_BYTES + 7),
            ] {
                let start = u128::from_be_bytes(nonce);
                let last = start + limit.div_ceil(16) as u128 - 1;
                assert_eq!(last >> 64, sequence as u128);
                assert!(validate_counter_partition(direction, &nonce, limit).is_ok());
                let (mut ek, mut ak) = session.envelope_keys(direction).unwrap();
                let sealed = seal_message(
                    &session.instance_id,
                    direction,
                    &ek,
                    &ak,
                    &nonce,
                    &vec![0; limit],
                )
                .unwrap();
                assert!(open_message(&session.instance_id, direction, &ek, &ak, &sealed).is_ok());
                assert!(seal_message(
                    &session.instance_id,
                    direction,
                    &ek,
                    &ak,
                    &nonce,
                    &vec![0; limit + 1]
                )
                .is_err());
                // A valid MAC cannot bypass the size limit in the production opener.
                let ciphertext = aes_ctr_xor(&ek, &nonce, &vec![0; limit + 1]).unwrap();
                let tag = hmac_sha256(
                    &ak,
                    &envelope_mac_message(&session.instance_id, direction, &nonce, &ciphertext),
                )
                .unwrap();
                let mut oversized = nonce.to_vec();
                oversized.extend_from_slice(&ciphertext);
                oversized.extend_from_slice(&tag);
                assert!(
                    open_message(&session.instance_id, direction, &ek, &ak, &oversized).is_err()
                );
                let stream = aes_ctr_xor(&ek, &nonce, &vec![0; 16 * 129]).unwrap();
                for block in [0_usize, 1, 77, 128] {
                    let mut counter = nonce;
                    counter[8..].copy_from_slice(&(block as u64).to_be_bytes());
                    let independent = aes_ctr_xor(&ek, &counter, &[0; 16]).unwrap();
                    assert!(stream[block * 16..(block + 1) * 16] == independent);
                }
                ek.fill(0);
                ak.fill(0);
            }
        }
        assert!(validate_counter_partition(b"request", &[0; 16], 32).is_err());
        let mut invalid = [0_u8; 16];
        invalid[7] = 1;
        invalid[15] = 1;
        assert!(validate_counter_partition(b"request", &invalid, 32).is_err());
        session
            .envelope_sequence
            .store(u64::MAX - 1, Ordering::Release);
        let last = session.next_envelope_nonce().unwrap();
        assert!(last[..8] == u64::MAX.to_be_bytes());
        assert!(session.next_envelope_nonce().is_err());
        assert_eq!(session.envelope_sequence.load(Ordering::Acquire), u64::MAX);
    }

    #[test]
    fn production_crypto_interoperates_with_python_in_both_directions() {
        use std::process::{Command, Stdio};
        let api = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../api");
        let script = r#"
import sys
import native_runtime as n
raw = sys.stdin.buffer.read()
identity = n.NativeRuntimeIdentity('ctr-interop', bytearray(raw[:32]), 1, 1)
direction = sys.argv[1].encode('ascii')
nonce = raw[32:48]
envelope = raw[48:]
_, plaintext = n._open_application_envelope(identity, direction, envelope)
limit = n.CTR_REQUEST_MAX_BYTES if direction == b'request' else n.CTR_RESPONSE_MAX_BYTES
if plaintext != bytes(i % 251 for i in range(limit)): raise SystemExit(2)
python_envelope = n._seal_application_envelope(identity, direction, nonce, plaintext)
if python_envelope != envelope: raise SystemExit(3)
identity.clear()
sys.stdout.buffer.write(python_envelope)
"#;
        let session = TransportSession::create("ctr-interop").unwrap();
        for (direction, size) in [
            (b"request".as_slice(), MAX_ENVELOPE_REQUEST_BYTES - 48),
            (b"response".as_slice(), MAX_RESPONSE_BODY_BYTES + 7),
        ] {
            let nonce = session.next_envelope_nonce().unwrap();
            let (mut ek, mut ak) = session.envelope_keys(direction).unwrap();
            let plaintext: Vec<u8> = (0..size).map(|i| (i % 251) as u8).collect();
            let envelope = seal_message(
                &session.instance_id,
                direction,
                &ek,
                &ak,
                &nonce,
                &plaintext,
            )
            .unwrap();
            let mut child = Command::new(api.join(".venv/bin/python"))
                .args(["-B", "-c", script, std::str::from_utf8(direction).unwrap()])
                .current_dir(&api)
                .env_clear()
                .stdin(Stdio::piped())
                .stdout(Stdio::piped())
                .stderr(Stdio::null())
                .spawn()
                .unwrap();
            {
                let mut input = child.stdin.take().unwrap();
                let secret = lock(&session.secret);
                input.write_all(secret.as_ref().unwrap()).unwrap();
                input.write_all(&nonce).unwrap();
                input.write_all(&envelope).unwrap();
            }
            let output = child.wait_with_output().unwrap();
            assert!(output.status.success(), "cross-language crypto failed");
            let opened =
                open_message(&session.instance_id, direction, &ek, &ak, &output.stdout).unwrap();
            assert!(opened == plaintext, "Python to Rust decryption failed");
            ek.fill(0);
            ak.fill(0);
        }
    }

    #[test]
    fn commoncrypt_aes256_ctr_matches_nist_vector() {
        let key = decode_hex_array::<32>(
            b"603deb1015ca71be2b73aef0857d7781\
              1f352c073b6108d72d9810a30914dff4"
                .iter()
                .copied()
                .filter(|byte| !byte.is_ascii_whitespace())
                .collect::<Vec<_>>()
                .as_slice(),
        )
        .unwrap();
        let nonce =
            decode_hex_array::<ENVELOPE_NONCE_BYTES>(b"f0f1f2f3f4f5f6f7f8f9fafbfcfdfeff").unwrap();
        let plaintext = decode_hex_array::<16>(b"6bc1bee22e409f96e93d7e117393172a").unwrap();
        let ciphertext = aes_ctr_xor(&key, &nonce, &plaintext).unwrap();
        assert_eq!(hex(&ciphertext), "601ec313775789a5b7a7f504bbf3d228");
    }

    #[test]
    fn application_envelope_encrypts_sensitive_request_fields() {
        let session = TransportSession::create("envelope-confidentiality").unwrap();
        let body = b"passphrase=synthetic-passphrase-never-send-plain\nsession_token=synthetic-session-token-secret\ncsrf_token=synthetic-csrf-secret\ngrant_id=synthetic-grant-secret\nmission_title=synthetic-mission-secret\n";
        let mut nonce = [0_u8; ENVELOPE_NONCE_BYTES];
        nonce[..ENVELOPE_SEQUENCE_BYTES].copy_from_slice(&7_u64.to_be_bytes());
        let envelope = session
            .seal_application_request(APP_SESSION_OPEN_ROUTE, body, &nonce)
            .unwrap();
        for secret in [
            b"synthetic-passphrase-never-send-plain".as_slice(),
            b"synthetic-session-token-secret".as_slice(),
            b"synthetic-csrf-secret".as_slice(),
            b"synthetic-grant-secret".as_slice(),
            b"synthetic-mission-secret".as_slice(),
        ] {
            assert!(!envelope
                .windows(secret.len())
                .any(|window| window == secret));
        }
        session.revoke();
    }

    #[test]
    fn encrypted_response_tampering_and_generation_replay_are_rejected() {
        let session = TransportSession::create("envelope-generation-a").unwrap();
        let mut nonce = [0_u8; ENVELOPE_NONCE_BYTES];
        nonce[..ENVELOPE_SEQUENCE_BYTES].copy_from_slice(&1_u64.to_be_bytes());
        let frame = [ENVELOPE_VERSION, 0, 200, 0, 0, 0, 2, b'o', b'k'];
        let (mut encryption_key, mut authentication_key) =
            session.envelope_keys(b"response").unwrap();
        let mut envelope = seal_message(
            &session.instance_id,
            b"response",
            &encryption_key,
            &authentication_key,
            &nonce,
            &frame,
        )
        .unwrap();
        for position in [0, 16, envelope.len() - 1] {
            envelope[position] ^= 1;
            assert!(open_message(
                &session.instance_id,
                b"response",
                &encryption_key,
                &authentication_key,
                &envelope
            )
            .is_err());
            envelope[position] ^= 1;
        }
        let other_generation = TransportSession::create("envelope-generation-b").unwrap();
        let (mut other_encryption, mut other_authentication) =
            other_generation.envelope_keys(b"response").unwrap();
        assert_eq!(
            open_message(
                &other_generation.instance_id,
                b"response",
                &other_encryption,
                &other_authentication,
                &envelope,
            ),
            Err(TransportError::ProofRejected)
        );
        encryption_key.fill(0);
        authentication_key.fill(0);
        other_encryption.fill(0);
        other_authentication.fill(0);
        session.revoke();
        other_generation.revoke();
    }

    #[test]
    fn http_field_parser_rejects_duplicates_and_unknown_field_count() {
        assert_eq!(
            parse_fields(b"a=1\na=2\n", 2),
            Err(TransportError::MalformedResponse)
        );
        assert_eq!(
            parse_fields(b"a=1\n", 2),
            Err(TransportError::MalformedResponse)
        );
    }

    #[test]
    fn fake_health_and_version_process_without_capability_is_rejected() {
        let session = TransportSession::create("fake-instance").unwrap();
        let fake = spawn_fake_process(&session, false);
        assert_eq!(session.probe(), Err(TransportError::ProofRejected));
        drop(fake);
        session.revoke();
    }

    #[test]
    fn fake_runtime_crashing_during_proof_request_fails_closed() {
        let session = TransportSession::create("crash-instance").unwrap();
        let mut fake = spawn_fake_process(&session, true);
        assert_eq!(session.probe(), Err(TransportError::MalformedResponse));
        assert_eq!(fake.wait_for_exit().code(), Some(42));
        drop(fake);
        session.revoke();
    }

    #[test]
    fn helper_requires_fixed_host_and_rejects_browser_origin_without_cors() {
        let wrong_host_session = TransportSession::create("host-check").unwrap();
        let wrong_host = helper_http_response(&wrong_host_session, "example.test", "");
        assert!(wrong_host.starts_with(b"HTTP/1.1 400 Bad Request\r\n"));
        assert!(!wrong_host
            .windows(b"Access-Control-Allow-Origin".len())
            .any(|window| window.eq_ignore_ascii_case(b"Access-Control-Allow-Origin")));
        wrong_host_session.revoke();

        let origin_session = TransportSession::create("origin-check").unwrap();
        let origin = helper_http_response(
            &origin_session,
            "jarvis.local",
            "Origin: tauri://localhost\r\n",
        );
        assert!(origin.starts_with(b"HTTP/1.1 400 Bad Request\r\n"));
        assert!(!origin
            .windows(b"Access-Control-Allow-Origin".len())
            .any(|window| window.eq_ignore_ascii_case(b"Access-Control-Allow-Origin")));
        origin_session.revoke();
    }

    #[test]
    fn wrong_proof_and_replayed_proof_are_rejected() {
        let session = TransportSession::create("proof-instance").unwrap();
        let invalid = format!(
            "protocol_version={PROTOCOL_VERSION}\nruntime_kind={RUNTIME_KIND}\ninstance_id=proof-instance\nbuild={BUILD_ID}\noperation_result=pong:proof-instance\nproof={}\n",
            "00".repeat(32)
        )
        .into_bytes();
        let server = fake_server(
            &session,
            vec![
                FakeReply::Body(b"ok\n".to_vec()),
                FakeReply::Body(version_body("proof-instance", PROTOCOL_VERSION)),
                FakeReply::Body(invalid),
            ],
        );
        assert_eq!(session.probe(), Err(TransportError::ProofRejected));
        server.join().unwrap();

        let mut stale_nonce = [0x5a_u8; NONCE_BYTES];
        let stale_hex = hex(&stale_nonce);
        let secret = lock(&session.secret).as_ref().unwrap().to_owned();
        let replay = proof_body("proof-instance", &stale_hex, &secret);
        stale_nonce.fill(0);
        let server = fake_server(
            &session,
            vec![
                FakeReply::Body(b"ok\n".to_vec()),
                FakeReply::Body(version_body("proof-instance", PROTOCOL_VERSION)),
                FakeReply::Body(replay),
            ],
        );
        assert_eq!(session.probe(), Err(TransportError::ProofRejected));
        server.join().unwrap();
        session.revoke();
    }

    #[test]
    fn incompatible_protocol_is_rejected_before_proof() {
        let session = TransportSession::create("version-instance").unwrap();
        let server = fake_server(
            &session,
            vec![
                FakeReply::Body(b"ok\n".to_vec()),
                FakeReply::Body(version_body("version-instance", "2")),
            ],
        );
        assert_eq!(session.probe(), Err(TransportError::IncompatibleVersion));
        server.join().unwrap();
        session.revoke();
    }

    #[test]
    fn malformed_oversized_slow_and_closed_responses_fail_closed() {
        let session = TransportSession::create("failure-instance").unwrap();
        let server = fake_server(
            &session,
            vec![FakeReply::Wire(b"not-http\r\n\r\n".to_vec())],
        );
        assert_eq!(session.probe(), Err(TransportError::MalformedResponse));
        server.join().unwrap();

        let server = fake_server(
            &session,
            vec![FakeReply::Wire(
                b"HTTP/1.1 200 OK\r\nContent-Length: 2049\r\n\r\n".to_vec(),
            )],
        );
        assert_eq!(session.probe(), Err(TransportError::ResponseTooLarge));
        server.join().unwrap();

        let server = fake_server(&session, vec![FakeReply::Hang(Duration::from_millis(1200))]);
        let started = Instant::now();
        assert_eq!(session.probe(), Err(TransportError::Timeout));
        assert!(started.elapsed() < Duration::from_millis(1100));
        server.join().unwrap();

        let server = fake_server(&session, vec![FakeReply::Close]);
        assert_eq!(session.probe(), Err(TransportError::MalformedResponse));
        server.join().unwrap();
        session.revoke();
    }

    #[test]
    fn response_http_framing_subset_rejects_malformed_and_extra_bytes() {
        let cases: Vec<(&str, Vec<u8>, TransportError)> = vec![
            (
                "malformed CRLF",
                b"HTTP/1.1 200 OK\nContent-Length: 3\n\nok\n".to_vec(),
                TransportError::MalformedResponse,
            ),
            (
                "bytes after one framed response",
                b"HTTP/1.1 200 OK\r\nContent-Length: 3\r\n\r\nok\nHTTP/1.1 200 OK\r\nContent-Length: 3\r\n\r\nok\n".to_vec(),
                TransportError::MalformedResponse,
            ),
            (
                "duplicate Content-Length",
                b"HTTP/1.1 200 OK\r\nContent-Length: 3\r\nContent-Length: 3\r\n\r\nok\n".to_vec(),
                TransportError::MalformedResponse,
            ),
            (
                "conflicting Content-Length",
                b"HTTP/1.1 200 OK\r\nContent-Length: 3\r\nContent-Length: 4\r\n\r\nok\n".to_vec(),
                TransportError::MalformedResponse,
            ),
            (
                "truncated body",
                b"HTTP/1.1 200 OK\r\nContent-Length: 5\r\n\r\nok\n".to_vec(),
                TransportError::MalformedResponse,
            ),
            (
                "invalid Content-Length",
                b"HTTP/1.1 200 OK\r\nContent-Length: nope\r\n\r\nok\n".to_vec(),
                TransportError::MalformedResponse,
            ),
            (
                "Transfer-Encoding",
                b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\nContent-Length: 3\r\n\r\nok\n".to_vec(),
                TransportError::MalformedResponse,
            ),
            (
                "oversized body",
                b"HTTP/1.1 200 OK\r\nContent-Length: 2049\r\n\r\n".to_vec(),
                TransportError::ResponseTooLarge,
            ),
        ];

        for (name, wire, expected) in cases {
            let session = TransportSession::create(&format!("framing-{name}")).unwrap();
            let server = fake_server(&session, vec![FakeReply::Wire(wire)]);
            assert_eq!(session.probe(), Err(expected), "{name}");
            server.join().unwrap();
            session.revoke();
        }

        let session = TransportSession::create("oversized-header").unwrap();
        let wire = format!(
            "HTTP/1.1 200 OK\r\nX-Pad: {}\r\nContent-Length: 3\r\n\r\nok\n",
            "x".repeat(MAX_RESPONSE_HEADER_BYTES)
        )
        .into_bytes();
        let server = fake_server(&session, vec![FakeReply::Wire(wire)]);
        assert_eq!(session.probe(), Err(TransportError::ResponseTooLarge));
        server.join().unwrap();
        session.revoke();
    }

    #[test]
    fn supervisor_loss_during_inflight_proof_suppresses_late_response() {
        let session = TransportSession::create("eof-inflight-proof").unwrap();
        let config = ChildTransportConfig {
            instance_id: session.instance_id.clone(),
            secret: lock(&session.secret).as_ref().unwrap().to_owned(),
            directory: session.directory_handle.try_clone().unwrap(),
        };
        let listener = fake_listener(&session);
        let live = Arc::new(AtomicBool::new(true));
        let server_live = Arc::clone(&live);
        let (accepted_sender, accepted_receiver) = std::sync::mpsc::channel();
        let server = thread::spawn(move || {
            config.serve_one_with_accept_hook_for_test(
                &listener,
                Duration::from_secs(2),
                &server_live,
                accepted_sender,
            )
        });

        let mut client = UnixStream::connect(&session.socket_path).unwrap();
        let body = "00".repeat(NONCE_BYTES);
        let header = format!(
            "POST {PROOF_ROUTE} HTTP/1.1\r\nHost: jarvis.local\r\nConnection: close\r\nContent-Length: {}\r\nContent-Type: text/plain\r\n\r\n",
            body.len()
        );
        client.write_all(header.as_bytes()).unwrap();
        client.write_all(&body.as_bytes()[..16]).unwrap();
        accepted_receiver
            .recv_timeout(Duration::from_secs(1))
            .expect("server accepted the in-flight request");
        live.store(false, Ordering::Release);
        client.write_all(&body.as_bytes()[16..]).unwrap();
        let mut response = Vec::new();
        client.read_to_end(&mut response).unwrap();
        assert!(
            response.is_empty(),
            "late response escaped after supervisor loss"
        );
        assert_eq!(server.join().unwrap(), Err(TransportError::Inactive));
        session.revoke();
    }

    #[test]
    fn proof_is_bound_to_instance_version_build_and_nonce() {
        let version = Version {
            protocol: "1".to_owned(),
            runtime_kind: RUNTIME_KIND.to_owned(),
            instance_id: "A".to_owned(),
            build: BUILD_ID.to_owned(),
        };
        assert_ne!(
            proof_message(&version, "00", "pong:A"),
            proof_message(&version, "01", "pong:A")
        );
        assert_ne!(
            proof_message(&version, "00", "pong:A"),
            proof_message(&version, "00", "pong:B")
        );
        let mut other = version;
        other.instance_id = "B".to_owned();
        assert_ne!(
            proof_message(&other, "00", "pong:A"),
            proof_message(
                &Version {
                    protocol: "1".to_owned(),
                    runtime_kind: RUNTIME_KIND.to_owned(),
                    instance_id: "A".to_owned(),
                    build: BUILD_ID.to_owned()
                },
                "00",
                "pong:A"
            )
        );
    }

    #[test]
    fn session_uses_private_uds_path_and_revocation_removes_it() {
        let session = TransportSession::create("instance-test").unwrap();
        assert!(session.directory.exists());
        assert_eq!(
            fs::metadata(&session.directory)
                .unwrap()
                .permissions()
                .mode()
                & 0o777,
            0o700
        );
        assert!(session.socket_path.as_os_str().as_bytes().len() < 104);
        assert!(session.path_matches_handle());
        session.revoke();
        assert!(
            session.directory.exists(),
            "safe cleanup retains the empty directory"
        );
        assert!(fs::symlink_metadata(&session.socket_path).is_err());
        assert_eq!(session.probe(), Err(TransportError::Inactive));
    }

    #[test]
    fn cleanup_is_anchored_to_original_directory_across_replacement_matrix() {
        #[derive(Clone, Copy)]
        enum Replacement {
            File,
            SymlinkToFile,
            SymlinkToDirectory,
            NewDirectory,
            FakeSocket,
        }

        let canaries = Canaries::create();
        for (index, replacement) in [
            Replacement::File,
            Replacement::SymlinkToFile,
            Replacement::SymlinkToDirectory,
            Replacement::NewDirectory,
            Replacement::FakeSocket,
        ]
        .into_iter()
        .enumerate()
        {
            let session = TransportSession::create(&format!("path-matrix-{index}")).unwrap();
            let original_path = session.directory_path().to_path_buf();
            let retained = canaries.root.join(format!("session-original-{index}"));
            fs::rename(&original_path, &retained).unwrap();
            let fake_socket = match replacement {
                Replacement::File => {
                    fs::write(&original_path, b"replacement-file").unwrap();
                    None
                }
                Replacement::SymlinkToFile => {
                    std::os::unix::fs::symlink(canaries.root.join("canary.txt"), &original_path)
                        .unwrap();
                    None
                }
                Replacement::SymlinkToDirectory => {
                    std::os::unix::fs::symlink(&canaries.root, &original_path).unwrap();
                    None
                }
                Replacement::NewDirectory => {
                    fs::create_dir(&original_path).unwrap();
                    fs::write(original_path.join("runtime.sock"), b"replacement-directory")
                        .unwrap();
                    None
                }
                Replacement::FakeSocket => Some(UnixListener::bind(&original_path).unwrap()),
            };

            session.revoke();
            canaries.assert_intact();
            assert!(retained.is_dir());
            if matches!(replacement, Replacement::NewDirectory) {
                assert_eq!(
                    fs::read(original_path.join("runtime.sock")).unwrap(),
                    b"replacement-directory"
                );
            }
            drop(fake_socket);
            match replacement {
                Replacement::NewDirectory => {
                    fs::remove_file(original_path.join("runtime.sock")).unwrap();
                    fs::remove_dir(&original_path).unwrap();
                }
                Replacement::FakeSocket => fs::remove_file(&original_path).unwrap(),
                _ => fs::remove_file(&original_path).unwrap(),
            }
            fs::remove_dir(&retained).unwrap();
        }
        canaries.assert_intact();
    }

    #[test]
    fn cleanup_after_bind_and_renamed_parent_preserves_external_canaries() {
        let canaries = Canaries::create();
        let session = TransportSession::create("path-after-bind").unwrap();
        let listener = UnixListener::bind(&session.socket_path).unwrap();
        fs::set_permissions(&session.socket_path, fs::Permissions::from_mode(0o600)).unwrap();
        let original_path = session.directory_path().to_path_buf();
        let retained = canaries.root.join("post-bind-original");
        fs::rename(&original_path, &retained).unwrap();
        std::os::unix::fs::symlink(&canaries.root, &original_path).unwrap();

        session.revoke();
        canaries.assert_intact();
        assert!(fs::symlink_metadata(retained.join("runtime.sock")).is_err());
        drop(listener);
        fs::remove_file(&original_path).unwrap();
        fs::remove_dir(&retained).unwrap();
        canaries.assert_intact();
    }

    #[test]
    fn child_drop_after_parent_rename_preserves_external_canaries() {
        let canaries = Canaries::create();
        let session = TransportSession::create("child-cleanup-after-rename").unwrap();
        let config = ChildTransportConfig {
            instance_id: session.instance_id.clone(),
            secret: lock(&session.secret).as_ref().unwrap().to_owned(),
            directory: session.directory_handle.try_clone().unwrap(),
        };
        let listener = UnixListener::bind(&session.socket_path).unwrap();
        let original_path = session.directory_path().to_path_buf();
        let retained = canaries.root.join("child-cleanup-original");
        fs::rename(&original_path, &retained).unwrap();
        std::os::unix::fs::symlink(&canaries.root, &original_path).unwrap();

        drop(listener);
        drop(config);
        canaries.assert_intact();
        assert!(fs::symlink_metadata(retained.join("runtime.sock")).is_err());
        session.revoke();
        fs::remove_file(&original_path).unwrap();
        fs::remove_dir(&retained).unwrap();
        canaries.assert_intact();
    }

    fn spawn_init_child_at(session: &TransportSession, cwd: &Path) -> io::Result<Child> {
        let executable = env::current_exe().unwrap();
        let mut child = Command::new(executable)
            .arg("--ignored")
            .arg("--exact")
            .arg("runtime_manager::tests::runtime_helper_entry")
            .arg("--format=terse")
            .arg("--nocapture")
            .arg("--test-threads=1")
            .env_clear()
            .env("JARVIS_RUNTIME_HELPER_ID", session.instance_id_for_test())
            .env("JARVIS_RUNTIME_HELPER_MODE", "normal")
            .current_dir(cwd)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .spawn()?;
        let mut stdin = child.stdin.take().unwrap();
        session.write_child_init(&mut stdin).unwrap();
        drop(stdin);
        Ok(child)
    }

    fn reap_init_child(mut child: Child) -> (i32, String) {
        let deadline = Instant::now() + Duration::from_secs(2);
        let status = loop {
            if let Some(status) = child.try_wait().unwrap() {
                break status;
            }
            assert!(Instant::now() < deadline, "mismatched helper did not exit");
            thread::sleep(Duration::from_millis(5));
        };
        let mut output = String::new();
        child
            .stdout
            .take()
            .unwrap()
            .read_to_string(&mut output)
            .unwrap();
        (status.code().unwrap_or(-1), output)
    }

    fn spawn_init_child_with_current_session_path(session: &TransportSession) -> (i32, String) {
        let child = spawn_init_child_at(session, session.directory_path()).unwrap();
        reap_init_child(child)
    }

    #[test]
    fn replacement_before_child_bind_fails_closed_without_ready_or_canary_deletion() {
        let canaries = Canaries::create();
        let session = TransportSession::create("path-before-bind").unwrap();
        let original_path = session.directory_path().to_path_buf();
        let retained = canaries.root.join("pre-bind-original");
        fs::rename(&original_path, &retained).unwrap();
        std::os::unix::fs::symlink(&canaries.root, &original_path).unwrap();

        let (exit_code, output) = spawn_init_child_with_current_session_path(&session);
        assert_eq!(exit_code, 44);
        assert!(!output.contains("JARVIS_RUNTIME_READY"));
        session.revoke();
        canaries.assert_intact();
        fs::remove_file(&original_path).unwrap();
        fs::remove_dir(&retained).unwrap();
        canaries.assert_intact();
    }

    #[test]
    fn startup_path_replacement_types_fail_closed_before_bind() {
        #[derive(Clone, Copy)]
        enum Replacement {
            File,
            SymlinkToFile,
            SymlinkToDirectory,
            NewDirectory,
            FakeSocket,
        }

        let canaries = Canaries::create();
        for (index, replacement) in [
            Replacement::File,
            Replacement::SymlinkToFile,
            Replacement::SymlinkToDirectory,
            Replacement::NewDirectory,
            Replacement::FakeSocket,
        ]
        .into_iter()
        .enumerate()
        {
            let session = TransportSession::create(&format!("startup-matrix-{index}")).unwrap();
            let original_path = session.directory_path().to_path_buf();
            let retained = canaries.root.join(format!("startup-original-{index}"));
            fs::rename(&original_path, &retained).unwrap();
            let fake_socket = match replacement {
                Replacement::File => {
                    fs::write(&original_path, b"replacement-file").unwrap();
                    None
                }
                Replacement::SymlinkToFile => {
                    std::os::unix::fs::symlink(canaries.root.join("canary.txt"), &original_path)
                        .unwrap();
                    None
                }
                Replacement::SymlinkToDirectory => {
                    std::os::unix::fs::symlink(&canaries.root, &original_path).unwrap();
                    None
                }
                Replacement::NewDirectory => {
                    fs::create_dir(&original_path).unwrap();
                    None
                }
                Replacement::FakeSocket => Some(UnixListener::bind(&original_path).unwrap()),
            };

            match replacement {
                Replacement::File | Replacement::SymlinkToFile | Replacement::FakeSocket => {
                    assert!(spawn_init_child_at(&session, &original_path).is_err());
                }
                Replacement::SymlinkToDirectory | Replacement::NewDirectory => {
                    let child = spawn_init_child_at(&session, &original_path).unwrap();
                    let (exit_code, output) = reap_init_child(child);
                    assert_eq!(exit_code, 44, "replacement case {index}");
                    assert!(!output.contains("JARVIS_RUNTIME_READY"), "case {index}");
                }
            }
            drop(fake_socket);
            session.revoke();
            canaries.assert_intact();
            match replacement {
                Replacement::NewDirectory => fs::remove_dir(&original_path).unwrap(),
                _ => fs::remove_file(&original_path).unwrap(),
            }
            fs::remove_dir(&retained).unwrap();
        }
        canaries.assert_intact();
    }

    #[test]
    #[ignore = "MAC-002.1 adversarial filesystem stress; run explicitly"]
    fn stress_path_substitution_200_rounds() {
        let canaries = Canaries::create();
        for round in 0..200 {
            let session = TransportSession::create(&format!("path-stress-{round}")).unwrap();
            let original_path = session.directory_path().to_path_buf();
            let retained = canaries.root.join(format!("stress-original-{round}"));
            fs::rename(&original_path, &retained).unwrap();
            std::os::unix::fs::symlink(&canaries.root, &original_path).unwrap();
            session.revoke();
            canaries.assert_intact();
            fs::remove_file(&original_path).unwrap();
            fs::remove_dir(&retained).unwrap();
        }
        canaries.assert_intact();
    }

    #[test]
    #[ignore = "MAC-002.1 child startup/path substitution stress; run explicitly"]
    fn stress_child_startup_path_substitution_200_rounds() {
        let canaries = Canaries::create();
        for round in 0..200 {
            let session = TransportSession::create(&format!("child-path-stress-{round}")).unwrap();
            let original_path = session.directory_path().to_path_buf();
            let retained = canaries.root.join(format!("child-original-{round}"));
            fs::rename(&original_path, &retained).unwrap();
            std::os::unix::fs::symlink(&canaries.root, &original_path).unwrap();
            let (exit_code, output) = spawn_init_child_with_current_session_path(&session);
            assert_eq!(exit_code, 44, "round {round}");
            assert!(!output.contains("JARVIS_RUNTIME_READY"), "round {round}");
            session.revoke();
            canaries.assert_intact();
            fs::remove_file(&original_path).unwrap();
            fs::remove_dir(&retained).unwrap();
        }
        canaries.assert_intact();
    }
}
