//! Validation for the domain part of an email address at signup. Two
//! independent checks, because neither alone is enough:
//!
//!   * `lookalike_of`     — offline typo detection against well-known
//!                          providers. Catches `gmai.com`, which DNS cannot.
//!   * `check_mail_domain` — MX lookup. Catches domains that do not exist,
//!                          and parked domains that cannot receive mail.
//!
//! WHAT THIS PROVES, AND WHAT IT DOES NOT
//! --------------------------------------
//! An MX lookup proves the *domain* is real and accepts mail — it rejects
//! invented domains (`asdfgh.com`). It does NOT reject registered typosquats:
//! `gmai.com` is a real domain with real MX records, so DNS calls it
//! deliverable and is right to. That is why the lookalike check exists.
//!
//! Neither check proves a *mailbox* exists: `nobody@gmail.com` passes, because
//! gmail.com has MX records. Proving a mailbox exists requires sending a
//! confirmation email. SMTP RCPT-TO probing is not a substitute — catch-all
//! domains accept every address, port 25 is usually blocked outbound, and
//! probing gets IPs blacklisted.
//!
//! Personal/consumer addresses are ACCEPTED throughout.
//!
//! Uses the Windows resolver (DnsQuery_W in dnsapi.dll) via FFI rather than a
//! DNS crate: no new dependency, and it reuses the OS resolver cache, so a
//! repeat signup on a known domain answers instantly.

/// Outcome of the lookup. The two "definitive" variants are the only ones
/// that may block a signup — see `rejection_reason`.
#[derive(Debug, PartialEq, Eq, Clone, Copy)]
pub enum MailDomain {
    /// Publishes MX records — something is there to receive mail.
    Deliverable,
    /// Authoritative NXDOMAIN — the domain does not exist.
    NoSuchDomain,
    /// Domain resolves but publishes no MX — nothing can deliver mail to it.
    /// The signature of a parked typosquat.
    NoMailRecords,
    /// No usable answer: offline, DNS server down, timeout. NOT a rejection.
    Undetermined,
}

impl MailDomain {
    /// The user-facing error, or None if signup should proceed.
    ///
    /// `Undetermined` deliberately returns None — failing closed would make
    /// the app unusable offline, and this check is a typo guard, not a
    /// security control. Nothing downstream trusts the email address.
    pub fn rejection_reason(self) -> Option<&'static str> {
        match self {
            MailDomain::NoSuchDomain =>
                Some("That email domain doesn't exist. Check for a typo."),
            MailDomain::NoMailRecords =>
                Some("That domain can't receive email. Check the address."),
            MailDomain::Deliverable | MailDomain::Undetermined => None,
        }
    }
}

/// The domain part of an email, lowercased. None if there isn't exactly one
/// '@' with text on both sides.
pub fn domain_of(email: &str) -> Option<String> {
    let (local, domain) = email.trim().rsplit_once('@')?;
    if local.is_empty() || domain.is_empty() { return None; }
    Some(domain.to_lowercase())
}

// ── Lookalike-domain detection ──────────────────────────────────────────────
//
// WHY THIS EXISTS, ON TOP OF THE MX CHECK
// `gmai.com` is a REAL registered domain with REAL MX records — a typosquat
// of gmail.com. Every DNS-based check on earth says it is deliverable,
// because it is. Only comparing it against the address the user plainly meant
// can catch it, so that is what this does.
//
// Personal/consumer providers are ACCEPTED here. This list is not a blocklist
// — it is the set of well-known domains a typo is measured against.
const KNOWN_DOMAINS: &[&str] = &[
    // Consumer providers — accepted, listed so typos of them are caught.
    "gmail.com", "googlemail.com", "yahoo.com", "yahoo.co.uk", "yahoo.co.in",
    "outlook.com", "hotmail.com", "hotmail.co.uk", "live.com", "live.co.uk",
    "msn.com", "icloud.com", "me.com", "mac.com", "aol.com",
    "protonmail.com", "proton.me", "zoho.com", "gmx.com", "gmx.net",
    "mail.com", "mail.ru", "yandex.com", "yandex.ru", "rediffmail.com",
    "qq.com", "163.com", "126.com", "naver.com", "daum.net",
    // Exact matches never get flagged, so near-miss real domains listed here
    // are protected from a false "did you mean" (gmx.net vs gmx.com etc).
];

