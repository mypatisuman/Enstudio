use serde::Serialize;

#[derive(Serialize)]
pub struct CreateProjectResponse {
    pub pid: String,
    pub name: String,
}

#[derive(Serialize)]
pub struct ProjectStatsDto {
    pub node_count: i64,
    pub edge_count: i64,
}

#[derive(Serialize)]
pub struct ProjectSummaryDto {
    pub id: String,
    pub name: String,
    pub status: String,
    pub instruments: i64,
    pub equipment: i64,
    pub drawings: i64,
    pub last_extraction: Option<String>,
    pub last_activity: Option<String>,
}

#[derive(Serialize)]
pub struct RenameProjectResponse {
    pub success: bool,
    pub new_id: String,
    pub new_name: String,
}
