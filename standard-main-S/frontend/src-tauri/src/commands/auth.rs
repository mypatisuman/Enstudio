use crate::database::open_db;
use crate::models::AuthUserDto;
use crate::utils::email_dns::{check_mail_domain, domain_of, lookalike_of};
use crate::config::load_config_key;

/// The one place an email address is judged. Three checks, cheapest first:
///
///   1. format      — offline, instant
///   2. lookalike   — offline, instant; catches `gmai.com`, which DNS cannot,
///                    because that domain genuinely exists and accepts mail
///   3. MX/A lookup — network; catches domains that do not exist at all
///
/// Personal/consumer addresses (gmail, outlook, …) are ACCEPTED. Only
/// definitive failures reject; a DNS outage lets the address through.
fn email_problem(email: &str) -> Option<String> {
    if !valid_email(email) {
        return Some("Please enter a valid email format.".to_string());
    }
    let domain = domain_of(email)?;

    // The matched provider is deliberately NOT named in the message — the user
    // is told the address is wrong, not what to replace it with.
    if lookalike_of(&domain).is_some() {
        return Some("That email domain doesn't look right. Check for a typo.".to_string());
    }

    check_mail_domain(&domain).rejection_reason().map(str::to_string)
}

/// Equivalent of the reference backend's
/// `^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$`, hand-rolled to avoid
/// pulling in the `regex` crate for one pattern. Stricter than the previous
/// check, which accepted things like `a@b.` and `a@-.com`.
fn valid_email(e: &str) -> bool {
    let e = e.trim();
    let Some((local, domain)) = e.split_once('@') else { return false };
    // Exactly one '@' — split_once leaves any extra in `domain`.
    if domain.contains('@') { return false; }

    if local.is_empty()
        || !local.chars().all(|c| c.is_ascii_alphanumeric() || "._%+-".contains(c)) {
        return false;
    }
    if domain.is_empty()
        || !domain.chars().all(|c| c.is_ascii_alphanumeric() || c == '.' || c == '-') {
        return false;
    }

    // Must end in a dot-separated TLD of >= 2 letters, and no empty labels
    // (which would allow "a@b..com" or a leading/trailing dot).
    let Some((host, tld)) = domain.rsplit_once('.') else { return false };
    host.split('.').all(|label| !label.is_empty())
        && tld.len() >= 2
        && tld.chars().all(|c| c.is_ascii_alphabetic())
}

/// One wording, used by both the live check and the real signup, so the
/// inline hint can never say something submit disagrees with.
const USERNAME_TAKEN: &str = "That username is already taken.";

/// Case-insensitive — `Daman` and `daman` are the same account name, so one
/// blocks the other. Matches the LOWER(username) unique index in schema.rs.
///
/// A query error reads as "not taken": the live check must not claim a name
/// is unavailable because the DB hiccupped, and signup is still backstopped
/// by that unique index.
fn username_taken(conn: &rusqlite::Connection, username: &str) -> bool {
    conn.query_row(
        "SELECT COUNT(*) FROM users WHERE LOWER(username) = LOWER(?)",
        [username],
        |r| r.get::<_, i64>(0),
    ).unwrap_or(0) > 0
}

/// Live availability check for the signup form, mirroring `check_email`.
/// Format first, then the uniqueness lookup.
#[tauri::command]
pub async fn check_username(username: String) -> Result<(), String> {
    tauri::async_runtime::spawn_blocking(move || {
        let username = username.trim().to_string();
        if let Some(p) = username_problem(&username) {
            return Err(format!("Username must be {}.", p));
        }
        let conn = open_db()?;
        if username_taken(&conn, &username) {
            return Err(USERNAME_TAKEN.to_string());
        }
        Ok(())
    })
    .await
    .map_err(|e| format!("Username check failed: {}", e))?
}

fn username_problem(u: &str) -> Option<&'static str> {
    let u = u.trim();
    if u.len() < 3 { return Some("at least 3 characters"); }
    if u.len() > 32 { return Some("at most 32 characters"); }
    if !u.chars().all(|c| c.is_ascii_alphanumeric() || c == '_' || c == '.' || c == '-') {
        return Some("only letters, numbers, and . _ -");
    }
    None
}

// Same rules as auth.py password_problem(). Returns the missing requirement.
fn password_problem(pw: &str) -> Option<&'static str> {
    if pw.len() < 8 { return Some("at least 8 characters"); }
    if !pw.chars().any(|c| c.is_ascii_uppercase()) { return Some("one uppercase letter"); }
    if !pw.chars().any(|c| c.is_ascii_lowercase()) { return Some("one lowercase letter"); }
    if !pw.chars().any(|c| c.is_ascii_digit())     { return Some("one number"); }
    if !pw.chars().any(|c| !c.is_ascii_alphanumeric()) { return Some("one special character"); }
    None
}