/// True when `a` and `b` differ by exactly one edit: an insertion, a deletion,
/// a substitution, or a swap of two adjacent characters.
///
/// Only distance-1 is treated as a typo. Distance-2 would catch a few more
/// mistakes but starts flagging genuinely unrelated domains, and a false
/// positive here blocks a real person from signing up — much worse than
/// letting one typo through.
fn is_one_edit_apart(a: &str, b: &str) -> bool {
    let (a, b): (Vec<char>, Vec<char>) = (a.chars().collect(), b.chars().collect());
    let (la, lb) = (a.len(), b.len());
    if la.abs_diff(lb) > 1 { return false; }

    if la == lb {
        let diffs: Vec<usize> = (0..la).filter(|&i| a[i] != b[i]).collect();
        return match diffs.len() {
            1 => true,                                  // substitution
            2 => {                                      // adjacent transposition
                let (i, j) = (diffs[0], diffs[1]);
                j == i + 1 && a[i] == b[j] && a[j] == b[i]
            }
            _ => false,                                 // 0 = identical, >2 = far apart
        };
    }

    // Lengths differ by one: the longer must equal the shorter plus one char.
    let (short, long) = if la < lb { (&a, &b) } else { (&b, &a) };
    let (mut i, mut j, mut skipped) = (0usize, 0usize, false);
    while i < short.len() && j < long.len() {
        if short[i] == long[j] { i += 1; j += 1; continue; }
        if skipped { return false; }
        skipped = true;
        j += 1;                                         // consume the extra char
    }
    true
}

/// If `domain` is one typo away from a well-known provider, return that
/// provider so the user can be told what they probably meant.
///
/// An exact match returns None — real consumer addresses are accepted.
pub fn lookalike_of(domain: &str) -> Option<&'static str> {
    if KNOWN_DOMAINS.contains(&domain) { return None; }
    KNOWN_DOMAINS.iter().copied().find(|known| is_one_edit_apart(domain, known))
}

#[cfg(windows)]
mod win_dns {
    // DnsQuery_W record type. Only MX is queried — see check_mail_domain.
    pub const DNS_TYPE_MX: u16 = 0x000f;

    // DNS_QUERY_STANDARD — use the OS resolver cache.
    const QUERY_STANDARD: u32 = 0x0;
    // DnsFreeRecordList
    const FREE_RECORD_LIST: u32 = 1;

    // Windows DNS status codes we branch on. Anything else is transient.
    pub const ERROR_SUCCESS: i32 = 0;
    pub const DNS_ERROR_RCODE_NAME_ERROR: i32 = 9003; // NXDOMAIN, authoritative
    pub const DNS_INFO_NO_RECORDS: i32 = 9501;        // domain exists, no such record type

    #[link(name = "dnsapi")]
    extern "system" {
        fn DnsQuery_W(
            name: *const u16,
            wtype: u16,
            options: u32,
            extra: *mut core::ffi::c_void,
            results: *mut *mut core::ffi::c_void,
            reserved: *mut core::ffi::c_void,
        ) -> i32;
        fn DnsRecordListFree(list: *mut core::ffi::c_void, free_type: u32);
    }

    /// Run one DNS query. Returns the status code and whether any record came
    /// back. The record payload itself is never parsed — presence is all we
    /// need — but the list must still be freed or it leaks.
    pub fn query(domain: &str, rtype: u16) -> (i32, bool) {
        let wide: Vec<u16> = domain.encode_utf16().chain(std::iter::once(0)).collect();
        let mut results: *mut core::ffi::c_void = std::ptr::null_mut();
        let status = unsafe {
            DnsQuery_W(wide.as_ptr(), rtype, QUERY_STANDARD,
                       std::ptr::null_mut(), &mut results, std::ptr::null_mut())
        };
        let got_records = !results.is_null();
        if got_records {
            unsafe { DnsRecordListFree(results, FREE_RECORD_LIST) };
        }
        (status, got_records)
    }
}

