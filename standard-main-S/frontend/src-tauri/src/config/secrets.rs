//! At-rest encryption for API keys stored in the `settings` table.
//!
//! Uses Windows DPAPI (CryptProtectData/CryptUnprotectData). The encryption
//! key is derived and held by Windows itself and is tied to the logged-in
//! user account — copying studio.db to another machine, or opening it as a
//! different Windows user, yields ciphertext that cannot be decrypted. That
//! is the property we want: the DB file alone must not leak the keys.
//!
//! Deliberately NOT an AES key embedded in the binary. A key shipped next to
//! the data it protects is obfuscation, not encryption, and it would have
//! cost an extra crate here plus a `cryptography` pip dependency on the
//! Python side. DPAPI is already present on every Windows install.
//!
//! Wire format stored in the DB:  `dpapi:<base64 of the DPAPI blob>`
//! `adapters/secrets.py` implements the identical format so the Python
//! extraction pipeline reads the same rows. Change one, change both — the
//! cross-language round-trip test in that module is the guard.

/// Marker prefix for an encrypted value. A stored value WITHOUT this prefix
/// is legacy plaintext, written before encryption existed.
pub const ENC_PREFIX: &str = "dpapi:";

/// App-specific entropy, mixed into the DPAPI blob. Stops a blob produced by
/// some other program running as the same user from being pasted into our
/// settings table and decrypting. Must byte-match ENTROPY in secrets.py.
const ENTROPY: &[u8] = b"enstudio.api_key.v1";

/// True for settings keys whose value is a credential. Covers the fixed
/// provider keys and the dynamic `custom_<id>_api_key` rows.
pub fn is_secret_key(field: &str) -> bool {
    field.ends_with("_api_key")
}

#[cfg(windows)]
mod dpapi {
    #[repr(C)]
    struct DataBlob {
        cb_data: u32,
        pb_data: *mut u8,
    }

    // CRYPTPROTECT_UI_FORBIDDEN — never show a UI prompt; fail instead. This
    // runs on a background thread during extraction, where a modal prompt
    // would hang the process.
    const UI_FORBIDDEN: u32 = 0x1;

    #[link(name = "crypt32")]
    extern "system" {
        fn CryptProtectData(
            data_in: *const DataBlob,
            descr: *const u16,
            entropy: *const DataBlob,
            reserved: *mut core::ffi::c_void,
            prompt: *mut core::ffi::c_void,
            flags: u32,
            data_out: *mut DataBlob,
        ) -> i32;
        fn CryptUnprotectData(
            data_in: *const DataBlob,
            descr_out: *mut *mut u16,
            entropy: *const DataBlob,
            reserved: *mut core::ffi::c_void,
            prompt: *mut core::ffi::c_void,
            flags: u32,
            data_out: *mut DataBlob,
        ) -> i32;
    }

    #[link(name = "kernel32")]
    extern "system" {
        fn LocalFree(mem: *mut core::ffi::c_void) -> *mut core::ffi::c_void;
    }

    fn blob(bytes: &[u8]) -> DataBlob {
        DataBlob { cb_data: bytes.len() as u32, pb_data: bytes.as_ptr() as *mut u8 }
    }

    /// Copy the output blob into a Vec and LocalFree the DPAPI allocation.
    /// Every success path must go through here or it leaks.
    unsafe fn take_output(out: DataBlob) -> Vec<u8> {
        let v = std::slice::from_raw_parts(out.pb_data, out.cb_data as usize).to_vec();
        LocalFree(out.pb_data as *mut core::ffi::c_void);
        v
    }

    pub fn protect(plain: &[u8], entropy: &[u8]) -> Result<Vec<u8>, String> {
        unsafe {
            let mut out = DataBlob { cb_data: 0, pb_data: std::ptr::null_mut() };
            let ok = CryptProtectData(
                &blob(plain), std::ptr::null(), &blob(entropy),
                std::ptr::null_mut(), std::ptr::null_mut(), UI_FORBIDDEN, &mut out,
            );
            if ok == 0 { return Err("CryptProtectData failed".to_string()); }
            Ok(take_output(out))
        }
    }

    pub fn unprotect(cipher: &[u8], entropy: &[u8]) -> Result<Vec<u8>, String> {
        unsafe {
            let mut out = DataBlob { cb_data: 0, pb_data: std::ptr::null_mut() };
            let ok = CryptUnprotectData(
                &blob(cipher), std::ptr::null_mut(), &blob(entropy),
                std::ptr::null_mut(), std::ptr::null_mut(), UI_FORBIDDEN, &mut out,
            );
            if ok == 0 { return Err("CryptUnprotectData failed".to_string()); }
            Ok(take_output(out))
        }
    }
}