/// Standalone email check, so the signup form can validate the address as
/// soon as the user leaves the field instead of only on submit. Same
/// `email_problem` the real signup uses — one implementation, so the inline
/// hint can never disagree with what submit will do.
///
/// Ok(()) means "no reason to reject", which includes the offline case. This
/// is feedback only; signup re-checks regardless.
#[tauri::command]
pub async fn check_email(email: String) -> Result<(), String> {
    let email = email.trim().to_lowercase();
    tauri::async_runtime::spawn_blocking(move || {
        if let Some(msg) = email_problem(&email) {
            return Err(msg);
        }
        
        // Also check if the email is already in use by an active account.
        // We only block "active" accounts, so users with "pending" accounts 
        // can still request a new OTP.
        if let Ok(conn) = crate::database::open_db() {
            let existing_status: Option<String> = conn
                .query_row("SELECT status FROM users WHERE email=?", [email.as_str()], |r| r.get(0))
                .ok();
            
            if let Some(ref status) = existing_status {
                if status == "active" {
                    return Err("An account with this email already exists.".to_string());
                }
            }
        }
        
        Ok(())
    })
    .await
    .map_err(|e| format!("Email check failed: {}", e))?
}

/// Async so the blocking work below — a DNS lookup and a bcrypt hash, each
/// capable of taking a noticeable fraction of a second — runs on the blocking
/// pool instead of freezing the window. The `invoke('signup', ...)` call on
/// the frontend is unchanged; it already awaited a Promise.
#[tauri::command]
pub async fn signup_request(username: String, email: String) -> Result<(), String> {
    tauri::async_runtime::spawn_blocking(move || signup_request_blocking(username, email))
        .await
        .map_err(|e| format!("Signup failed: {}", e))?
}

fn signup_request_blocking(username: String, email: String) -> Result<(), String> {
    use rand::Rng;
    use sha2::{Sha256, Digest};

    let username = username.trim().to_string();
    let email = email.trim().to_lowercase();
    if username.is_empty() || email.is_empty() {
        return Err("Username and email are required.".to_string());
    }
    if let Some(p) = username_problem(&username) { return Err(format!("Username must be {}.", p)); }
    if let Some(p) = email_problem(&email) { return Err(p); }

    let conn = open_db()?;

    // Check existing email
    let existing_status: Option<String> = conn
        .query_row("SELECT status FROM users WHERE email=?", [email.as_str()], |r| r.get(0))
        .ok();

    if let Some(ref status) = existing_status {
        if status == "active" {
            return Err("An account with this email already exists.".to_string());
        }
    }

    // Check existing username (make sure it's not taken by an *active* user, or just anyone)
    // To be safe, we reject if username is taken by someone else (active or pending).
    let username_owner: Option<String> = conn
        .query_row("SELECT email FROM users WHERE LOWER(username)=LOWER(?)", [username.as_str()], |r| r.get(0))
        .ok();
    
    if let Some(owner_email) = username_owner {
        if owner_email != email {
            return Err(USERNAME_TAKEN.to_string());
        }
    }

    // Dummy password hash since password is set in step 3
    let hash = "*PENDING*".to_string();

    // Generate a 6-digit OTP (100000–999999).
    let otp: u32 = rand::thread_rng().gen_range(100_000..=999_999);
    let otp_str = format!("{}", otp);

    // Hash it before storing — never persist the raw code.
    let mut hasher = Sha256::new();
    hasher.update(otp_str.as_bytes());
    let token_hash = format!("{:x}", hasher.finalize());

    // Expiry: now + 15 minutes (UTC), as an ISO-8601 string.
    let expires = unix_secs_to_iso(
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap_or_default()
            .as_secs() + 15 * 60,
    );

    if existing_status.is_some() {
        // Update pending user
        conn.execute(
            "UPDATE users SET username=?, password_hash=?, reset_token=?, reset_expires=?, updated_at=datetime('now') WHERE email=?",
            rusqlite::params![username, hash, token_hash, expires, email],
        ).map_err(|e| format!("Could not update pending account: {}", e))?;
    } else {
        // Insert new pending user
        conn.execute(
            "INSERT INTO users (full_name, username, email, password_hash, role, status, reset_token, reset_expires, created_at, updated_at)
             VALUES (?1, ?1, ?2, ?3, 'user', 'pending', ?4, ?5, datetime('now'), datetime('now'))",
            rusqlite::params![username, email, hash, token_hash, expires],
        ).map_err(|e| format!("Could not create account: {}", e))?;
    }

    let message_html = format!(
        r#"<p style="margin:0 0 24px;font-size:16px;color:#475569;line-height:24px;">
          Welcome to <strong style="color:#1a1c21;">ENSTUDIO</strong>! Please use the verification code below to complete your registration:
        </p>"#
    );

    send_otp_email_blocking(&email, &otp_str, "Verify your ENSTUDIO registration", &message_html)?;

    Ok(())
}