/// Look up whether `domain` can receive mail. Blocking — call it off the UI
/// thread (see `signup`, which uses spawn_blocking).
#[cfg(windows)]
pub fn check_mail_domain(domain: &str) -> MailDomain {
    use win_dns::*;

    // Guard the FFI against inputs the resolver would choke on. A bare label
    // with no dot ("localhost", "gmail") is never a public mail domain.
    if domain.is_empty() || domain.len() > 253 || !domain.contains('.') {
        return MailDomain::NoSuchDomain;
    }

    let (status, has_mx) = query(domain, DNS_TYPE_MX);
    match (status, has_mx) {
        // A real mail domain publishes MX. This is the only accept path.
        (ERROR_SUCCESS, true) => MailDomain::Deliverable,

        // Authoritative "this name does not exist".
        (DNS_ERROR_RCODE_NAME_ERROR, _) => MailDomain::NoSuchDomain,

        // The name resolves but publishes no MX, so nothing can deliver mail
        // to it. This is what a parked typosquat looks like: a web server for
        // the parking page (A record) and no mail server at all. Measured on
        // amazn.com / microsft.com / facebok.com / siemenss.com, all of which
        // used to slip through the old A-record fallback.
        //
        // That fallback implemented RFC 5321 §5.1, which lets a bare A record
        // stand in as a mail destination. Dropped deliberately: every real
        // company domain sampled (siemens, honeywell, emerson, yokogawa,
        // shell, bp, adnoc, reliance, anthropic) publishes MX, so the rule
        // costs nothing real and catches a whole class of typos. The tradeoff
        // is a self-hosted A-only mail domain would now be rejected — rare
        // enough to be worth it, but that is the reason if one ever is.
        (DNS_INFO_NO_RECORDS, _) | (ERROR_SUCCESS, false) => MailDomain::NoMailRecords,

        // SERVFAIL, no DNS servers configured, timeout, offline — not the
        // user's fault, so do not block them.
        _ => MailDomain::Undetermined,
    }
}

