use std::{
    env, fs, io,
    io::{BufRead, Read, Write},
    path::PathBuf,
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc, Mutex, MutexGuard,
    },
    time::{Duration, Instant},
};

#[cfg(unix)]
use std::os::unix::{
    ffi::OsStrExt,
    fs::PermissionsExt,
    net::{UnixListener, UnixStream},
};

const INIT_PREFIX: &[u8] = b"JARVIS_TRANSPORT_INIT ";
const PROTOCOL_VERSION: &str = "1";
const RUNTIME_KIND: &str = "jarvis-synthetic";
const BUILD_ID: &str = "g6-mac-002-synthetic-v1";
const HEALTH_ROUTE: &str = "/v1/health";
const VERSION_ROUTE: &str = "/v1/version";
const PROOF_ROUTE: &str = "/v1/instance-proof";
const CONNECT_TIMEOUT: Duration = Duration::from_millis(350);
const REQUEST_TIMEOUT: Duration = Duration::from_millis(900);
const SERVER_REQUEST_TIMEOUT: Duration = Duration::from_millis(500);
const MAX_REQUEST_HEADER_BYTES: usize = 1024;
const MAX_REQUEST_BODY_BYTES: usize = 128;
const MAX_RESPONSE_HEADER_BYTES: usize = 2048;
const MAX_RESPONSE_BODY_BYTES: usize = 2048;
const MAX_INIT_BYTES: usize = 1024;
const SECRET_BYTES: usize = 32;
const NONCE_BYTES: usize = 32;

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
    HttpRejected,
    ProofRejected,
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
            Self::HttpRejected => "http_rejected",
            Self::ProofRejected => "proof_rejected",
            Self::IncompatibleVersion => "incompatible_version",
            Self::OsCryptoUnavailable => "os_crypto_unavailable",
            Self::SetupFailed => "transport_setup_failed",
        }
    }

    pub(crate) fn incompatible(self) -> bool {
        self == Self::IncompatibleVersion
    }
}

