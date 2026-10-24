//! Keychain-backed 256-bit key for the encrypted synthetic SQLite snapshot.
//!
//! The key is returned only to the caller so it can be sent through the
//! authenticated local runtime channel. It is never serialized to disk by this
//! module or included in diagnostics.

use std::io::Read;

const KEY_LEN: usize = 32;
const SERVICE: &str = "com.jarvis.victor-os.synthetic-database.v1";
const ACCOUNT: &str = "primary";

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum KeychainError {
    Unavailable,
    InvalidItem,
    MissingItem,
    DuplicateItem,
}

trait KeychainBackend {
    fn load(&self) -> Result<Option<[u8; KEY_LEN]>, KeychainError>;
    fn store(&self, key: &[u8; KEY_LEN]) -> Result<(), KeychainError>;
}

fn load_or_create_with(
    backend: &impl KeychainBackend,
    mut random_key: impl FnMut() -> Result<[u8; KEY_LEN], KeychainError>,
) -> Result<[u8; KEY_LEN], KeychainError> {
    if let Some(key) = backend.load()? {
        return Ok(key);
    }
    let mut key = random_key()?;
    match backend.store(&key) {
        Ok(()) => Ok(key),
        Err(KeychainError::DuplicateItem) => {
            key.fill(0);
            backend.load()?.ok_or(KeychainError::Unavailable)
        }
        Err(error) => {
            key.fill(0);
            Err(error)
        }
    }
}

fn load_existing_with(backend: &impl KeychainBackend) -> Result<[u8; KEY_LEN], KeychainError> {
    backend.load()?.ok_or(KeychainError::MissingItem)
}

pub(crate) fn load_or_create_key() -> Result<[u8; KEY_LEN], KeychainError> {
    let backend = PlatformKeychain;
    load_or_create_with(&backend, random_key)
}

pub(crate) fn load_existing_key() -> Result<[u8; KEY_LEN], KeychainError> {
    load_existing_with(&PlatformKeychain)
}

fn pending_account(generation: &str) -> Result<String, KeychainError> {
    if generation.len() != 16 || !generation.bytes().all(|byte| byte.is_ascii_hexdigit()) {
        return Err(KeychainError::InvalidItem);
    }
    Ok(format!("pending-{generation}"))
}

pub(crate) fn insert_pending_key(
    generation: &str,
    key: &[u8; KEY_LEN],
) -> Result<(), KeychainError> {
    macos_insert(&pending_account(generation)?, key)
}

pub(crate) fn load_pending_key(generation: &str) -> Result<Option<[u8; KEY_LEN]>, KeychainError> {
    macos_load(&pending_account(generation)?)
}

pub(crate) fn delete_pending_key(generation: &str) -> Result<(), KeychainError> {
    macos_delete(&pending_account(generation)?)
}

#[cfg(target_os = "macos")]
fn macos_load(account: &str) -> Result<Option<[u8; KEY_LEN]>, KeychainError> {
    macos::load_account(account)
}

#[cfg(target_os = "macos")]
fn macos_insert(account: &str, key: &[u8; KEY_LEN]) -> Result<(), KeychainError> {
    macos::store_account(account, key)
}

#[cfg(target_os = "macos")]
fn macos_delete(account: &str) -> Result<(), KeychainError> {
    macos::delete_account(account)
}

#[cfg(not(target_os = "macos"))]
fn macos_load(_account: &str) -> Result<Option<[u8; KEY_LEN]>, KeychainError> {
    Err(KeychainError::Unavailable)
}

#[cfg(not(target_os = "macos"))]
fn macos_insert(_account: &str, _key: &[u8; KEY_LEN]) -> Result<(), KeychainError> {
    Err(KeychainError::Unavailable)
}

#[cfg(not(target_os = "macos"))]
fn macos_delete(_account: &str) -> Result<(), KeychainError> {
    Err(KeychainError::Unavailable)
}

pub(crate) fn random_storage_key() -> Result<[u8; KEY_LEN], KeychainError> {
    random_key()
}

fn random_key() -> Result<[u8; KEY_LEN], KeychainError> {
    let mut key = [0_u8; KEY_LEN];
    if std::fs::File::open("/dev/urandom")
        .and_then(|mut random| random.read_exact(&mut key))
        .is_err()
    {
        key.fill(0);
        return Err(KeychainError::Unavailable);
    }
    Ok(key)
}

struct PlatformKeychain;

