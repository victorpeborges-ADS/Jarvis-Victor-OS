// Included only under cfg(test, target_os = "macos"). Native Security is never mocked.
use super::*;
use std::{cell::RefCell, ffi::CString, path::PathBuf};

#[link(name = "Security", kind = "framework")]
unsafe extern "C" {
    static kSecUseKeychain: CFStringRef;
    static kSecMatchSearchList: CFStringRef;
    static kSecMatchItemList: CFStringRef;
    static kSecReturnRef: CFStringRef;
    fn SecKeychainCreate(
        path: *const i8,
        len: u32,
        password: *const c_void,
        prompt: u8,
        access: CFTypeRef,
        result: *mut CFTypeRef,
    ) -> i32;
    fn SecKeychainDelete(keychain: CFTypeRef) -> i32;
    fn SecKeychainLock(keychain: CFTypeRef) -> i32;
    fn SecKeychainUnlock(
        keychain: CFTypeRef,
        len: u32,
        password: *const c_void,
        use_password: u8,
    ) -> i32;
    fn SecKeychainGetPath(keychain: CFTypeRef, len: *mut u32, path: *mut i8) -> i32;
    fn SecKeychainItemCopyKeychain(item: CFTypeRef, keychain: *mut CFTypeRef) -> i32;
    fn SecKeychainGetUserInteractionAllowed(allowed: *mut u8) -> i32;
    fn SecKeychainSetUserInteractionAllowed(allowed: u8) -> i32;
    fn SecItemDelete(query: CFDictionaryRef) -> i32;
}

#[link(name = "CoreFoundation", kind = "framework")]
unsafe extern "C" {
    fn CFArrayCreate(
        allocator: CFTypeRef,
        values: *const CFTypeRef,
        count: CFIndex,
        callbacks: *const c_void,
    ) -> CFTypeRef;
}

struct Scope {
    keychain: CFTypeRef,
    service: String,
    account: String,
}
thread_local! { static SCOPE: RefCell<Option<Scope>> = const { RefCell::new(None) }; }
static NATIVE_TEST_LOCK: std::sync::Mutex<()> = std::sync::Mutex::new(());

pub(super) fn identity() -> (String, String) {
    SCOPE.with(|slot| {
        let slot = slot.borrow();
        let scope = slot
            .as_ref()
            .expect("native test requires explicit disposable Keychain");
        (scope.service.clone(), scope.account.clone())
    })
}

fn keychain() -> Result<CFTypeRef, KeychainError> {
    SCOPE.with(|slot| {
        slot.borrow()
            .as_ref()
            .map(|s| s.keychain)
            .filter(|p| !p.is_null())
            .ok_or(KeychainError::Unavailable)
    })
}

fn array(value: CFTypeRef) -> Result<CFTypeRef, KeychainError> {
    if value.is_null() {
        return Err(KeychainError::Unavailable);
    }
    let result = unsafe { CFArrayCreate(ptr::null(), &value, 1, ptr::null()) };
    if result.is_null() {
        Err(KeychainError::Unavailable)
    } else {
        Ok(result)
    }
}

pub(super) fn restrict_search(
    entries: &mut Vec<(CFTypeRef, CFTypeRef)>,
) -> Result<Owned, KeychainError> {
    let list = array(keychain()?)?;
    entries.push((unsafe { kSecMatchSearchList }, list));
    Ok(Owned(vec![list]))
}

pub(super) fn restrict_add(entries: &mut Vec<(CFTypeRef, CFTypeRef)>) -> Result<(), KeychainError> {
    entries.push((unsafe { kSecUseKeychain }, keychain()?));
    Ok(())
}

/// Thread-bound injection; every native query fails closed without this guard.
pub(crate) struct DisposableKeychain {
    directory: PathBuf,
    path: PathBuf,
    reference: CFTypeRef,
    password: [u8; 64],
    previous_ui: u8,
    closed: bool,
    _serial: std::sync::MutexGuard<'static, ()>,
    _thread_bound: std::marker::PhantomData<std::rc::Rc<()>>,
}