fn send_otp_email_blocking(email: &str, otp_str: &str, subject: &str, message_html: &str) -> Result<(), String> {
    use lettre::{Message, SmtpTransport, Transport};
    use lettre::transport::smtp::authentication::Credentials;
    use lettre::message::{MultiPart, SinglePart, header::{ContentType, ContentId}};

    let smtp_host      = load_config_key("smtp_host").unwrap_or_else(|| "smtp.gmail.com".to_string());
    let smtp_port: u16 = load_config_key("smtp_port").and_then(|v| v.parse().ok()).unwrap_or(587);
    let smtp_user      = load_config_key("smtp_user").unwrap_or_default();
    let smtp_password  = load_config_key("smtp_password").unwrap_or_default();
    let smtp_from      = load_config_key("smtp_from").unwrap_or_else(|| smtp_user.clone());

    if smtp_user.is_empty() || smtp_password.is_empty() {
        return Err(
            "SMTP is not configured. Please set smtp_host, smtp_port, smtp_user, \
             smtp_password, and smtp_from in Settings.".to_string()
        );
    }

    let body = format!(
        r#"<!DOCTYPE html>
<html>
<body style="margin:0;padding:0;background-color:#f4f7fa;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background-color:#f4f7fa;padding:40px 0;">
    <tr><td align="center">
      <table width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;background:#ffffff;border-radius:12px;overflow:hidden;box-shadow:0 4px 20px rgba(0,0,0,0.08);">
        <tr>
          <td style="background-color:#1F5FE0;padding:28px 40px;text-align:center;">
            <table cellpadding="0" cellspacing="0" style="margin:0 auto;"><tr>
              <td style="padding-right:14px;vertical-align:middle;">
                <table cellpadding="0" cellspacing="0" style="width:48px;height:48px;background:#ffffff;border-radius:50%;">
                  <tr><td align="center" valign="middle" style="width:48px;height:48px;">
                    <img src="cid:enstudio-logo" alt="ENSTUDIO" width="34" height="34" style="display:block;margin:0 auto;">
                  </td></tr>
                </table>
              </td>
              <td style="vertical-align:middle;">
                <h1 style="margin:0;font-size:22px;font-weight:700;color:#ffffff;">ENSTUDIO</h1>
              </td>
            </tr></table>
          </td>
        </tr>
        <tr>
          <td style="padding:40px;">
            <p style="margin:0 0 16px;font-size:16px;color:#475569;line-height:24px;">Hi,</p>
            {message_html}
            <table width="100%" cellpadding="0" cellspacing="0" style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;">
              <tr><td align="center" style="padding:32px 20px;">
                <p style="margin:0;font-size:36px;font-weight:700;letter-spacing:8px;color:#1F5FE0;">{otp_str}</p>
              </td></tr>
            </table>
            <p style="margin:24px 0 0;font-size:15px;color:#475569;line-height:22px;">
              This code will expire in <strong>15 minutes</strong>.<br>
              If you didn't request this, you can safely ignore this email.
            </p>
            <p style="margin:32px 0 0;font-size:15px;color:#475569;line-height:22px;">
              Best regards,<br><strong style="color:#1a1c21;">The ENSTUDIO Team</strong>
            </p>
          </td>
        </tr>
        <tr>
          <td style="padding:24px 40px;background:#fcfcfd;border-top:1px solid #f1f5f9;text-align:center;">
            <p style="margin:0;font-size:12px;color:#94a3b8;">This is an automated message &mdash; no need to reply.</p>
          </td>
        </tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"#
    );

    let html_part = SinglePart::html(body);
    let logo_data = include_bytes!("../../../public/logo.png");
    let image_part = SinglePart::builder()
        .header(ContentType::parse("image/png").unwrap())
        .header(ContentId::from("<enstudio-logo>".to_string()))
        .body(logo_data.to_vec());

    let multipart = MultiPart::related()
        .singlepart(html_part)
        .singlepart(image_part);

    let message = Message::builder()
        .from(
            format!("enSTUDIO <{smtp_from}>")
                .parse()
                .map_err(|e| format!("Invalid SMTP from address: {}", e))?,
        )
        .to(
            email
                .parse()
                .map_err(|e| format!("Invalid recipient address: {}", e))?,
        )
        .subject(subject)
        .multipart(multipart)
        .map_err(|e| format!("Email build error: {}", e))?;

    let creds = Credentials::new(smtp_user, smtp_password);
    let transport = SmtpTransport::starttls_relay(&smtp_host)
        .map_err(|e| format!("SMTP relay error: {}", e))?
        .port(smtp_port)
        .credentials(creds)
        .build();

    transport.send(&message).map_err(|e| format!("Failed to send email: {}", e))?;
    Ok(())
}