pub(crate) const LEGACY_ACCOUNT: &str = "primary";

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct RotationJournal {
    pub(crate) phase: String,
    pub(crate) from_account: String,
    pub(crate) to_account: String,
    pub(crate) primary_digest: String,
    pub(crate) staged_digest: String,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) enum UnlockAccount {
    Legacy,
    Generation(String),
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum SelectionError {
    Ambiguous,
    Unavailable,
}

trait GenerationBackend {
    fn load_generation(&self, account: &str) -> Result<Option<[u8; KEY_LEN]>, KeychainError>;
    fn store_new_generation(&self, account: &str, key: &[u8; KEY_LEN])
        -> Result<(), KeychainError>;
    fn delete_generation(&self, account: &str) -> Result<(), KeychainError>;
}

pub(crate) fn select_unlock_account(
    journal: Option<&RotationJournal>,
    digest: Option<&str>,
) -> Result<UnlockAccount, SelectionError> {
    let Some(journal) = journal else {
        return Ok(UnlockAccount::Legacy);
    };
    let Some(digest) = digest else {
        return Err(SelectionError::Ambiguous);
    };
    if !journal.staged_digest.is_empty() && journal.staged_digest == journal.primary_digest {
        return if digest == journal.primary_digest {
            Ok(account_choice(&journal.from_account))
        } else {
            Err(SelectionError::Ambiguous)
        };
    }
    if digest == journal.primary_digest {
        return Ok(account_choice(&journal.from_account));
    }
    if !journal.staged_digest.is_empty() && digest == journal.staged_digest {
        return Ok(account_choice(&journal.to_account));
    }
    Err(SelectionError::Ambiguous)
}

fn account_choice(account: &str) -> UnlockAccount {
    if account == LEGACY_ACCOUNT {
        UnlockAccount::Legacy
    } else {
        UnlockAccount::Generation(account.to_owned())
    }
}

/// An intent journal has no new ciphertext yet. Creating the missing item
/// continues that generation; it does not replace a key that already exists.
pub(crate) fn missing_intent_key_may_be_created(journal: &RotationJournal, digest: &str) -> bool {
    journal.phase == "intent"
        && journal.staged_digest.is_empty()
        && digest == journal.primary_digest
        && journal.from_account != journal.to_account
}

/// Old account deletion is allowed only after the new ciphertext is the primary.
pub(crate) fn retirement_account(journal: &RotationJournal, digest: &str) -> Option<String> {
    if journal.phase != "validated" && journal.phase != "committed" {
        return None;
    }
    if journal.staged_digest.is_empty()
        || digest != journal.staged_digest
        || journal.from_account == journal.to_account
    {
        return None;
    }
    Some(journal.from_account.clone())
}

pub(crate) fn install_new_generation(
    backend: &impl GenerationBackend,
    generation: &str,
    key: &[u8; KEY_LEN],
) -> Result<(), KeychainError> {
    if !valid_generation(generation) {
        return Err(KeychainError::InvalidItem);
    }
    match backend.load_generation(generation)? {
        Some(mut existing) => {
            let same = existing == *key;
            existing.fill(0);
            if same {
                Ok(())
            } else {
                Err(KeychainError::DuplicateItem)
            }
        }
        None => backend.store_new_generation(generation, key),
    }
}

pub(crate) fn load_generation_key(account: &str) -> Result<Option<[u8; KEY_LEN]>, KeychainError> {
    PlatformKeychain.load_generation(account)
}

pub(crate) fn install_platform_generation(
    generation: &str,
    key: &[u8; KEY_LEN],
) -> Result<(), KeychainError> {
    install_new_generation(&PlatformKeychain, generation, key)
}

pub(crate) fn retire_platform_account(
    journal: &RotationJournal,
    digest: &str,
    requested: &str,
) -> Result<(), KeychainError> {
    retire_matching_account(&PlatformKeychain, journal, digest, requested)
}

pub(crate) fn retire_matching_account(
    backend: &impl GenerationBackend,
    journal: &RotationJournal,
    digest: &str,
    requested: &str,
) -> Result<(), KeychainError> {
    match retirement_account(journal, digest) {
        Some(account) if account == requested && account != journal.to_account => {
            backend.delete_generation(&account)
        }
        _ => Err(KeychainError::InvalidItem),
    }
}

const JOURNAL_MAGIC: &[u8] = b"JVRJT\x00\x01\x00";

pub(crate) fn rotation_journal_exists(database: &std::path::Path) -> Result<bool, SelectionError> {
    let path = rotation_journal_file(database)?;
    match std::fs::symlink_metadata(&path) {
        Ok(info) if info.file_type().is_symlink() || !info.is_file() => {
            Err(SelectionError::Ambiguous)
        }
        Ok(_) => Ok(true),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(false),
        Err(_) => Err(SelectionError::Unavailable),
    }
}

pub(crate) fn authenticated_rotation_marker(
    database: &std::path::Path,
) -> Result<(), SelectionError> {
    let path = rotation_journal_file(database)?;
    let info = match std::fs::symlink_metadata(&path) {
        Ok(info) => info,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(()),
        Err(_) => return Err(SelectionError::Unavailable),
    };
    if info.file_type().is_symlink() || !info.file_type().is_file() || info.len() > 8192 {
        return Err(SelectionError::Ambiguous);
    }
    let raw = std::fs::read(&path).map_err(|_| SelectionError::Unavailable)?;
    if raw.starts_with(JOURNAL_MAGIC) {
        Ok(())
    } else {
        Err(SelectionError::Ambiguous)
    }
}

/// Some when a published generation, or the generation marker, names the key.
/// Before the first publication, the legacy item still opens the primary.
/// A journal without a recovery file and without a marker is ambiguous:
/// this function does not create a substitute key.
pub(crate) fn published_generation_account(
    database: &std::path::Path,
) -> Result<Option<String>, SelectionError> {
    let journal = rotation_journal_file(database)?;
    match std::fs::symlink_metadata(&journal) {
        Ok(info) if info.file_type().is_symlink() || !info.is_file() => {
            return Err(SelectionError::Ambiguous);
        }
        Ok(_) => {}
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(None),
        Err(_) => return Err(SelectionError::Unavailable),
    }
    authenticated_rotation_marker(database)?;
    if let Some(recovery) = recovery_ciphertext(database)? {
        let recovery_digest = ciphertext_digest(&recovery)?;
        let primary_digest = ciphertext_digest(database)?;
        if primary_digest != recovery_digest {
            return Ok(Some(generation_from_digest(&recovery_digest)?));
        }
        return marker_account(database);
    }
    match marker_account(database)? {
        Some(account) => Ok(Some(account)),
        None => Err(SelectionError::Ambiguous),
    }
}

fn marker_account(database: &std::path::Path) -> Result<Option<String>, SelectionError> {
    Ok(read_generation_marker(database)?.map(|(account, _operation)| account))
}

pub(crate) fn read_generation_marker(
    database: &std::path::Path,
) -> Result<Option<(String, String)>, SelectionError> {
    let path = generation_marker_file(database)?;
    let info = match std::fs::symlink_metadata(&path) {
        Ok(info) => info,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(None),
        Err(_) => return Err(SelectionError::Unavailable),
    };
    if info.file_type().is_symlink() || !info.is_file() || info.len() > 128 {
        return Err(SelectionError::Ambiguous);
    }
    let raw = std::fs::read(&path).map_err(|_| SelectionError::Unavailable)?;
    let text = std::str::from_utf8(&raw).map_err(|_| SelectionError::Ambiguous)?;
    let mut lines = text.split('\n');
    let account = lines.next().ok_or(SelectionError::Ambiguous)?;
    let operation_id = lines.next().ok_or(SelectionError::Ambiguous)?;
    if lines.next() != Some("")
        || !valid_generation(account)
        || operation_id != operation_id_for(account)
    {
        return Err(SelectionError::Ambiguous);
    }
    Ok(Some((account.to_owned(), operation_id.to_owned())))
}

pub(crate) fn operation_id_for(generation: &str) -> String {
    use sha2::{Digest, Sha256};
    format!("{:x}", Sha256::digest(generation.as_bytes()))
}

fn generation_marker_file(
    database: &std::path::Path,
) -> Result<std::path::PathBuf, SelectionError> {
    let name = database.file_name().ok_or(SelectionError::Ambiguous)?;
    let mut marker = std::ffi::OsString::from(".");
    marker.push(name);
    marker.push(".key-generation");
    Ok(database
        .parent()
        .ok_or(SelectionError::Ambiguous)?
        .join(marker))
}

fn recovery_ciphertext(
    database: &std::path::Path,
) -> Result<Option<std::path::PathBuf>, SelectionError> {
    let parent = database.parent().ok_or(SelectionError::Ambiguous)?;
    let file_name = database
        .file_name()
        .and_then(|value| value.to_str())
        .ok_or(SelectionError::Ambiguous)?;
    let prefix = format!(".{file_name}.rotation-");
    let mut recovery: Option<std::path::PathBuf> = None;
    for entry in std::fs::read_dir(parent).map_err(|_| SelectionError::Unavailable)? {
        let entry = entry.map_err(|_| SelectionError::Unavailable)?;
        let text = entry.file_name().to_string_lossy().into_owned();
        if text.starts_with(&prefix) && text.ends_with(".sealed") {
            if recovery.is_some() {
                return Err(SelectionError::Ambiguous);
            }
            let info = entry.metadata().map_err(|_| SelectionError::Unavailable)?;
            if !info.is_file() || info.file_type().is_symlink() {
                return Err(SelectionError::Ambiguous);
            }
            recovery = Some(entry.path());
        }
    }
    Ok(recovery)
}

pub(crate) fn recovery_still_present(database: &std::path::Path) -> Result<bool, SelectionError> {
    Ok(recovery_ciphertext(database)?.is_some())
}

/// Name for an explicit new rotation. A recovery file means cleanup is pending.
pub(crate) fn rotation_generation_name(
    database: &std::path::Path,
) -> Result<String, SelectionError> {
    if recovery_ciphertext(database)?.is_some() {
        return Err(SelectionError::Ambiguous);
    }
    generation_from_digest(&ciphertext_digest(database)?)
}

pub(crate) fn in_progress_generation_name(
    database: &std::path::Path,
) -> Result<String, SelectionError> {
    let parent = database.parent().ok_or(SelectionError::Ambiguous)?;
    let file_name = database
        .file_name()
        .and_then(|value| value.to_str())
        .ok_or(SelectionError::Ambiguous)?;
    let prefix = format!(".{file_name}.rotation-");
    let mut recovery: Option<std::path::PathBuf> = None;
    for entry in std::fs::read_dir(parent).map_err(|_| SelectionError::Unavailable)? {
        let entry = entry.map_err(|_| SelectionError::Unavailable)?;
        let name = entry.file_name();
        let text = name.to_string_lossy();
        if text.starts_with(&prefix) && text.ends_with(".sealed") {
            if recovery.is_some() {
                return Err(SelectionError::Ambiguous);
            }
            let info = entry.metadata().map_err(|_| SelectionError::Unavailable)?;
            if !info.is_file() || info.file_type().is_symlink() {
                return Err(SelectionError::Ambiguous);
            }
            recovery = Some(entry.path());
        }
    }
    let Some(path) = recovery else {
        return Err(SelectionError::Ambiguous);
    };
    generation_from_digest(&ciphertext_digest(&path)?)
}

pub(crate) fn retire_other_account(account: &str, keep: &str) -> Result<(), KeychainError> {
    if !valid_account(account) || !valid_generation(keep) || account == keep {
        return Err(KeychainError::InvalidItem);
    }
    #[cfg(target_os = "macos")]
    {
        macos::delete_account(account)
    }
    #[cfg(not(target_os = "macos"))]
    {
        let _ = (account, keep);
        Err(KeychainError::Unavailable)
    }
}

fn generation_from_digest(digest: &str) -> Result<String, SelectionError> {
    if !valid_digest(digest) {
        return Err(SelectionError::Ambiguous);
    }
    Ok(format!("gen-v1-{}", &digest[..32]))
}

fn rotation_journal_file(database: &std::path::Path) -> Result<std::path::PathBuf, SelectionError> {
    let name = database.file_name().ok_or(SelectionError::Ambiguous)?;
    let mut journal_name = std::ffi::OsString::from(".");
    journal_name.push(name);
    journal_name.push(".key-rotation.json");
    Ok(database
        .parent()
        .ok_or(SelectionError::Ambiguous)?
        .join(journal_name))
}

pub(crate) fn read_rotation_journal(
    database: &std::path::Path,
) -> Result<Option<RotationJournal>, SelectionError> {
    // Disk bytes are not a Keychain decision. A sealed marker is ignored here;
    // plaintext is rejected. Account selection uses the ciphertext digest.
    authenticated_rotation_marker(database)?;
    Ok(None)
}

pub(crate) fn ciphertext_digest(path: &std::path::Path) -> Result<String, SelectionError> {
    use sha2::{Digest, Sha256};
    use std::io::Read;
    let info = std::fs::symlink_metadata(path).map_err(|_| SelectionError::Unavailable)?;
    if !info.file_type().is_file() || info.len() > 256 * 1024 * 1024 + 64 {
        return Err(SelectionError::Ambiguous);
    }
    let mut file = std::fs::File::open(path).map_err(|_| SelectionError::Unavailable)?;
    let mut hasher = Sha256::new();
    let mut buffer = [0_u8; 8192];
    let mut total = 0_u64;
    loop {
        let count = file
            .read(&mut buffer)
            .map_err(|_| SelectionError::Unavailable)?;
        if count == 0 {
            break;
        }
        total += count as u64;
        if total > 256 * 1024 * 1024 + 64 {
            return Err(SelectionError::Ambiguous);
        }
        hasher.update(&buffer[..count]);
    }
    Ok(format!("{:x}", hasher.finalize()))
}

fn parse_rotation_journal(raw: &[u8]) -> Result<Option<RotationJournal>, SelectionError> {
    let value: serde_json::Value =
        serde_json::from_slice(raw).map_err(|_| SelectionError::Ambiguous)?;
    let object = value.as_object().ok_or(SelectionError::Ambiguous)?;
    const KEYS: [&str; 9] = [
        "from_account",
        "phase",
        "primary_digest",
        "recovery_name",
        "schema",
        "staged_digest",
        "staged_name",
        "to_account",
        "version",
    ];
    if object.len() != KEYS.len() || KEYS.iter().any(|key| !object.contains_key(*key)) {
        return Err(SelectionError::Ambiguous);
    }
    if object.get("version").and_then(|value| value.as_u64()) != Some(1) {
        return Err(SelectionError::Ambiguous);
    }
    let phase = object_string(object, "phase")?;
    if !matches!(
        phase.as_str(),
        "intent" | "key_stored" | "staged" | "linked" | "published" | "validated" | "committed"
    ) {
        return Err(SelectionError::Ambiguous);
    }
    let from_account = object_string(object, "from_account")?;
    let to_account = object_string(object, "to_account")?;
    if !valid_account(&from_account) || !valid_generation(&to_account) || from_account == to_account
    {
        return Err(SelectionError::Ambiguous);
    }
    let primary_digest = object_string(object, "primary_digest")?;
    let staged_digest = object_string(object, "staged_digest")?;
    if !valid_digest(&primary_digest)
        || (!staged_digest.is_empty() && !valid_digest(&staged_digest))
    {
        return Err(SelectionError::Ambiguous);
    }
    Ok(Some(RotationJournal {
        phase,
        from_account,
        to_account,
        primary_digest,
        staged_digest,
    }))
}

fn object_string(
    object: &serde_json::Map<String, serde_json::Value>,
    key: &str,
) -> Result<String, SelectionError> {
    object
        .get(key)
        .and_then(|value| value.as_str())
        .map(str::to_owned)
        .ok_or(SelectionError::Ambiguous)
}

fn valid_account(value: &str) -> bool {
    value == LEGACY_ACCOUNT || valid_generation(value)
}

fn valid_generation(value: &str) -> bool {
    let Some(rest) = value.strip_prefix("gen-v1-") else {
        return false;
    };
    rest.len() == 32
        && rest
            .bytes()
            .all(|byte| matches!(byte, b'0'..=b'9' | b'a'..=b'f'))
}

fn valid_digest(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|byte| matches!(byte, b'0'..=b'9' | b'a'..=b'f'))
}

