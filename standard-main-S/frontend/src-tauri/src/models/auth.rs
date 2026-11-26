use serde::Serialize;

/// The user shape returned by signup/login/get_user/update_user — all four
/// commands already return exactly this via ad-hoc `json!()`; this just
/// gives it a name and compile-time field checking.
#[derive(Serialize)]
pub struct AuthUserDto {
    pub id: i64,
    pub name: String,
    pub email: String,
    pub role: String,
}
