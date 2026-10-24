use super::*;

#[test]
fn disposable_keychain_unlocks_real_runtime_over_uds() {
    let keychain = crate::storage_keychain::native_test::DisposableKeychain::create();
    let api_root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../api");
    let python = api_root.join(".venv/bin/python");
    assert!(
        python.is_file(),
        "locked API virtualenv required; no installation"
    );
    let manager = manager();
    let instance_id = new_instance_id();
    let session = TransportSession::create(&instance_id).unwrap();
    let database_path = session.directory_path().join("keychain-synthetic.snapshot");
    struct ProfileEnv(Option<std::ffi::OsString>);
    impl Drop for ProfileEnv {
        fn drop(&mut self) {
            match self.0.take() {
                Some(value) => env::set_var("JARVIS_DATABASE_PATH", value),
                None => env::remove_var("JARVIS_DATABASE_PATH"),
            }
        }
    }
    let _profile = ProfileEnv(env::var_os("JARVIS_DATABASE_PATH"));
    env::set_var("JARVIS_DATABASE_PATH", &database_path);
    let mut child = Command::new(python)
        .arg("-u")
        .arg(api_root.join("serve.py"))
        .arg("--desktop-runtime")
        .arg(&instance_id)
        .current_dir(session.directory_path())
        .env_clear()
        .env("JARVIS_LOCAL_PASSPHRASE", "synthetic-keychain-session")
        .env("JARVIS_DATABASE_PATH", &database_path)
        .env("TMPDIR", env::temp_dir())
        .env("PYTHONDONTWRITEBYTECODE", "1")
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()
        .expect("own synthetic runtime starts");
    session.set_expected_peer_pid(child.id()).unwrap();
    let stdin = child.stdin.take().unwrap();
    let mut process = FastApiChild {
        child,
        stdin,
        instance_id: instance_id.clone(),
    };
    session.write_child_init(&mut process.stdin).unwrap();
    let stdout = process.child.stdout.take().unwrap();
    let (tx, rx) = mpsc::channel();
    thread::spawn(move || {
        let mut line = String::new();
        let _ = BufReader::new(stdout).read_line(&mut line);
        let _ = tx.send(line);
    });
    assert_eq!(
        rx.recv_timeout(Duration::from_secs(12)).expect("READY"),
        format!("{READY_PREFIX}{instance_id}\n")
    );
    writeln!(process.stdin, "{ACK_PREFIX}{instance_id}").unwrap();
    process.stdin.flush().unwrap();
    session
        .probe()
        .expect("authenticated peer PID/generation proof");
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
            runtime_instance_id: Some(instance_id),
            endpoint_type: Some("uds"),
            protocol_version: Some(PROTOCOL_VERSION.to_owned()),
            error_category: None,
        };
        inner.transport_session = Some(Arc::clone(&session));
    }
    struct LockAtEnd<'a>(&'a RuntimeManager);
    impl Drop for LockAtEnd<'_> {
        fn drop(&mut self) {
            let _ = self.0.storage_lock_native();
        }
    }
    let lock_at_end = LockAtEnd(&manager);
    let state = || {
        let bytes = session
            .call_g5_application("/v1/app/storage/status", b"")
            .unwrap();
        let fields = parse_application_response(&bytes).unwrap();
        app_field(&fields, "state").unwrap().to_owned()
    };
    assert_eq!(state(), "locked");
    assert!(!database_path.exists());
    assert!(matches!(
        crate::storage_keychain::load_existing_key(),
        Err(crate::storage_keychain::KeychainError::MissingItem)
    ));
    assert_eq!(
        manager.storage_unlock_native(),
        "{\"ok\":true,\"state\":\"unlocked\"}"
    );
    assert_eq!(state(), "unlocked");
    assert!(manager
        .g5_session_open(SecretText::new("synthetic-keychain-session".to_owned()))
        .contains("\"session_active\":true"));
    const CANARY: &str = "SYNTHETIC_NATIVE_KEYCHAIN_UDS_CANARY";
    assert!(manager
        .g5_capture_create(CANARY.to_owned())
        .contains("\"ok\":true"));
    assert!(manager.g5_capture_list().contains(CANARY));
    let committed = fs::read(&database_path).unwrap();
    assert!(committed.starts_with(b"JVSDB\0\x01\0"));
    assert!(!committed
        .windows(CANARY.len())
        .any(|part| part == CANARY.as_bytes()));
    assert_eq!(
        manager.storage_lock_native(),
        "{\"ok\":true,\"state\":\"locked\"}"
    );
    keychain.lock();
    assert_eq!(
        manager.storage_unlock_native(),
        g5_error_json("keychain_unavailable")
    );
    assert_eq!(state(), "locked");
    assert!(fs::read(&database_path).unwrap() == committed);
    keychain.unlock();
    assert_eq!(
        manager.storage_unlock_native(),
        "{\"ok\":true,\"state\":\"unlocked\"}"
    );
    assert!(manager
        .g5_session_open(SecretText::new("synthetic-keychain-session".to_owned()))
        .contains("\"session_active\":true"));
    assert!(manager.g5_capture_list().contains(CANARY));
    assert_eq!(
        manager.storage_lock_native(),
        "{\"ok\":true,\"state\":\"locked\"}"
    );
    let preserved = fs::read(&database_path).unwrap();
    keychain.delete_item().unwrap();
    assert_eq!(
        manager.storage_unlock_native(),
        g5_error_json("keychain_item_missing")
    );
    assert_eq!(state(), "locked");
    assert!(fs::read(&database_path).unwrap() == preserved);
    // A new native item is the wrong key for this existing snapshot.
    let mut wrong = crate::storage_keychain::load_or_create_key().unwrap();
    let encoded = SecretText::new(wrong.iter().map(|b| format!("{b:02x}")).collect());
    let body = SecretBytes::new(encode_application_fields(&[(
        "database_key",
        encoded.as_str(),
    )]));
    wrong.fill(0);
    drop(encoded);
    let rejected = session
        .call_g5_application("/v1/app/storage/unlock", body.as_slice())
        .unwrap();
    drop(body);
    let rejected = parse_application_response(&rejected).unwrap();
    assert_eq!(app_field(&rejected, "ok"), Some("false"));
    assert_eq!(app_field(&rejected, "code"), Some("storage_unlock_failed"));
    // The current Rust application-error mapper exposes a generic local-task
    // error for this API code. Keep that public contract and verify the precise
    // server refusal above, as well as locked state and unchanged bytes below.
    assert_eq!(
        manager.storage_unlock_native(),
        g5_error_json("workflow_failed")
    );
    assert_eq!(state(), "locked");
    assert!(fs::read(&database_path).unwrap() == preserved);
    for suffix in ["-wal", "-shm", "-journal"] {
        assert!(!PathBuf::from(format!("{}{suffix}", database_path.display())).exists());
    }
    drop(lock_at_end);
    assert_eq!(state(), "locked");
    assert_eq!(process.stop(), 0);
    session.revoke();
    keychain.close();
    // Only artifacts owned by this newly created synthetic test profile.
    for entry in fs::read_dir(session.directory_path()).unwrap() {
        let entry = entry.unwrap();
        assert!(entry.file_type().unwrap().is_file());
        fs::remove_file(entry.path()).unwrap();
    }
    fs::remove_dir(session.directory_path()).unwrap();
    eprintln!("native_keychain stage=real_Rust_UDS_unlock_write_reopen_refusals_final_lock PASS");
}