impl GenerationBackend for PlatformKeychain {
    fn load_generation(&self, account: &str) -> Result<Option<[u8; KEY_LEN]>, KeychainError> {
        if !valid_account(account) {
            return Err(KeychainError::InvalidItem);
        }
        #[cfg(target_os = "macos")]
        {
            macos::load_account(account)
        }
        #[cfg(not(target_os = "macos"))]
        {
            let _ = account;
            Err(KeychainError::Unavailable)
        }
    }

    fn store_new_generation(
        &self,
        account: &str,
        key: &[u8; KEY_LEN],
    ) -> Result<(), KeychainError> {
        if !valid_generation(account) {
            return Err(KeychainError::InvalidItem);
        }
        #[cfg(target_os = "macos")]
        {
            macos::store_account(account, key)
        }
        #[cfg(not(target_os = "macos"))]
        {
            let _ = (account, key);
            Err(KeychainError::Unavailable)
        }
    }

    fn delete_generation(&self, account: &str) -> Result<(), KeychainError> {
        if !valid_account(account) {
            return Err(KeychainError::InvalidItem);
        }
        #[cfg(target_os = "macos")]
        {
            macos::delete_account(account)
        }
        #[cfg(not(target_os = "macos"))]
        {
            let _ = account;
            Err(KeychainError::Unavailable)
        }
    }
}