/// Encrypt a secret for storage. Returns the `dpapi:<base64>` wire form.
///
/// Non-Windows builds have no DPAPI, so this returns the value unchanged
/// (unencrypted) rather than pretending. The app is Windows-only in practice
/// — see the VS2022 link requirement in README — so this is the status quo,
/// not a regression, but it IS a real gap if the app is ever ported.
pub fn encrypt_secret(plain: &str) -> Result<String, String> {
    if plain.is_empty() { return Ok(String::new()); }
    #[cfg(windows)]
    {
        use base64::Engine as _;
        let blob = dpapi::protect(plain.as_bytes(), ENTROPY)?;
        Ok(format!("{}{}", ENC_PREFIX, base64::engine::general_purpose::STANDARD.encode(blob)))
    }
    #[cfg(not(windows))]
    { Ok(plain.to_string()) }
}

/// Decrypt a stored value. A value without the `dpapi:` prefix is returned
/// as-is — that is a legacy plaintext row, and migrate_plaintext_secrets()
/// rewrites those on startup.
pub fn decrypt_secret(stored: &str) -> Result<String, String> {
    let Some(b64) = stored.strip_prefix(ENC_PREFIX) else {
        return Ok(stored.to_string());
    };
    #[cfg(windows)]
    {
        use base64::Engine as _;
        let raw = base64::engine::general_purpose::STANDARD.decode(b64)
            .map_err(|e| format!("Stored key is not valid base64: {}", e))?;
        let plain = dpapi::unprotect(&raw, ENTROPY)?;
        String::from_utf8(plain).map_err(|_| "Decrypted key is not valid UTF-8".to_string())
    }
    #[cfg(not(windows))]
    {
        let _ = b64;
        Err("Encrypted key found but DPAPI is unavailable on this platform".to_string())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn round_trips_and_does_not_store_plaintext() {
        let secret = "sk-ant-api03-NOTAREALKEY-0123456789";
        let stored = encrypt_secret(secret).expect("encrypt");

        if cfg!(windows) {
            assert!(stored.starts_with(ENC_PREFIX), "missing marker: {}", stored);
            // The whole point: the key must not be readable in the stored form.
            assert!(!stored.contains(secret), "plaintext leaked into stored value");
            assert!(!stored.contains("sk-ant"), "key prefix leaked into stored value");
        }
        assert_eq!(decrypt_secret(&stored).expect("decrypt"), secret);
    }

    #[test]
    fn legacy_plaintext_reads_back_unchanged() {
        // Rows written before encryption existed have no prefix and must keep
        // working, otherwise every existing install loses its configured key.
        assert_eq!(decrypt_secret("sk-plain-legacy").unwrap(), "sk-plain-legacy");
    }

    #[test]
    fn empty_stays_empty() {
        // load_config_key() treats "" as unset; encrypting it would produce a
        // non-empty blob and make an unset key look configured.
        assert_eq!(encrypt_secret("").unwrap(), "");
        assert_eq!(decrypt_secret("").unwrap(), "");
    }

    #[test]
    fn only_api_key_fields_are_treated_as_secret() {
        assert!(is_secret_key("anthropic_api_key"));
        assert!(is_secret_key("custom_grok_api_key"));
        assert!(!is_secret_key("anthropic_model_smart"));
        assert!(!is_secret_key("llm_provider"));
    }

    #[cfg(windows)]
    #[test]
    fn wrong_entropy_cannot_decrypt() {
        // Guards the entropy binding: a DPAPI blob made by another program
        // running as the same user must not decrypt in our settings table.
        let foreign = dpapi::protect(b"attacker-value", b"some.other.app").unwrap();
        use base64::Engine as _;
        let stored = format!("{}{}", ENC_PREFIX,
            base64::engine::general_purpose::STANDARD.encode(foreign));
        assert!(decrypt_secret(&stored).is_err());
    }
}

#[cfg(all(test, windows))]
mod interop {
    use super::*;
    /// Decrypt a blob produced by adapters/secrets.py. Skipped unless
    /// ENSTUDIO_PY_BLOB is set, so the normal `cargo test` run stays offline;
    /// tests/test_secrets.py documents how to produce one.
    #[test]
    fn decrypts_python_produced_blob() {
        let Ok(blob) = std::env::var("ENSTUDIO_PY_BLOB") else { return };
        let expected = std::env::var("ENSTUDIO_PY_PLAIN").expect("ENSTUDIO_PY_PLAIN");
        assert_eq!(decrypt_secret(&blob).expect("rust must decrypt python's blob"), expected);
    }
}