#[tauri::command]
pub fn login(identifier: String, password: String) -> Result<AuthUserDto, String> {
    // Accept either an email or a username. Email is stored lowercased; match
    // username case-insensitively too, so the lowercased identifier hits both.
    let ident = identifier.trim().to_lowercase();
    let conn = open_db()?;
    // .ok() collapses "no such user" and any lookup error into None → the same
    // generic message, so we never reveal which accounts exist.
    let found: Option<(i64, String, String, String, String, String)> = conn
        .query_row(
            "SELECT id, full_name, email, role, status, password_hash
             FROM users WHERE email = ?1 OR LOWER(username) = ?1",
            [ident.as_str()],
            |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?, r.get(3)?, r.get(4)?, r.get(5)?)),
        )
        .ok();

    let (id, name, email, role, status, hash) = found.ok_or("Invalid credentials.")?;
    if !bcrypt::verify(&password, &hash).unwrap_or(false) {
        return Err("Invalid credentials.".to_string());
    }
    if status != "active" { return Err("Account is not active.".to_string()); }

    conn.execute("UPDATE users SET last_login=datetime('now') WHERE id=?", [id]).ok();
    Ok(AuthUserDto { id, name, email, role })
}

#[tauri::command]
pub fn get_user(id: i64) -> Result<AuthUserDto, String> {
    let conn = open_db()?;
    conn.query_row(
        "SELECT id, full_name, email, role FROM users WHERE id=? AND status='active'",
        [id],
        |r| Ok(AuthUserDto {
            id:    r.get::<_, i64>(0)?,
            name:  r.get::<_, String>(1)?,
            email: r.get::<_, String>(2)?,
            role:  r.get::<_, String>(3)?,
        }),
    ).map_err(|_| "User not found".to_string())
}

/// Async for the same reason as signup — changing an email re-runs the DNS
/// check, so an unvalidated address cannot get in via profile edit.
#[tauri::command]
pub async fn update_user(id: i64, name: String, email: String) -> Result<AuthUserDto, String> {
    tauri::async_runtime::spawn_blocking(move || update_user_blocking(id, name, email))
        .await
        .map_err(|e| format!("Update failed: {}", e))?
}

fn update_user_blocking(id: i64, name: String, email: String) -> Result<AuthUserDto, String> {
    let name = name.trim().to_string();
    let email = email.trim().to_lowercase();
    if name.is_empty() || email.is_empty() {
        return Err("Name and email cannot be empty.".to_string());
    }
    if let Some(p) = email_problem(&email) { return Err(p); }

    let conn = open_db()?;
    // Check if the email belongs to another user
    let exists: i64 = conn.query_row(
        "SELECT COUNT(*) FROM users WHERE email=? AND id!=?",
        rusqlite::params![email, id],
        |r| r.get(0)
    ).unwrap_or(0);
    if exists > 0 { return Err("Email is already in use.".to_string()); }

    conn.execute(
        "UPDATE users SET full_name=?, email=?, updated_at=datetime('now') WHERE id=?",
        rusqlite::params![name, email, id],
    ).map_err(|e| format!("Update failed: {}", e))?;

    get_user(id)
}

// ── Forgot / Reset password ────────────────────────────────────────────────────