#[cfg(target_os = "macos")]
impl KeychainBackend for PlatformKeychain {
    fn load(&self) -> Result<Option<[u8; KEY_LEN]>, KeychainError> {
        macos::load()
    }

    fn store(&self, key: &[u8; KEY_LEN]) -> Result<(), KeychainError> {
        macos::store(key)
    }
}

#[cfg(not(target_os = "macos"))]
impl KeychainBackend for PlatformKeychain {
    fn load(&self) -> Result<Option<[u8; KEY_LEN]>, KeychainError> {
        Err(KeychainError::Unavailable)
    }

    fn store(&self, _key: &[u8; KEY_LEN]) -> Result<(), KeychainError> {
        Err(KeychainError::Unavailable)
    }
}

#[cfg(target_os = "macos")]
mod macos {
    use super::{KeychainError, KEY_LEN};
    use std::{ffi::c_void, ptr};

    type CFTypeRef = *const c_void;
    type CFStringRef = *const c_void;
    type CFDataRef = *const c_void;
    type CFDictionaryRef = *const c_void;
    type CFIndex = isize;
    type CFBooleanRef = *const c_void;

    const UTF8: u32 = 0x0800_0100;
    const ERR_ITEM_NOT_FOUND: i32 = -25300;
    const ERR_DUPLICATE_ITEM: i32 = -25299;