/// Native-only transport capability. The endpoint and key are never serialized to Tauri IPC.
pub(crate) struct TransportSession {
    instance_id: String,
    socket_path: PathBuf,
    directory: PathBuf,
    secret: Mutex<Option<[u8; SECRET_BYTES]>>,
    active: AtomicBool,
    request_lock: Mutex<()>,
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
            let _ = fs::remove_dir(&directory);
            return Err(TransportError::SetupFailed);
        }
        let socket_path = directory.join("runtime.sock");
        if socket_path.as_os_str().as_bytes().len() >= 104 {
            secret.fill(0);
            let _ = fs::remove_dir(&directory);
            return Err(TransportError::SetupFailed);
        }

        Ok(Arc::new(Self {
            instance_id: instance_id.to_owned(),
            socket_path,
            directory,
            secret: Mutex::new(Some(secret)),
            active: AtomicBool::new(true),
            request_lock: Mutex::new(()),
        }))
    }

    pub(crate) fn write_child_init(&self, writer: &mut impl Write) -> Result<(), TransportError> {
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
            .and_then(|_| write_hex(writer, self.socket_path.as_os_str().as_bytes()))
            .and_then(|_| writer.write_all(b"\n"))
            .and_then(|_| writer.flush())
            .map_err(|_| TransportError::SetupFailed)
    }

    pub(crate) fn probe(&self) -> Result<(), TransportError> {
        self.probe_endpoint(&self.socket_path)
    }

    fn probe_endpoint(&self, endpoint: &std::path::Path) -> Result<(), TransportError> {
        let _serial = lock(&self.request_lock);
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

    #[cfg(test)]
    pub(crate) fn probe_other_session_for_test(
        &self,
        other: &TransportSession,
    ) -> Result<(), TransportError> {
        self.probe_endpoint(&other.socket_path)
    }

    #[cfg(test)]
    pub(crate) fn is_clean_for_test(&self) -> bool {
        !self.active.load(Ordering::Acquire)
            && lock(&self.secret).is_none()
            && !self.directory.exists()
            && !self.socket_path.exists()
    }

    #[cfg(test)]
    pub(crate) fn instance_id_for_test(&self) -> &str {
        &self.instance_id
    }

    pub(crate) fn revoke(&self) {
        self.deactivate();
        self.cleanup_endpoint();
    }

    pub(crate) fn deactivate(&self) {
        self.active.store(false, Ordering::Release);
        if let Some(mut secret) = lock(&self.secret).take() {
            secret.fill(0);
            std::hint::black_box(secret);
        }
    }

    fn cleanup_endpoint(&self) {
        let _ = fs::remove_file(&self.socket_path);
        let _ = fs::remove_dir(&self.directory);
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
        self.ensure_active()?;
        let mut stream = connect_bounded(endpoint, CONNECT_TIMEOUT)?;
        let request_deadline = Instant::now() + REQUEST_TIMEOUT;
        stream
            .set_read_timeout(Some(REQUEST_TIMEOUT))
            .and_then(|_| stream.set_write_timeout(Some(REQUEST_TIMEOUT)))
            .map_err(|_| TransportError::EndpointUnavailable)?;

        let method = match verb {
            Verb::Get => "GET",
            Verb::Post => "POST",
        };
        let request = format!(
            "{method} {route} HTTP/1.1\r\nHost: jarvis.local\r\nConnection: close\r\nContent-Length: {}\r\nContent-Type: text/plain\r\n\r\n",
            body.len()
        );
        stream
            .write_all(request.as_bytes())
            .and_then(|_| stream.write_all(body))
            .and_then(|_| stream.flush())
            .map_err(map_io_error)?;
        read_http_response(&mut stream, request_deadline)
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
}

impl Drop for TransportSession {
    fn drop(&mut self) {
        self.revoke();
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
        "jarvis-local-transport-proof-v1\n{}\n{}\n{}\n{}\n{}\n{}",
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

fn decode_hex(value: &[u8]) -> Option<Vec<u8>> {
    if value.len() % 2 != 0 {
        return None;
    }
    value
        .chunks_exact(2)
        .map(|pair| Some((hex_nibble(pair[0])? << 4) | hex_nibble(pair[1])?))
        .collect()
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

fn read_http_response(
    stream: &mut UnixStream,
    deadline: Instant,
) -> Result<Vec<u8>, TransportError> {
    let mut wire = Vec::new();
    let mut buffer = [0_u8; 512];
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
        wire.extend_from_slice(&buffer[..count]);
        if wire.len() > MAX_RESPONSE_HEADER_BYTES + MAX_RESPONSE_BODY_BYTES {
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
        } else if name.eq_ignore_ascii_case("transfer-encoding") {
            return Err(TransportError::MalformedResponse);
        }
    }
    let content_length = content_length.ok_or(TransportError::MalformedResponse)?;
    if content_length > MAX_RESPONSE_BODY_BYTES {
        return Err(TransportError::ResponseTooLarge);
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
        stream
            .set_read_timeout(Some(remaining))
            .map_err(|_| TransportError::EndpointUnavailable)?;
        let count = stream.read(output).map_err(map_io_error)?;
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
    use std::os::unix::ffi::OsStringExt;

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
        let path_hex = fields.next().ok_or(TransportError::SetupFailed)?;
        if fields.next().is_some() || instance_id != expected_instance_id.as_bytes() {
            return Err(TransportError::SetupFailed);
        }
        let mut secret =
            decode_hex_array::<SECRET_BYTES>(secret_hex).ok_or(TransportError::SetupFailed)?;
        let path = match decode_hex(path_hex) {
            Some(path) => path,
            None => {
                secret.fill(0);
                return Err(TransportError::SetupFailed);
            }
        };
        if path.is_empty() || path.contains(&0) || path.len() >= 104 {
            secret.fill(0);
            return Err(TransportError::SetupFailed);
        }
        Ok((secret, path))
    })();
    record.fill(0);
    let (secret, path) = parsed?;
    Ok(ChildTransportConfig {
        instance_id: expected_instance_id.to_owned(),
        secret,
        socket_path: PathBuf::from(std::ffi::OsString::from_vec(path)),
    })
}

pub(crate) struct ChildTransportConfig {
    instance_id: String,
    secret: [u8; SECRET_BYTES],
    socket_path: PathBuf,
}

impl Drop for ChildTransportConfig {
    fn drop(&mut self) {
        self.secret.fill(0);
        std::hint::black_box(self.secret);
        let _ = fs::remove_file(&self.socket_path);
    }
}

impl ChildTransportConfig {
    pub(crate) fn bind(&self) -> Result<UnixListener, TransportError> {
        let listener =
            UnixListener::bind(&self.socket_path).map_err(|_| TransportError::SetupFailed)?;
        fs::set_permissions(&self.socket_path, fs::Permissions::from_mode(0o600))
            .map_err(|_| TransportError::SetupFailed)?;
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

    pub(crate) fn serve_one(
        &self,
        listener: &UnixListener,
        wait: Duration,
    ) -> Result<bool, TransportError> {
        let deadline = Instant::now() + wait;
        loop {
            match listener.accept() {
                Ok((mut stream, _)) => {
                    stream
                        .set_read_timeout(Some(SERVER_REQUEST_TIMEOUT))
                        .and_then(|_| stream.set_write_timeout(Some(SERVER_REQUEST_TIMEOUT)))
                        .map_err(|_| TransportError::EndpointUnavailable)?;
                    let response = self.handle_request(&mut stream);
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

    fn fake_listener(session: &TransportSession) -> UnixListener {
        let listener = UnixListener::bind(&session.socket_path).unwrap();
        fs::set_permissions(&session.socket_path, fs::Permissions::from_mode(0o600)).unwrap();
        listener
    }

    fn fake_server(session: &TransportSession, replies: Vec<FakeReply>) -> JoinHandle<()> {
        let listener = fake_listener(session);
        let socket_path = session.socket_path.clone();
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
            let _ = fs::remove_file(socket_path);
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
            "HTTP/1.1 {status}\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
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
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn()
            .unwrap();
        let fake = FakeProcess(child);
        let deadline = Instant::now() + Duration::from_secs(2);
        while !session.socket_path.exists() && Instant::now() < deadline {
            thread::sleep(Duration::from_millis(5));
        }
        assert!(
            session.socket_path.exists(),
            "fake runtime did not bind its UDS"
        );
        fake
    }

    fn helper_http_response(
        session: &TransportSession,
        host: &str,
        extra_headers: &str,
    ) -> Vec<u8> {
        use std::io::Cursor;

        let mut init = Vec::new();
        session.write_child_init(&mut init).unwrap();
        let config = read_child_init(
            &mut io::BufReader::new(Cursor::new(init)),
            &session.instance_id,
        )
        .unwrap();
        let listener = config.bind().unwrap();
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
                FakeReply::Body(version_body("version-instance", "99")),
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
        session.revoke();
        assert!(!session.directory.exists());
        assert_eq!(session.probe(), Err(TransportError::Inactive));
    }
}