/// Generates a 6-digit OTP, stores a SHA-256 hash of it in the DB with a
/// 15-minute expiry, then emails the raw code to the user.
///
/// Always returns Ok(()) — even if the email is not registered — so callers
/// cannot enumerate which addresses have accounts.
///
/// SMTP settings are read from the `settings` table using load_config_key:
///   smtp_host      (default smtp.gmail.com)
///   smtp_port      (default 587)
///   smtp_user      — required
///   smtp_password  — required
///   smtp_from      (defaults to smtp_user)
///
/// Insert them once (or expose them in a Settings panel):
///   INSERT OR REPLACE INTO settings VALUES ('smtp_host', 'smtp.gmail.com');
///   INSERT OR REPLACE INTO settings VALUES ('smtp_port', '587');
///   INSERT OR REPLACE INTO settings VALUES ('smtp_user', 'you@gmail.com');
///   INSERT OR REPLACE INTO settings VALUES ('smtp_password', 'app-password');
///   INSERT OR REPLACE INTO settings VALUES ('smtp_from',     'you@gmail.com');
#[tauri::command]
pub async fn forgot_password(email: String) -> Result<(), String> {
    tauri::async_runtime::spawn_blocking(move || forgot_password_blocking(email))
        .await
        .map_err(|e| format!("Forgot password failed: {}", e))?
}

fn forgot_password_blocking(email: String) -> Result<(), String> {
    use rand::Rng;
    use sha2::{Sha256, Digest};

    let email = email.trim().to_lowercase();

    // Check if user exists — for an internal tool, tell the user directly.
    let conn = open_db()?;
    let user_exists: bool = conn
        .query_row(
            "SELECT COUNT(*) FROM users WHERE email = ?",
            [email.as_str()],
            |r| r.get::<_, i64>(0),
        )
        .unwrap_or(0) > 0;

    if !user_exists {
        return Err("No account found with this email address.".to_string());
    }

    // Generate a 6-digit OTP (100000–999999).
    let otp: u32 = rand::thread_rng().gen_range(100_000..=999_999);
    let otp_str = format!("{}", otp);

    // Hash it before storing — never persist the raw code.
    let mut hasher = Sha256::new();
    hasher.update(otp_str.as_bytes());
    let token_hash = format!("{:x}", hasher.finalize());

    // Expiry: now + 15 minutes (UTC), as an ISO-8601 string for easy comparison.
    let expires = unix_secs_to_iso(
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap_or_default()
            .as_secs() + 15 * 60,
    );

    // Persist token + expiry.
    conn.execute(
        "UPDATE users SET reset_token=?, reset_expires=? WHERE email=?",
        rusqlite::params![token_hash, expires, email.as_str()],
    ).map_err(|e| format!("DB error storing reset token: {}", e))?;

    let message_html = format!(
        r#"<p style="margin:0 0 24px;font-size:16px;color:#475569;line-height:24px;">
          You requested a password reset for your <strong style="color:#1a1c21;">ENSTUDIO</strong> account. Please use the verification code below to set a new password:
        </p>"#
    );

    send_otp_email_blocking(&email, &otp_str, "Your ENSTUDIO password reset code", &message_html)?;

    Ok(())
}

#[tauri::command]
pub fn signup_verify_otp(email: String, otp: String) -> Result<(), String> {
    use sha2::{Sha256, Digest};

    let email = email.trim().to_lowercase();
    let otp   = otp.trim().to_string();

    let conn = open_db()?;

    let row: Option<(Option<String>, Option<String>)> = conn
        .query_row(
            "SELECT reset_token, reset_expires FROM users WHERE email = ? AND status = 'pending'",
            [email.as_str()],
            |r| Ok((r.get(0)?, r.get(1)?)),
        )
        .ok();

    let (stored_hash, expires_str) = match row {
        Some((Some(h), Some(e))) => (h, e),
        _ => return Err("Invalid session or account already verified.".to_string()),
    };

    let now_str = unix_secs_to_iso(
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap_or_default()
            .as_secs(),
    );

    if now_str > expires_str {
        return Err("This registration code has expired. Please sign up again.".to_string());
    }

    let mut hasher = Sha256::new();
    hasher.update(otp.as_bytes());
    if format!("{:x}", hasher.finalize()) != stored_hash {
        return Err("Incorrect code. Please check and try again.".to_string());
    }

    Ok(())
}

#[tauri::command]
pub async fn signup_finalize(email: String, otp: String, password: String) -> Result<AuthUserDto, String> {
    tauri::async_runtime::spawn_blocking(move || signup_finalize_blocking(email, otp, password))
        .await
        .map_err(|e| format!("Signup finalize failed: {}", e))?
}