    #[link(name = "Security", kind = "framework")]
    unsafe extern "C" {
        static kSecClass: CFStringRef;
        static kSecClassGenericPassword: CFStringRef;
        static kSecAttrService: CFStringRef;
        static kSecAttrAccount: CFStringRef;
        static kSecAttrAccessible: CFStringRef;
        static kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly: CFStringRef;
        static kSecValueData: CFStringRef;
        static kSecReturnData: CFStringRef;
        static kSecMatchLimit: CFStringRef;
        static kSecMatchLimitOne: CFStringRef;
        fn SecItemCopyMatching(query: CFDictionaryRef, result: *mut CFTypeRef) -> i32;
        fn SecItemAdd(attributes: CFDictionaryRef, result: *mut CFTypeRef) -> i32;
        fn SecItemDelete(query: CFDictionaryRef) -> i32;
    }

    #[link(name = "CoreFoundation", kind = "framework")]
    unsafe extern "C" {
        static kCFBooleanTrue: CFBooleanRef;
        fn CFStringCreateWithCString(
            allocator: CFTypeRef,
            value: *const i8,
            encoding: u32,
        ) -> CFStringRef;
        fn CFDataCreate(allocator: CFTypeRef, bytes: *const u8, length: CFIndex) -> CFDataRef;
        fn CFDataGetLength(data: CFDataRef) -> CFIndex;
        fn CFDataGetBytePtr(data: CFDataRef) -> *const u8;
        fn CFDictionaryCreate(
            allocator: CFTypeRef,
            keys: *const CFTypeRef,
            values: *const CFTypeRef,
            count: CFIndex,
            key_callbacks: *const c_void,
            value_callbacks: *const c_void,
        ) -> CFDictionaryRef;
        fn CFRelease(value: CFTypeRef);
    }

    struct Owned(Vec<CFTypeRef>);
    impl Drop for Owned {
        fn drop(&mut self) {
            unsafe {
                for value in self.0.drain(..) {
                    if !value.is_null() {
                        CFRelease(value);
                    }
                }
            }
        }
    }

    fn string(value: &str) -> Result<CFStringRef, KeychainError> {
        let bytes = value.as_bytes();
        if bytes.contains(&0) {
            return Err(KeychainError::InvalidItem);
        }
        let mut nul_terminated = Vec::with_capacity(bytes.len() + 1);
        nul_terminated.extend_from_slice(bytes);
        nul_terminated.push(0);
        let value =
            unsafe { CFStringCreateWithCString(ptr::null(), nul_terminated.as_ptr().cast(), UTF8) };
        if value.is_null() {
            return Err(KeychainError::Unavailable);
        }
        Ok(value)
    }

    unsafe fn dictionary(
        entries: &[(CFTypeRef, CFTypeRef)],
    ) -> Result<CFDictionaryRef, KeychainError> {
        let keys: Vec<_> = entries.iter().map(|(key, _)| *key).collect();
        let values: Vec<_> = entries.iter().map(|(_, value)| *value).collect();
        let value = CFDictionaryCreate(
            ptr::null(),
            keys.as_ptr(),
            values.as_ptr(),
            entries.len() as CFIndex,
            ptr::null(),
            ptr::null(),
        );
        if value.is_null() {
            return Err(KeychainError::Unavailable);
        }
        Ok(value)
    }