impl DisposableKeychain {
    pub(crate) fn create() -> Self {
        let serial = NATIVE_TEST_LOCK.lock().unwrap_or_else(|e| e.into_inner());
        assert!(SCOPE.with(|s| s.borrow().is_none()));
        let random = super::super::random_key().expect("test entropy");
        let suffix: String = random[..12].iter().map(|b| format!("{b:02x}")).collect();
        let directory = std::env::temp_dir().join(format!("jarvis-native-keychain-{suffix}"));
        std::fs::create_dir(&directory).expect("new private temporary directory");
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(&directory, std::fs::Permissions::from_mode(0o700)).unwrap();
        let path = directory.join("disposable.keychain-db");
        let password_string: String = super::super::random_key()
            .unwrap()
            .iter()
            .map(|b| format!("{b:02x}"))
            .collect();
        let mut guard = Self {
            directory,
            path,
            reference: ptr::null(),
            password: [0; 64],
            previous_ui: 0,
            closed: false,
            _serial: serial,
            _thread_bound: std::marker::PhantomData,
        };
        guard.password.copy_from_slice(password_string.as_bytes());
        // No password is sent to a command, environment, file, or diagnostic.
        let mut password_string = password_string.into_bytes();
        password_string.fill(0);
        unsafe {
            assert_eq!(
                SecKeychainGetUserInteractionAllowed(&mut guard.previous_ui),
                0
            );
            assert_eq!(SecKeychainSetUserInteractionAllowed(0), 0);
            let path_c = CString::new(guard.path.as_os_str().as_encoded_bytes()).unwrap();
            let status = SecKeychainCreate(
                path_c.as_ptr(),
                64,
                guard.password.as_ptr().cast(),
                0,
                ptr::null(),
                &mut guard.reference,
            );
            assert_eq!(status, 0, "SecKeychainCreate disposable file status");
        }
        assert!(!guard.reference.is_null());
        let actual = keychain_path(guard.reference);
        assert_eq!(
            actual.parent().unwrap().canonicalize().unwrap(),
            guard.directory.canonicalize().unwrap()
        );
        guard.path = actual;
        assert!(guard.path.is_file());
        SCOPE.with(|slot| {
            *slot.borrow_mut() = Some(Scope {
                keychain: guard.reference,
                service: format!("test.jarvis.native.{suffix}"),
                account: format!("synthetic-{suffix}"),
            })
        });
        eprintln!("native_keychain stage=created_explicit_temporary_file PASS");
        guard
    }

    pub(crate) fn lock(&self) {
        assert_eq!(unsafe { SecKeychainLock(self.reference) }, 0);
    }
    pub(crate) fn unlock(&self) {
        assert_eq!(
            unsafe { SecKeychainUnlock(self.reference, 64, self.password.as_ptr().cast(), 1) },
            0
        );
    }

    pub(crate) fn delete_item(&self) -> Result<(), KeychainError> {
        // First obtain an exact reference from the explicitly restricted search.
        let (service, account) = identity();
        let service = string(&service)?;
        let account = string(&account)?;
        let _objects = Owned(vec![service, account]);
        let mut entries = unsafe {
            vec![
                (kSecClass, kSecClassGenericPassword),
                (kSecAttrService, service),
                (kSecAttrAccount, account),
                (kSecReturnRef, kCFBooleanTrue),
                (kSecMatchLimit, kSecMatchLimitOne),
            ]
        };
        let _list = restrict_search(&mut entries)?;
        let query = unsafe { dictionary(&entries)? };
        let _query = Owned(vec![query]);
        let mut item = ptr::null();
        let status = unsafe { SecItemCopyMatching(query, &mut item) };
        if status == ERR_ITEM_NOT_FOUND {
            return Ok(());
        }
        if status != 0 || item.is_null() {
            return Err(KeychainError::Unavailable);
        }
        let _item = Owned(vec![item]);
        let mut owner = ptr::null();
        if unsafe { SecKeychainItemCopyKeychain(item, &mut owner) } != 0 || owner.is_null() {
            return Err(KeychainError::Unavailable);
        }
        let _owner = Owned(vec![owner]);
        assert_eq!(
            keychain_path(owner),
            self.path,
            "item belongs to disposable file"
        );
        let items = array(item)?;
        let _items = Owned(vec![items]);
        // SecItem.h explicitly documents this exact-item deletion on macOS.
        let mut deletion = unsafe {
            vec![
                (kSecClass, kSecClassGenericPassword),
                (kSecAttrService, service),
                (kSecAttrAccount, account),
                (kSecMatchItemList, items),
            ]
        };
        let _deletion_list = restrict_search(&mut deletion)?;
        let query = unsafe { dictionary(&deletion)? };
        let _query = Owned(vec![query]);
        let status = unsafe { SecItemDelete(query) };
        eprintln!("native_keychain operation=restricted_delete status={status}");
        match status {
            0 | ERR_ITEM_NOT_FOUND => Ok(()),
            _ => Err(KeychainError::Unavailable),
        }
    }