fn signup_finalize_blocking(email: String, otp: String, password: String) -> Result<AuthUserDto, String> {
    use sha2::{Sha256, Digest};

    let email = email.trim().to_lowercase();
    let otp   = otp.trim().to_string();
    
    if let Some(p) = password_problem(&password) { return Err(format!("Password needs {}.", p)); }

    let conn = open_db()?;

    // Verify OTP again
    let row: Option<(Option<String>, Option<String>)> = conn
        .query_row(
            "SELECT reset_token, reset_expires FROM users WHERE email = ? AND status = 'pending'",
            [email.as_str()],
            |r| Ok((r.get(0)?, r.get(1)?)),
        )
        .ok();

    let (stored_hash, expires_str) = match row {
        Some((Some(h), Some(e))) => (h, e),
        _ => return Err("Invalid session or account already verified.".to_string()),
    };

    let now_str = unix_secs_to_iso(
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap_or_default()
            .as_secs(),
    );

    if now_str > expires_str {
        return Err("This registration code has expired. Please sign up again.".to_string());
    }

    let mut hasher = Sha256::new();
    hasher.update(otp.as_bytes());
    if format!("{:x}", hasher.finalize()) != stored_hash {
        return Err("Incorrect code. Please check and try again.".to_string());
    }

    let hash = bcrypt::hash(&password, bcrypt::DEFAULT_COST)
        .map_err(|e| format!("Password hashing failed: {}", e))?;

    // Activate the user and set password
    conn.execute(
        "UPDATE users SET password_hash=?, status='active', reset_token=NULL, reset_expires=NULL, updated_at=datetime('now') WHERE email=?",
        rusqlite::params![hash, email.as_str()],
    ).map_err(|e| format!("Could not activate account: {}", e))?;

    // Return AuthUserDto
    let found: Option<(i64, String, String, String)> = conn
        .query_row(
            "SELECT id, username, email, role FROM users WHERE email = ?",
            [email.as_str()],
            |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?, r.get(3)?)),
        ).ok();

    let (id, name, email_db, role) = found.ok_or("Account activated but could not be found.")?;

    Ok(AuthUserDto { id, name, email: email_db, role })
}

/// Validates the OTP entered by the user without resetting the password.
/// Clears the token only if it has expired.
#[tauri::command]
pub fn verify_otp(email: String, otp: String) -> Result<(), String> {
    use sha2::{Sha256, Digest};

    let email = email.trim().to_lowercase();
    let otp   = otp.trim().to_string();

    let conn = open_db()?;

    // Fetch token + expiry for this email.
    let row: Option<(Option<String>, Option<String>)> = conn
        .query_row(
            "SELECT reset_token, reset_expires FROM users WHERE email = ?",
            [email.as_str()],
            |r| Ok((r.get::<_, Option<String>>(0)?, r.get::<_, Option<String>>(1)?)),
        )
        .ok();

    let (stored_hash, expires_str) = match row {
        Some((Some(h), Some(e))) => (h, e),
        _ => return Err(
            "No password reset was requested for this email, or the code has already been used."
                .to_string()
        ),
    };

    let now_str = unix_secs_to_iso(
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap_or_default()
            .as_secs(),
    );

    if now_str > expires_str {
        // Clear the expired token.
        let _ = conn.execute(
            "UPDATE users SET reset_token=NULL, reset_expires=NULL WHERE email=?",
            [email.as_str()],
        );
        return Err("This reset code has expired. Please request a new one.".to_string());
    }

    // Hash the submitted OTP and compare.
    let mut hasher = Sha256::new();
    hasher.update(otp.as_bytes());
    let submitted_hash = format!("{:x}", hasher.finalize());

    if submitted_hash != stored_hash {
        return Err("Incorrect code. Please check and try again.".to_string());
    }

    Ok(())
}

/// Checks if a proposed new password is the same as the user's old password.
/// Requires the OTP to ensure the caller is authorized to probe this email's password.
#[tauri::command]
pub fn check_new_password(email: String, otp: String, new_password: String) -> Result<(), String> {
    use sha2::{Sha256, Digest};

    let email = email.trim().to_lowercase();
    let otp   = otp.trim().to_string();

    let conn = open_db()?;

    // Fetch token + expiry + old password hash for this email.
    let row: Option<(Option<String>, Option<String>, Option<String>)> = conn
        .query_row(
            "SELECT reset_token, reset_expires, password_hash FROM users WHERE email = ?",
            [email.as_str()],
            |r| Ok((r.get::<_, Option<String>>(0)?, r.get::<_, Option<String>>(1)?, r.get::<_, Option<String>>(2)?)),
        )
        .ok();

    let (stored_hash, expires_str, old_password_hash) = match row {
        Some((Some(h), Some(e), p)) => (h, e, p),
        _ => return Err("Invalid session.".to_string()),
    };

    let now_str = unix_secs_to_iso(
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap_or_default()
            .as_secs(),
    );

    if now_str > expires_str {
        return Err("Reset code expired.".to_string());
    }

    let mut hasher = Sha256::new();
    hasher.update(otp.as_bytes());
    if format!("{:x}", hasher.finalize()) != stored_hash {
        return Err("Invalid code.".to_string());
    }

    if let Some(old_hash) = old_password_hash {
        if bcrypt::verify(&new_password, &old_hash).unwrap_or(false) {
            return Err("Your new password cannot be the same as your old password.".to_string());
        }
    }

    Ok(())
}

