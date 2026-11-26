use serde::Serialize;

#[derive(Serialize)]
pub struct NodeKinds {
    pub instruments: Vec<String>,
    pub equipment: Vec<String>,
}

#[derive(Serialize)]
pub struct InstrumentDto {
    pub tag: String,
    pub r#type: String,
    pub kind_detail: String,
    pub area: String,
    pub equipment_ref: String,
    pub drawing: String,
    pub description: String,
    pub confidence: f64,
    pub review_status: String,
}

#[derive(Serialize)]
pub struct EquipmentDto {
    pub tag: String,
    pub r#type: String,
    pub kind_detail: String,
    pub area: String,
    pub drawing: String,
    pub description: String,
}

/// Shared by the `orphans` and `lonely_equipment` gap categories — both use
/// exactly {tag, type, kind_detail, area, drawing}.
#[derive(Serialize)]
pub struct GapRowDto {
    pub tag: String,
    pub r#type: String,
    pub kind_detail: String,
    pub area: String,
    pub drawing: String,
}

#[derive(Serialize)]
pub struct NoDrawingRowDto {
    pub tag: String,
    pub r#type: String,
    pub kind_detail: String,
    pub area: String,
    pub equipment_ref: String,
}

#[derive(Serialize)]
pub struct LowConfidenceRowDto {
    pub tag: String,
    pub r#type: String,
    pub kind_detail: String,
    pub area: String,
    pub confidence: f64,
    pub drawing: String,
}

#[derive(Serialize)]
pub struct GapsDto {
    pub orphans: Vec<GapRowDto>,
    pub no_drawing: Vec<NoDrawingRowDto>,
    pub low_confidence: Vec<LowConfidenceRowDto>,
    pub lonely_equipment: Vec<GapRowDto>,
}

#[derive(Serialize)]
pub struct ReviewStatusResponse {
    pub success: bool,
    pub tag: String,
    pub new_status: String,
}

#[derive(Serialize)]
pub struct BulkReviewResponse {
    pub success: bool,
    pub count: usize,
}

#[derive(Serialize)]
pub struct UpdateInstrumentResponse {
    pub success: bool,
    pub tag: String,
    pub field: String,
    pub new_value: String,
}

#[derive(Serialize)]
pub struct AddConnectionResponse {
    pub success: bool,
    pub id: String,
}

#[derive(Serialize)]
pub struct TagResponse {
    pub success: bool,
    pub tag: String,
}
