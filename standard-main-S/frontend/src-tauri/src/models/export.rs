use serde::Serialize;

#[derive(Serialize)]
pub struct ExportFileResult {
    pub success: bool,
    pub filename: String,
    pub path: String,
}