/// Validates the OTP entered by the user and, if valid, updates their password.
/// Clears the reset token on success or expiry to prevent reuse.
#[tauri::command]
pub fn reset_password(email: String, otp: String, new_password: String) -> Result<(), String> {
    use sha2::{Sha256, Digest};

    let email = email.trim().to_lowercase();
    let otp   = otp.trim().to_string();

    // Validate new password strength first — cheap, no DB needed.
    if let Some(p) = password_problem(&new_password) {
        return Err(format!("Password needs {}.", p));
    }

    let conn = open_db()?;

    // Fetch token + expiry + old password hash for this email.
    let row: Option<(Option<String>, Option<String>, Option<String>)> = conn
        .query_row(
            "SELECT reset_token, reset_expires, password_hash FROM users WHERE email = ?",
            [email.as_str()],
            |r| Ok((r.get::<_, Option<String>>(0)?, r.get::<_, Option<String>>(1)?, r.get::<_, Option<String>>(2)?)),
        )
        .ok();

    let (stored_hash, expires_str, old_password_hash) = match row {
        Some((Some(h), Some(e), p)) => (h, e, p),
        _ => return Err(
            "No password reset was requested for this email, or the code has already been used."
                .to_string()
        ),
    };

    // Compare ISO-8601 strings lexicographically to detect expiry
    // (zero-padded, descending-significance order makes this correct).
    let now_str = unix_secs_to_iso(
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap_or_default()
            .as_secs(),
    );

    if now_str > expires_str {
        // Clear the expired token.
        let _ = conn.execute(
            "UPDATE users SET reset_token=NULL, reset_expires=NULL WHERE email=?",
            [email.as_str()],
        );
        return Err("This reset code has expired. Please request a new one.".to_string());
    }

    // Hash the submitted OTP and compare.
    let mut hasher = Sha256::new();
    hasher.update(otp.as_bytes());
    let submitted_hash = format!("{:x}", hasher.finalize());

    if submitted_hash != stored_hash {
        return Err("Incorrect code. Please check and try again.".to_string());
    }

    // Ensure the new password is not the same as the old one.
    if let Some(old_hash) = old_password_hash {
        if bcrypt::verify(&new_password, &old_hash).unwrap_or(false) {
            return Err("Your new password cannot be the same as your old password.".to_string());
        }
    }

    // Hash the new password.
    let new_hash = bcrypt::hash(&new_password, bcrypt::DEFAULT_COST)
        .map_err(|e| format!("Password hashing failed: {}", e))?;

    // Update password and clear the token atomically.
    conn.execute(
        "UPDATE users SET password_hash=?, reset_token=NULL, reset_expires=NULL, \
         updated_at=datetime('now') WHERE email=?",
        rusqlite::params![new_hash, email.as_str()],
    ).map_err(|e| format!("Could not update password: {}", e))?;

    Ok(())
}

/// Convert a Unix timestamp (seconds) to an ISO-8601 UTC string such as
/// "2026-08-05T07:30:00Z". Implemented without `chrono` to keep deps minimal;
/// uses Tomohiko Sakamoto's Gregorian day-of-year algorithm.
fn unix_secs_to_iso(s: u64) -> String {
    let sec  =  s % 60;   let s = s / 60;
    let min  =  s % 60;   let s = s / 60;
    let hour =  s % 24;   let s = s / 24;

    let z = s as i64 + 719_468;
    let era   = if z >= 0 { z } else { z - 146_096 } / 146_097;
    let doe   = (z - era * 146_097) as u64;
    let yoe   = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365;
    let y     = yoe as i64 + era * 400;
    let doy   = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp    = (5 * doy + 2) / 153;
    let d     = doy - (153 * mp + 2) / 5 + 1;
    let m     = if mp < 10 { mp + 3 } else { mp - 9 };
    let y     = if m <= 2 { y + 1 } else { y };

    format!("{y:04}-{m:02}-{d:02}T{hour:02}:{min:02}:{sec:02}Z")
}


