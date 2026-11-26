use serde::Serialize;

/// Shared `{ "success": true }` shape used by several write commands across
/// domains (project delete, review updates, connection edits) that don't
/// return any other data on success.
#[derive(Serialize)]
pub struct SuccessResponse {
    pub success: bool,
}