    pub(super) fn load() -> Result<Option<[u8; KEY_LEN]>, KeychainError> {
        let mut result = ptr::null();
        let response = unsafe {
            #[cfg(not(test))]
            let (service_name, account_name) =
                (super::SERVICE.to_owned(), super::ACCOUNT.to_owned());
            #[cfg(test)]
            let (service_name, account_name) = native_test::identity();
            let service = string(&service_name)?;
            let account = string(&account_name)?;
            let extras = Owned(vec![service, account]);
            #[allow(unused_mut)]
            let mut entries = vec![
                (kSecClass, kSecClassGenericPassword),
                (kSecAttrService, service),
                (kSecAttrAccount, account),
                (kSecReturnData, kCFBooleanTrue),
                (kSecMatchLimit, kSecMatchLimitOne),
            ];
            #[cfg(test)]
            let _scope = native_test::restrict_search(&mut entries)?;
            let query = dictionary(&entries)?;
            let status = SecItemCopyMatching(query, &mut result);
            #[cfg(test)]
            eprintln!("native_keychain operation=restricted_load status={status}");
            CFRelease(query);
            drop(extras);
            if status == ERR_ITEM_NOT_FOUND {
                Ok(None)
            } else if status != 0 || result.is_null() {
                Err(KeychainError::Unavailable)
            } else {
                let data = result as CFDataRef;
                if CFDataGetLength(data) != KEY_LEN as CFIndex {
                    CFRelease(result);
                    Err(KeychainError::InvalidItem)
                } else {
                    let pointer = CFDataGetBytePtr(data);
                    if pointer.is_null() {
                        CFRelease(result);
                        Err(KeychainError::InvalidItem)
                    } else {
                        let mut key = [0_u8; KEY_LEN];
                        ptr::copy_nonoverlapping(pointer, key.as_mut_ptr(), KEY_LEN);
                        CFRelease(result);
                        Ok(Some(key))
                    }
                }
            }
        };
        response
    }

    pub(super) fn store(key: &[u8; KEY_LEN]) -> Result<(), KeychainError> {
        #[cfg(not(test))]
        let (service_name, account_name) = (super::SERVICE.to_owned(), super::ACCOUNT.to_owned());
        #[cfg(test)]
        let (service_name, account_name) = native_test::identity();
        let service = string(&service_name)?;
        let account = string(&account_name)?;
        let data = unsafe { CFDataCreate(ptr::null(), key.as_ptr(), KEY_LEN as CFIndex) };
        if data.is_null() {
            return Err(KeychainError::Unavailable);
        }
        let objects = Owned(vec![service, account, data]);
        #[allow(unused_mut)]
        let mut entries = unsafe {
            vec![
                (kSecClass, kSecClassGenericPassword),
                (kSecAttrService, service),
                (kSecAttrAccount, account),
                (kSecValueData, data),
                (
                    kSecAttrAccessible,
                    kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly,
                ),
            ]
        };
        #[cfg(test)]
        native_test::restrict_add(&mut entries)?;
        let dictionary = unsafe { dictionary(&entries)? };
        let status = unsafe { SecItemAdd(dictionary, ptr::null_mut()) };
        #[cfg(test)]
        eprintln!("native_keychain operation=restricted_add status={status}");
        unsafe { CFRelease(dictionary) };
        drop(objects);
        if status == 0 {
            Ok(())
        } else if status == ERR_DUPLICATE_ITEM {
            Err(KeychainError::DuplicateItem)
        } else {
            Err(KeychainError::Unavailable)
        }
    }

    pub(super) fn load_account(account_name: &str) -> Result<Option<[u8; KEY_LEN]>, KeychainError> {
        let mut result = ptr::null();
        let response = unsafe {
            #[cfg(not(test))]
            let service_name = super::SERVICE.to_owned();
            #[cfg(test)]
            let service_name = native_test::identity().0;
            let service = string(&service_name)?;
            let account = string(account_name)?;
            let extras = Owned(vec![service, account]);
            #[allow(unused_mut)]
            let mut entries = vec![
                (kSecClass, kSecClassGenericPassword),
                (kSecAttrService, service),
                (kSecAttrAccount, account),
                (kSecReturnData, kCFBooleanTrue),
                (kSecMatchLimit, kSecMatchLimitOne),
            ];
            #[cfg(test)]
            let _scope = native_test::restrict_search(&mut entries)?;
            let query = dictionary(&entries)?;
            let status = SecItemCopyMatching(query, &mut result);
            CFRelease(query);
            drop(extras);
            if status == ERR_ITEM_NOT_FOUND {
                Ok(None)
            } else if status != 0 || result.is_null() {
                Err(KeychainError::Unavailable)
            } else {
                let data = result as CFDataRef;
                if CFDataGetLength(data) != KEY_LEN as CFIndex {
                    CFRelease(result);
                    Err(KeychainError::InvalidItem)
                } else {
                    let pointer = CFDataGetBytePtr(data);
                    if pointer.is_null() {
                        CFRelease(result);
                        Err(KeychainError::InvalidItem)
                    } else {
                        let mut key = [0_u8; KEY_LEN];
                        ptr::copy_nonoverlapping(pointer, key.as_mut_ptr(), KEY_LEN);
                        CFRelease(result);
                        Ok(Some(key))
                    }
                }
            }
        };
        response
    }