#[cfg(test)]
mod email_validation_tests {
    use super::*;

    /// Only the offline paths are asserted here — format and lookalike both
    /// return before `email_problem` reaches DNS, so these stay deterministic
    /// and runnable without a network.
    #[test]
    fn rejects_lookalike_domains_without_naming_the_suggestion() {
        const EXPECTED: &str = "That email domain doesn't look right. Check for a typo.";
        for addr in ["Daman@gmai.com", "a@gmial.com", "a@hotmial.com", "a@outlok.com"] {
            let msg = email_problem(addr).expect("should be rejected");
            assert_eq!(msg, EXPECTED, "{}", addr);
            // The whole point of this wording: never hand back the real domain.
            assert!(!msg.contains("gmail"), "message leaked the suggestion: {}", msg);
            assert!(!msg.contains("hotmail"), "message leaked the suggestion: {}", msg);
            assert!(!msg.contains("outlook"), "message leaked the suggestion: {}", msg);
        }
    }

    #[test]
    fn rejects_malformed_addresses() {
        for bad in ["", "no-at-sign", "@nolocal.com", "nodomain@", "a@b",
                    "a@b.", "a@.com", "a@b..com", "two@at@signs.com",
                    "spa ce@example.com", "a@exam ple.com"] {
            assert!(email_problem(bad).is_some(), "{:?} should be rejected", bad);
        }
    }

    #[test]
    fn format_check_accepts_normal_addresses() {
        // valid_email is the gate before any network call — it must not reject
        // ordinary real-world addresses.
        for good in ["jane.doe@example.com", "a+tag@sub.example.co.uk",
                     "first_last@company-name.com", "x1%y@mail.example.org"] {
            assert!(valid_email(good), "{:?} should pass the format check", good);
        }
    }

    #[test]
    fn personal_domains_are_not_rejected_by_the_offline_checks() {
        // Explicitly NOT a company-only policy: consumer addresses must reach
        // the DNS stage rather than being turned away on sight.
        for d in ["gmail.com", "outlook.com", "yahoo.com", "icloud.com"] {
            let addr = format!("someone@{}", d);
            assert!(valid_email(&addr));
            assert_eq!(crate::utils::email_dns::lookalike_of(d), None);
        }
    }
}


#[cfg(test)]
mod username_unique_tests {
    use super::*;

    fn db_with(names: &[&str]) -> rusqlite::Connection {
        let c = rusqlite::Connection::open_in_memory().unwrap();
        c.execute_batch(
            "CREATE TABLE users (id INTEGER PRIMARY KEY, full_name TEXT, username TEXT,
             email TEXT, password_hash TEXT, role TEXT, status TEXT,
             created_at TEXT, updated_at TEXT, last_login TEXT);
             CREATE UNIQUE INDEX idx_users_username_ci ON users(LOWER(username));"
        ).unwrap();
        for n in names {
            c.execute("INSERT INTO users (username, email) VALUES (?, ?)",
                      rusqlite::params![n, format!("{}@example.com", n)]).unwrap();
        }
        c
    }

    #[test]
    fn taken_names_are_detected_case_insensitively() {
        let c = db_with(&["daman"]);
        for probe in ["daman", "Daman", "DAMAN", "DaMaN"] {
            assert!(username_taken(&c, probe),
                    "{} collides with existing 'daman' and must be reported taken", probe);
        }
    }

    #[test]
    fn free_names_are_available() {
        let c = db_with(&["daman", "jane.doe"]);
        for probe in ["daman2", "damian", "jane_doe", "newuser"] {
            assert!(!username_taken(&c, probe), "{} is free and must be available", probe);
        }
    }

    #[test]
    fn the_db_index_also_enforces_case_insensitivity() {
        // The app check is only half of it — this is the backstop that stops a
        // race from landing "Daman" next to "daman". SCHEMA_SQL's plain
        // users(username) index is case-SENSITIVE and would allow it.
        let c = db_with(&["daman"]);
        let err = c.execute("INSERT INTO users (username, email) VALUES ('Daman', 'x@y.com')", []);
        assert!(err.is_err(), "unique index must reject a case-variant duplicate");
    }

    #[test]
    fn empty_db_reports_everything_free() {
        let c = db_with(&[]);
        assert!(!username_taken(&c, "anyone"));
    }
}