    fn cleanup(&mut self) -> bool {
        if self.closed {
            return true;
        }
        let mut success = true;
        if !self.reference.is_null() {
            // Explicit credentials; UI stays disabled even during unwinding.
            let unlocked =
                unsafe { SecKeychainUnlock(self.reference, 64, self.password.as_ptr().cast(), 1) };
            if SCOPE.with(|s| s.borrow().is_some()) {
                success &= unlocked == 0 && self.delete_item().is_ok();
            }
            success &= unsafe { SecKeychainDelete(self.reference) } == 0;
            unsafe {
                CFRelease(self.reference);
            }
            self.reference = ptr::null();
        }
        SCOPE.with(|s| *s.borrow_mut() = None);
        self.password.fill(0);
        success &= unsafe { SecKeychainSetUserInteractionAllowed(self.previous_ui) } == 0;
        // Never remove a surviving Keychain with filesystem deletion: report it.
        success &= !self.path.exists();
        success &= std::fs::remove_dir(&self.directory).is_ok();
        self.closed = true;
        eprintln!("native_keychain cleanup_removed={success}");
        success
    }

    pub(crate) fn close(mut self) {
        assert!(self.cleanup(), "disposable Keychain cleanup");
    }
}

impl Drop for DisposableKeychain {
    fn drop(&mut self) {
        let _ = self.cleanup();
    }
}

fn keychain_path(reference: CFTypeRef) -> PathBuf {
    assert!(!reference.is_null());
    let mut bytes = [0u8; 4096];
    let mut len = bytes.len() as u32;
    assert_eq!(
        unsafe { SecKeychainGetPath(reference, &mut len, bytes.as_mut_ptr().cast()) },
        0
    );
    use std::os::unix::ffi::OsStrExt;
    PathBuf::from(std::ffi::OsStr::from_bytes(&bytes[..len as usize]))
}

#[test]
fn disposable_native_keychain_crud_and_access_failure() {
    let guard = DisposableKeychain::create();
    assert!(matches!(
        super::super::load_existing_key(),
        Err(KeychainError::MissingItem)
    ));
    let mut first = super::super::load_or_create_key().expect("native creation");
    let mut second = super::super::load_existing_key().expect("native retrieval");
    assert!(first == second, "native key comparison in memory");
    guard.lock();
    assert!(matches!(
        super::super::load_existing_key(),
        Err(KeychainError::Unavailable)
    ));
    guard.unlock();
    let mut recovered = super::super::load_existing_key().expect("native retrieval after unlock");
    assert!(recovered == first, "same key after native unlock");
    guard.delete_item().expect("delete exact temporary item");
    assert!(matches!(
        super::super::load_existing_key(),
        Err(KeychainError::MissingItem)
    ));
    first.fill(0);
    second.fill(0);
    recovered.fill(0);
    guard.close();
}

#[test]
fn pending_rotation_item_is_confined_to_the_disposable_keychain() {
    let guard = DisposableKeychain::create();
    let generation = "0123456789abcdef";
    assert!(matches!(
        super::super::load_pending_key(generation),
        Ok(None)
    ));
    let mut pending = [9_u8; 32];
    super::super::insert_pending_key(generation, &pending).expect("pending insert");
    let mut loaded = super::super::load_pending_key(generation)
        .expect("pending load")
        .expect("pending item");
    assert_eq!(loaded, pending);
    assert!(matches!(
        super::super::load_existing_key(),
        Err(super::super::KeychainError::MissingItem)
    ));
    super::super::delete_pending_key(generation).expect("pending delete");
    assert!(matches!(
        super::super::load_pending_key(generation),
        Ok(None)
    ));
    pending.fill(0);
    loaded.fill(0);
    guard.close();
}

#[test]
fn generation_items_are_distinct_and_confined_to_the_disposable_keychain() {
    let guard = DisposableKeychain::create();
    let current = "gen-v1-0123456789abcdef0123456789abcdef";
    let next = "gen-v1-fedcba9876543210fedcba9876543210";
    let mut current_key = [7_u8; 32];
    let mut next_key = [8_u8; 32];
    super::super::install_platform_generation(current, &current_key).expect("current item");
    super::super::install_platform_generation(next, &next_key).expect("next item");
    assert_eq!(
        super::super::install_platform_generation(current, &[9_u8; 32]),
        Err(super::super::KeychainError::DuplicateItem),
        "existing generation is not replaced"
    );
    let mut loaded_current = super::super::load_generation_key(current)
        .expect("load current")
        .expect("current present");
    let mut loaded_next = super::super::load_generation_key(next)
        .expect("load next")
        .expect("next present");
    assert!(loaded_current == current_key, "current generation mismatch");
    assert!(loaded_next == next_key, "next generation mismatch");
    super::delete_account(current).expect("retire current generation");
    assert!(super::load_account(current).expect("reload current").is_none());
    let mut still_next = super::load_account(next).expect("reload next").expect("next remains");
    assert!(still_next == next_key, "retirement removed the generation that remains");
    super::delete_account(next).expect("retire next generation");
    super::delete_account(next).expect("missing generation delete is idempotent");
    assert!(super::load_account(next).expect("reload deleted").is_none());
    current_key.fill(0);
    next_key.fill(0);
    loaded_current.fill(0);
    loaded_next.fill(0);
    still_next.fill(0);
    guard.close();
}