    pub(super) fn store_account(
        account_name: &str,
        key: &[u8; KEY_LEN],
    ) -> Result<(), KeychainError> {
        #[cfg(not(test))]
        let service_name = super::SERVICE.to_owned();
        #[cfg(test)]
        let service_name = native_test::identity().0;
        let service = string(&service_name)?;
        let account = string(account_name)?;
        let data = unsafe { CFDataCreate(ptr::null(), key.as_ptr(), KEY_LEN as CFIndex) };
        if data.is_null() {
            return Err(KeychainError::Unavailable);
        }
        let objects = Owned(vec![service, account, data]);
        #[allow(unused_mut)]
        let mut entries = unsafe {
            vec![
                (kSecClass, kSecClassGenericPassword),
                (kSecAttrService, service),
                (kSecAttrAccount, account),
                (kSecValueData, data),
                (
                    kSecAttrAccessible,
                    kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly,
                ),
            ]
        };
        #[cfg(test)]
        native_test::restrict_add(&mut entries)?;
        let dictionary = unsafe { dictionary(&entries)? };
        let status = unsafe { SecItemAdd(dictionary, ptr::null_mut()) };
        unsafe { CFRelease(dictionary) };
        drop(objects);
        if status == 0 {
            Ok(())
        } else if status == ERR_DUPLICATE_ITEM {
            Err(KeychainError::DuplicateItem)
        } else {
            Err(KeychainError::Unavailable)
        }
    }

    pub(super) fn delete_account(account_name: &str) -> Result<(), KeychainError> {
        #[cfg(not(test))]
        let service_name = super::SERVICE.to_owned();
        #[cfg(test)]
        let service_name = native_test::identity().0;
        let service = string(&service_name)?;
        let account = string(account_name)?;
        let objects = Owned(vec![service, account]);
        #[allow(unused_mut)]
        let mut entries = unsafe {
            vec![
                (kSecClass, kSecClassGenericPassword),
                (kSecAttrService, service),
                (kSecAttrAccount, account),
                (kSecMatchLimit, kSecMatchLimitOne),
            ]
        };
        #[cfg(test)]
        let _scope = native_test::restrict_search(&mut entries)?;
        let query = unsafe { dictionary(&entries)? };
        let status = unsafe { SecItemDelete(query) };
        unsafe { CFRelease(query) };
        drop(objects);
        if status == 0 || status == ERR_ITEM_NOT_FOUND {
            Ok(())
        } else {
            Err(KeychainError::Unavailable)
        }
    }

    // No Keychain path or selector exists in non-test builds.
    #[cfg(test)]
    pub(crate) mod native_test {
        include!("storage_keychain_native_test.rs");
    }
}

#[cfg(all(test, target_os = "macos"))]
pub(crate) use macos::native_test;

#[cfg(test)]
mod tests {
    use super::*;
    use std::cell::RefCell;

    struct FakeKeychain(RefCell<Option<[u8; KEY_LEN]>>, bool);
    impl KeychainBackend for FakeKeychain {
        fn load(&self) -> Result<Option<[u8; KEY_LEN]>, KeychainError> {
            if self.1 {
                return Err(KeychainError::Unavailable);
            }
            Ok(*self.0.borrow())
        }
        fn store(&self, key: &[u8; KEY_LEN]) -> Result<(), KeychainError> {
            if self.1 {
                return Err(KeychainError::Unavailable);
            }
            *self.0.borrow_mut() = Some(*key);
            Ok(())
        }
    }

    #[test]
    fn absent_item_is_generated_and_persisted_once() {
        let keychain = FakeKeychain(RefCell::new(None), false);
        let first = load_or_create_with(&keychain, || Ok([7; KEY_LEN])).unwrap();
        let second = load_or_create_with(&keychain, || panic!("must reuse stored key")).unwrap();
        assert_eq!(first, [7; KEY_LEN]);
        assert_eq!(second, first);
    }

    #[test]
    fn unavailable_keychain_fails_without_generating_a_key() {
        let keychain = FakeKeychain(RefCell::new(None), true);
        let generated = RefCell::new(false);
        let result = load_or_create_with(&keychain, || {
            *generated.borrow_mut() = true;
            Ok([9; KEY_LEN])
        });
        assert_eq!(result, Err(KeychainError::Unavailable));
        assert!(!*generated.borrow());
    }

    #[test]
    fn missing_item_is_not_replaced_when_unlocking_existing_data() {
        let keychain = FakeKeychain(RefCell::new(None), false);
        assert_eq!(
            load_existing_with(&keychain),
            Err(KeychainError::MissingItem)
        );
        assert!(keychain.0.borrow().is_none());
    }

    #[test]
    fn concurrent_creation_uses_the_key_that_won_in_keychain() {
        let existing_key = [5; KEY_LEN];
        struct Winner([u8; KEY_LEN], RefCell<usize>);
        impl KeychainBackend for Winner {
            fn load(&self) -> Result<Option<[u8; KEY_LEN]>, KeychainError> {
                *self.1.borrow_mut() += 1;
                Ok(Some(self.0))
            }
            fn store(&self, _key: &[u8; KEY_LEN]) -> Result<(), KeychainError> {
                Err(KeychainError::DuplicateItem)
            }
        }
        let result =
            load_or_create_with(&Winner(existing_key, RefCell::new(0)), || Ok([9; KEY_LEN]));
        assert_eq!(result, Ok(existing_key));
    }

