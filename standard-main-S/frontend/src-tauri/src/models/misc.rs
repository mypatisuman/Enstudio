use serde::Serialize;

#[derive(Serialize)]
pub struct PageImageResult {
    pub url: String,
    pub width: u32,
    pub height: u32,
}