#[test]
fn disposable_keychain_rotates_synthetic_database_over_uds() {
    let keychain = crate::storage_keychain::native_test::DisposableKeychain::create();
    let api_root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../api");
    let python = api_root.join(".venv/bin/python");
    assert!(python.is_file(), "locked API virtualenv required; no installation");
    let manager = manager();
    let instance_id = new_instance_id();
    let session = TransportSession::create(&instance_id).unwrap();
    let database_path = session.directory_path().join("keychain-rotation.snapshot");
    struct ProfileEnv(Option<std::ffi::OsString>);
    impl Drop for ProfileEnv {
        fn drop(&mut self) {
            match self.0.take() {
                Some(value) => env::set_var("JARVIS_DATABASE_PATH", value),
                None => env::remove_var("JARVIS_DATABASE_PATH"),
            }
        }
    }
    let _profile = ProfileEnv(env::var_os("JARVIS_DATABASE_PATH"));
    env::set_var("JARVIS_DATABASE_PATH", &database_path);
    let mut child = Command::new(python)
        .arg("-u")
        .arg(api_root.join("serve.py"))
        .arg("--desktop-runtime")
        .arg(&instance_id)
        .current_dir(session.directory_path())
        .env_clear()
        .env("JARVIS_LOCAL_PASSPHRASE", "synthetic-keychain-session")
        .env("JARVIS_DATABASE_PATH", &database_path)
        .env("TMPDIR", env::temp_dir())
        .env("PYTHONDONTWRITEBYTECODE", "1")
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()
        .expect("own synthetic runtime starts");
    session.set_expected_peer_pid(child.id()).unwrap();
    let stdin = child.stdin.take().unwrap();
    let mut process = FastApiChild {
        child,
        stdin,
        instance_id: instance_id.clone(),
    };
    session.write_child_init(&mut process.stdin).unwrap();
    let stdout = process.child.stdout.take().unwrap();
    let (tx, rx) = mpsc::channel();
    thread::spawn(move || {
        let mut line = String::new();
        let _ = BufReader::new(stdout).read_line(&mut line);
        let _ = tx.send(line);
    });
    assert_eq!(
        rx.recv_timeout(Duration::from_secs(12)).expect("READY"),
        format!("{READY_PREFIX}{instance_id}\n")
    );
    writeln!(process.stdin, "{ACK_PREFIX}{instance_id}").unwrap();
    process.stdin.flush().unwrap();
    session
        .probe()
        .expect("authenticated peer PID/generation proof");
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
            runtime_instance_id: Some(instance_id),
            endpoint_type: Some("uds"),
            protocol_version: Some(PROTOCOL_VERSION.to_owned()),
            error_category: None,
        };
        inner.transport_session = Some(Arc::clone(&session));
    }
    struct LockAtEnd<'a>(&'a RuntimeManager);
    impl Drop for LockAtEnd<'_> {
        fn drop(&mut self) {
            let _ = self.0.storage_lock_native();
        }
    }
    let lock_at_end = LockAtEnd(&manager);
    assert_eq!(
        manager.storage_unlock_native(),
        "{\"ok\":true,\"state\":\"unlocked\"}"
    );
    assert!(manager
        .g5_session_open(SecretText::new("synthetic-keychain-session".to_owned()))
        .contains("\"session_active\":true"));
    const CANARY: &str = "SYNTHETIC_NATIVE_ROTATION_UDS_CANARY";
    assert!(manager
        .g5_capture_create(CANARY.to_owned())
        .contains("\"ok\":true"));
    let before = fs::read(&database_path).unwrap();
    assert!(before.starts_with(b"JVSDB\0\x01\0"));
    assert_eq!(
        manager.storage_rotate_native(),
        "{\"ok\":true,\"state\":\"finalized\"}"
    );
    assert_eq!(
        manager.storage_rotate_native(),
        "{\"ok\":true,\"state\":\"finalized\"}"
    );
    let recovery = database_path.parent().unwrap().read_dir().unwrap().any(|entry| {
        entry
            .ok()
            .and_then(|item| item.file_name().into_string().ok())
            .is_some_and(|name| name.contains(".rotation-") && name.ends_with(".sealed"))
    });
    assert!(!recovery);
    let after = fs::read(&database_path).unwrap();
    assert!(after.starts_with(b"JVSDB\0\x01\0"));
    assert_ne!(after, before);
    assert!(!after.windows(CANARY.len()).any(|part| part == CANARY.as_bytes()));
    let journal = database_path
        .parent()
        .unwrap()
        .join(".keychain-rotation.snapshot.key-rotation.json");
    let journal_bytes = fs::read(&journal).unwrap();
    assert!(journal_bytes.starts_with(b"JVRJT\x00\x01\x00"));
    assert!(journal_bytes.windows(CANARY.len()).all(|part| part != CANARY.as_bytes()));
    assert!(manager.g5_capture_list().contains(CANARY));
    assert_eq!(
        manager.storage_lock_native(),
        "{\"ok\":true,\"state\":\"locked\"}"
    );
    let mut old = crate::storage_keychain::load_existing_key().unwrap();
    let encoded = SecretText::new(old.iter().map(|byte| format!("{byte:02x}")).collect());
    let body = SecretBytes::new(encode_application_fields(&[("database_key", encoded.as_str())]));
    old.fill(0);
    drop(encoded);
    let rejected = session
        .call_g5_application("/v1/app/storage/unlock", body.as_slice())
        .unwrap();
    drop(body);
    let rejected = parse_application_response(&rejected).unwrap();
    assert_eq!(app_field(&rejected, "ok"), Some("false"));
    let preserved = fs::read(&database_path).unwrap();
    assert!(preserved.starts_with(b"JVSDB\0\x01\x00"));
    assert!(!preserved.windows(CANARY.len()).any(|part| part == CANARY.as_bytes()));
    assert_eq!(
        manager.storage_unlock_native(),
        "{\"ok\":true,\"state\":\"unlocked\"}"
    );
    assert!(manager
        .g5_session_open(SecretText::new("synthetic-keychain-session".to_owned()))
        .contains("\"session_active\":true"));
    assert!(manager.g5_capture_list().contains(CANARY));
    for suffix in ["-wal", "-shm", "-journal"] {
        assert!(!PathBuf::from(format!("{}{suffix}", database_path.display())).exists());
    }
    drop(lock_at_end);
    assert_eq!(process.stop(), 0);
    session.revoke();
    keychain.close();
    for entry in fs::read_dir(session.directory_path()).unwrap() {
        let entry = entry.unwrap();
        assert!(entry.file_type().unwrap().is_file());
        fs::remove_file(entry.path()).unwrap();
    }
    fs::remove_dir(session.directory_path()).unwrap();
    eprintln!("native_keychain stage=real_Rust_UDS_rotation_reopen PASS");
}