    struct MapKeychain(RefCell<Vec<(String, [u8; KEY_LEN])>>);
    impl GenerationBackend for MapKeychain {
        fn load_generation(&self, account: &str) -> Result<Option<[u8; KEY_LEN]>, KeychainError> {
            Ok(self
                .0
                .borrow()
                .iter()
                .find(|(name, _)| name == account)
                .map(|(_, key)| *key))
        }
        fn store_new_generation(
            &self,
            account: &str,
            key: &[u8; KEY_LEN],
        ) -> Result<(), KeychainError> {
            if self.load_generation(account)?.is_some() {
                return Err(KeychainError::DuplicateItem);
            }
            self.0.borrow_mut().push((account.to_owned(), *key));
            Ok(())
        }
        fn delete_generation(&self, account: &str) -> Result<(), KeychainError> {
            self.0.borrow_mut().retain(|(name, _)| name != account);
            Ok(())
        }
    }

    fn journal(phase: &str, staged: &str) -> RotationJournal {
        RotationJournal {
            phase: phase.to_owned(),
            from_account: "primary".to_owned(),
            to_account: "gen-v1-0123456789abcdef0123456789abcdef".to_owned(),
            primary_digest: "ab".repeat(32),
            staged_digest: staged.to_owned(),
        }
    }

    #[test]
    fn unlock_selection_follows_ciphertext_digest() {
        assert_eq!(
            select_unlock_account(None, None).unwrap(),
            UnlockAccount::Legacy
        );
        let pending = journal("linked", &"cd".repeat(32));
        assert_eq!(
            select_unlock_account(Some(&pending), Some(&"ab".repeat(32))).unwrap(),
            UnlockAccount::Legacy
        );
        assert_eq!(
            select_unlock_account(Some(&pending), Some(&"cd".repeat(32))).unwrap(),
            UnlockAccount::Generation(pending.to_account.clone())
        );
        assert_eq!(
            select_unlock_account(Some(&pending), Some(&"ef".repeat(32))),
            Err(SelectionError::Ambiguous)
        );
        assert_eq!(
            select_unlock_account(Some(&pending), None),
            Err(SelectionError::Ambiguous)
        );
    }

    #[test]
    fn retirement_never_removes_the_generation_that_opens_the_primary() {
        let ready = journal("validated", &"cd".repeat(32));
        assert_eq!(
            retirement_account(&ready, &"cd".repeat(32)).as_deref(),
            Some("primary")
        );
        assert_eq!(retirement_account(&ready, &"ab".repeat(32)), None);
        assert_eq!(
            retirement_account(&journal("linked", &"cd".repeat(32)), &"cd".repeat(32)),
            None
        );
        let keychain = MapKeychain(RefCell::new(vec![
            ("primary".to_owned(), [1; KEY_LEN]),
            (ready.to_account.clone(), [2; KEY_LEN]),
        ]));
        assert_eq!(
            retire_matching_account(&keychain, &ready, &"ab".repeat(32), "primary"),
            Err(KeychainError::InvalidItem)
        );
        assert_eq!(keychain.0.borrow().len(), 2);
        assert_eq!(
            retire_matching_account(&keychain, &ready, &"cd".repeat(32), &ready.to_account),
            Err(KeychainError::InvalidItem)
        );
        assert_eq!(keychain.0.borrow().len(), 2);
        retire_matching_account(&keychain, &ready, &"cd".repeat(32), "primary").unwrap();
        assert!(keychain.load_generation("primary").unwrap().is_none());
        assert_eq!(
            keychain.load_generation(&ready.to_account).unwrap(),
            Some([2; KEY_LEN])
        );
    }

    #[test]
    fn new_generation_is_not_written_over_a_different_item() {
        let keychain = MapKeychain(RefCell::new(vec![(
            "gen-v1-0123456789abcdef0123456789abcdef".to_owned(),
            [4; KEY_LEN],
        )]));
        let generation = "gen-v1-0123456789abcdef0123456789abcdef";
        assert_eq!(
            install_new_generation(&keychain, generation, &[9; KEY_LEN]),
            Err(KeychainError::DuplicateItem)
        );
        assert_eq!(
            keychain.load_generation(generation).unwrap(),
            Some([4; KEY_LEN])
        );
        install_new_generation(&keychain, generation, &[4; KEY_LEN]).unwrap();
        assert_eq!(keychain.0.borrow().len(), 1);
    }

    #[test]
    fn missing_intent_key_is_created_only_before_any_new_ciphertext() {
        let intent = journal("intent", "");
        assert!(missing_intent_key_may_be_created(&intent, &"ab".repeat(32)));
        assert!(!missing_intent_key_may_be_created(
            &intent,
            &"cd".repeat(32)
        ));
        assert!(!missing_intent_key_may_be_created(
            &journal("key_stored", ""),
            &"ab".repeat(32)
        ));
        assert!(!missing_intent_key_may_be_created(
            &journal("published", &"cd".repeat(32)),
            &"cd".repeat(32)
        ));
    }

    #[test]
    fn malformed_journal_does_not_select_a_substitute_account() {
        assert_eq!(
            parse_rotation_journal(b"{}"),
            Err(SelectionError::Ambiguous)
        );
        assert_eq!(
            parse_rotation_journal(br#"{"version":2}"#),
            Err(SelectionError::Ambiguous)
        );
    }
}