/// Non-Windows has no DnsQuery_W. Rather than pull in a resolver crate for a
/// platform the app does not currently ship on, skip the check — the format
/// validation in auth.rs still applies.
#[cfg(not(windows))]
pub fn check_mail_domain(_domain: &str) -> MailDomain {
    MailDomain::Undetermined
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn extracts_domain() {
        assert_eq!(domain_of("Jane.Doe@Example.COM").as_deref(), Some("example.com"));
        // '+' tags and dots in the local part must not confuse the split.
        assert_eq!(domain_of("a.b+tag@sub.example.co.uk").as_deref(), Some("sub.example.co.uk"));
        // rsplit_once means the LAST '@' delimits, matching real parsing.
        assert_eq!(domain_of("weird@name@example.com").as_deref(), Some("example.com"));
        assert_eq!(domain_of("no-at-sign"), None);
        assert_eq!(domain_of("@nolocal.com"), None);
        assert_eq!(domain_of("nodomain@"), None);
    }

    #[test]
    fn catches_the_typos_dns_cannot() {
        // The screenshot case. gmai.com is a REAL domain with REAL MX records,
        // so every DNS check accepts it — only this catches it.
        assert_eq!(lookalike_of("gmai.com"), Some("gmail.com"));   // dropped letter
        assert_eq!(lookalike_of("gmial.com"), Some("gmail.com"));  // transposition
        assert_eq!(lookalike_of("gmaill.com"), Some("gmail.com")); // doubled letter
        assert_eq!(lookalike_of("gmail.co"), Some("gmail.com"));   // clipped TLD
        assert_eq!(lookalike_of("hotmial.com"), Some("hotmail.com"));
        assert_eq!(lookalike_of("outlok.com"), Some("outlook.com"));
        assert_eq!(lookalike_of("yahooo.com"), Some("yahoo.com"));
    }

    #[test]
    fn personal_addresses_are_accepted_not_flagged() {
        // The known list is a typo yardstick, NOT a blocklist — consumer
        // providers must pass cleanly.
        for d in ["gmail.com", "outlook.com", "yahoo.com", "icloud.com",
                  "protonmail.com", "hotmail.com", "aol.com"] {
            assert_eq!(lookalike_of(d), None, "{} must be accepted", d);
        }
    }

    #[test]
    fn does_not_flag_unrelated_or_near_miss_real_domains() {
        // False positives are the real hazard: flagging one of these would
        // lock a genuine user out of signing up.
        for d in ["anthropic.com", "enxplant.com", "siemens.com", "bp.com",
                  "shell.com", "reliance.com", "adnoc.ae", "company.co.uk",
                  // Real providers deliberately listed as known so they are
                  // exact matches rather than "did you mean" false hits.
                  "gmx.net", "mail.ru", "yandex.ru", "live.co.uk", "me.com"] {
            assert_eq!(lookalike_of(d), None, "{} must NOT be flagged", d);
        }
    }

    #[test]
    fn one_edit_apart_rejects_two_or_more_edits() {
        assert!(is_one_edit_apart("gmai.com", "gmail.com"));
        assert!(!is_one_edit_apart("gmail.com", "gmail.com"));   // identical, not a typo
        assert!(!is_one_edit_apart("gmx.com", "gmail.com"));     // far apart
        assert!(!is_one_edit_apart("hotmail.com", "gmail.com"));
    }

    #[test]
    fn only_definitive_failures_block_signup() {
        // The important policy assertion: a DNS outage must never lock a user
        // out of signing up.
        assert!(MailDomain::Undetermined.rejection_reason().is_none());
        assert!(MailDomain::Deliverable.rejection_reason().is_none());
        assert!(MailDomain::NoSuchDomain.rejection_reason().is_some());
        assert!(MailDomain::NoMailRecords.rejection_reason().is_some());
    }

    #[cfg(windows)]
    #[test]
    fn malformed_domains_rejected_without_touching_the_resolver() {
        assert_eq!(check_mail_domain(""), MailDomain::NoSuchDomain);
        assert_eq!(check_mail_domain("localhost"), MailDomain::NoSuchDomain);
        assert_eq!(check_mail_domain(&"a".repeat(300)), MailDomain::NoSuchDomain);
    }

    /// Live DNS. Skipped unless ENSTUDIO_DNS_TEST=1 so the normal test run
    /// stays offline and deterministic.
    #[cfg(windows)]
    #[test]
    fn live_lookup_separates_real_domains_from_typos() {
        if std::env::var("ENSTUDIO_DNS_TEST").is_err() { return; }

        // Real mail domains — consumer AND company. Requiring MX must not
        // reject any of these; if it ever does, the MX-only rule is wrong.
        for d in ["gmail.com", "outlook.com", "siemens.com", "honeywell.com",
                  "emerson.com", "yokogawa.com", "shell.com", "bp.com",
                  "adnoc.ae", "reliance.com", "anthropic.com"] {
            assert_eq!(check_mail_domain(d), MailDomain::Deliverable,
                       "{} is a real mail domain and must be accepted", d);
        }

        // Parked typosquats: a web server, no mail server. These are exactly
        // what the dropped A-record fallback used to let through.
        for d in ["amazn.com", "microsft.com", "facebok.com", "siemenss.com"] {
            assert_eq!(check_mail_domain(d), MailDomain::NoMailRecords,
                       "{} publishes no MX and must be rejected", d);
        }

        // Reserved by RFC 2606 for exactly this: guaranteed never to resolve.
        assert_eq!(check_mail_domain("nonexistent.invalid"), MailDomain::NoSuchDomain);
    }
}



