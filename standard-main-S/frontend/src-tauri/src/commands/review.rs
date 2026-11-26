use crate::database::{open_db, collect_rows};

use crate::models::{
    NodeKinds, InstrumentDto, EquipmentDto, GapRowDto, NoDrawingRowDto, LowConfidenceRowDto,
    GapsDto, ReviewStatusResponse, BulkReviewResponse, UpdateInstrumentResponse,
    AddConnectionResponse, TagResponse,
};

#[tauri::command]
pub fn get_instruments(project_id: String) -> Result<Vec<InstrumentDto>, String> {
    let conn = open_db()?;
    // Columns confirmed from db.py schema:
    //   instruments: tag, pid, area, kind_detail, type, equipment_ref, extra_json
    //   extra_json fields include: drawing, confidence, description, range_lo/hi,
    //                              units, alarm_*, fail_position, loop_number
    //   review: (pid, key=tag, state=review_status)
    let mut stmt = conn.prepare(
        "SELECT i.tag,
                COALESCE(i.type,         '') AS type,
                COALESCE(i.kind_detail,  '') AS kind_detail,
                COALESCE(i.area,         '') AS area,
                COALESCE(i.equipment_ref,'') AS equipment_ref,
                COALESCE(json_extract(i.extra_json, '$.drawing'),     '') AS drawing,
                COALESCE(json_extract(i.extra_json, '$.description'), '') AS description,
                json_extract(i.extra_json, '$.confidence')              AS confidence,
                COALESCE(r.state, 'pending')                            AS review_status
         FROM instruments i
         LEFT JOIN review r ON r.pid = i.pid AND r.key = i.tag
         WHERE i.pid = ?
         ORDER BY i.tag",
    ).map_err(|e| format!("Prepare failed: {}", e))?;

    collect_rows(&mut stmt, [project_id.as_str()], |row| {
        let confidence: Option<f64> = row.get(7)?;
        Ok(InstrumentDto {
            tag:          row.get::<_, String>(0)?,
            r#type:       row.get::<_, String>(1)?,
            kind_detail:  row.get::<_, String>(2)?,
            area:         row.get::<_, String>(3)?,
            equipment_ref:row.get::<_, String>(4)?,
            drawing:      row.get::<_, String>(5)?,
            description:  row.get::<_, String>(6)?,
            confidence:   confidence.unwrap_or(0.0),
            review_status:row.get::<_, String>(8)?,
        })
    })
}

#[tauri::command]
pub fn get_equipment(project_id: String) -> Result<Vec<EquipmentDto>, String> {
    let conn = open_db()?;
    // Columns confirmed from db.py schema:
    //   equipment: tag, pid, area, kind_detail, type, extra_json
    //   drawing and description are in extra_json
    let mut stmt = conn.prepare(
        "SELECT e.tag,
                COALESCE(e.type,        '') AS type,
                COALESCE(e.kind_detail, '') AS kind_detail,
                COALESCE(e.area,        '') AS area,
                COALESCE(json_extract(e.extra_json, '$.drawing'),     '') AS drawing,
                COALESCE(json_extract(e.extra_json, '$.description'), '') AS description
         FROM equipment e
         WHERE e.pid = ?
         ORDER BY e.tag",
    ).map_err(|e| format!("Prepare failed: {}", e))?;

    collect_rows(&mut stmt, [project_id.as_str()], |row| {
        Ok(EquipmentDto {
            tag:         row.get::<_, String>(0)?,
            r#type:      row.get::<_, String>(1)?,
            kind_detail: row.get::<_, String>(2)?,
            area:        row.get::<_, String>(3)?,
            drawing:     row.get::<_, String>(4)?,
            description: row.get::<_, String>(5)?,
        })
    })
}

#[tauri::command]
pub fn get_gaps(project_id: String) -> Result<GapsDto, String> {
    let conn = open_db()?;
    let pid  = project_id.as_str();

    // 1. Orphaned instruments — equipment_ref is NULL or ''
    //    (native column, no json_extract needed)
    let orphans = {
        let mut s = conn.prepare(
            "SELECT i.tag,
                    COALESCE(i.type,        '') AS type,
                    COALESCE(i.kind_detail, '') AS kind_detail,
                    COALESCE(i.area,        '') AS area,
                    COALESCE(json_extract(i.extra_json, '$.drawing'), '') AS drawing
             FROM instruments i
             WHERE i.pid = ?
               AND (i.equipment_ref IS NULL OR i.equipment_ref = '')
             ORDER BY i.tag"
        ).map_err(|e| format!("orphans prepare: {}", e))?;
        collect_rows(&mut s, [pid], |row| {
            Ok(GapRowDto {
                tag:        row.get::<_, String>(0)?,
                r#type:     row.get::<_, String>(1)?,
                kind_detail:row.get::<_, String>(2)?,
                area:       row.get::<_, String>(3)?,
                drawing:    row.get::<_, String>(4)?,
            })
        })?
    };

    // 2. Missing drawings — drawing field absent in extra_json
    let no_drawing = {
        let mut s = conn.prepare(
            "SELECT i.tag,
                    COALESCE(i.type,        '') AS type,
                    COALESCE(i.kind_detail, '') AS kind_detail,
                    COALESCE(i.area,        '') AS area,
                    COALESCE(i.equipment_ref,'') AS equipment_ref
             FROM instruments i
             WHERE i.pid = ?
               AND (json_extract(i.extra_json, '$.drawing') IS NULL
                    OR json_extract(i.extra_json, '$.drawing') = '')
             ORDER BY i.tag"
        ).map_err(|e| format!("no_drawing prepare: {}", e))?;
        collect_rows(&mut s, [pid], |row| {
            Ok(NoDrawingRowDto {
                tag:          row.get::<_, String>(0)?,
                r#type:       row.get::<_, String>(1)?,
                kind_detail:  row.get::<_, String>(2)?,
                area:         row.get::<_, String>(3)?,
                equipment_ref:row.get::<_, String>(4)?,
            })
        })?
    };

    // 3. Low confidence — confidence present but < 0.5
    //    json_extract returns REAL for numeric JSON values
    let low_confidence = {
        let mut s = conn.prepare(
            "SELECT i.tag,
                    COALESCE(i.type,        '') AS type,
                    COALESCE(i.kind_detail, '') AS kind_detail,
                    COALESCE(i.area,        '') AS area,
                    json_extract(i.extra_json, '$.confidence') AS confidence,
                    COALESCE(json_extract(i.extra_json, '$.drawing'), '') AS drawing
             FROM instruments i
             WHERE i.pid = ?
               AND json_extract(i.extra_json, '$.confidence') IS NOT NULL
               AND json_extract(i.extra_json, '$.confidence') < 0.5
             ORDER BY json_extract(i.extra_json, '$.confidence') ASC"
        ).map_err(|e| format!("low_confidence prepare: {}", e))?;
        collect_rows(&mut s, [pid], |row| {
            let confidence: Option<f64> = row.get(4)?;
            Ok(LowConfidenceRowDto {
                tag:        row.get::<_, String>(0)?,
                r#type:     row.get::<_, String>(1)?,
                kind_detail:row.get::<_, String>(2)?,
                area:       row.get::<_, String>(3)?,
                confidence: confidence.unwrap_or(0.0),
                drawing:    row.get::<_, String>(5)?,
            })
        })?
    };

    // 4. Lonely equipment — no instrument has this tag as equipment_ref
    let lonely_equipment = {
        let mut s = conn.prepare(
            "SELECT e.tag,
                    COALESCE(e.type,        '') AS type,
                    COALESCE(e.kind_detail, '') AS kind_detail,
                    COALESCE(e.area,        '') AS area,
                    COALESCE(json_extract(e.extra_json, '$.drawing'), '') AS drawing
             FROM equipment e
             WHERE e.pid = ?
               AND e.tag NOT IN (
                   SELECT equipment_ref FROM instruments
                   WHERE pid = ? AND equipment_ref IS NOT NULL AND equipment_ref != ''
               )
             ORDER BY e.tag"
        ).map_err(|e| format!("lonely_equipment prepare: {}", e))?;
        collect_rows(&mut s, [pid, pid], |row| {
            Ok(GapRowDto {
                tag:        row.get::<_, String>(0)?,
                r#type:     row.get::<_, String>(1)?,
                kind_detail:row.get::<_, String>(2)?,
                area:       row.get::<_, String>(3)?,
                drawing:    row.get::<_, String>(4)?,
            })
        })?
    };

    Ok(GapsDto { orphans, no_drawing, low_confidence, lonely_equipment })
}

#[tauri::command]
pub fn update_review_status(project_id: String, tag: String, status: String) -> Result<ReviewStatusResponse, String> {
    if !["accepted", "rejected", "pending"].contains(&status.as_str()) {
        return Err(format!("Invalid status '{}' — must be accepted, rejected, or pending", status));
    }
    let conn = open_db()?;
    conn.execute(
        "INSERT OR REPLACE INTO review (pid, key, state) VALUES (?, ?, ?)",
        rusqlite::params![project_id, tag, status],
    ).map_err(|e| format!("Update review: {}", e))?;
    Ok(ReviewStatusResponse { success: true, tag, new_status: status })
}

#[tauri::command]
pub fn bulk_update_review(project_id: String, tags: Vec<String>, status: String) -> Result<BulkReviewResponse, String> {
    if !["accepted", "rejected", "pending"].contains(&status.as_str()) {
        return Err(format!("Invalid status '{}'", status));
    }
    let mut conn = open_db()?;
    let tx = conn.transaction().map_err(|e| format!("Begin tx: {}", e))?;
    let count = tags.len();
    for tag in &tags {
        tx.execute(
            "INSERT OR REPLACE INTO review (pid, key, state) VALUES (?, ?, ?)",
            rusqlite::params![project_id, tag, status],
        ).map_err(|e| format!("Bulk update at '{}': {}", tag, e))?;
    }
    tx.commit().map_err(|e| format!("Commit: {}", e))?;
    Ok(BulkReviewResponse { success: true, count })
}

#[tauri::command]
pub fn update_instrument(project_id: String, tag: String, field: String, value: String) -> Result<UpdateInstrumentResponse, String> {
    let conn = open_db()?;
    match field.as_str() {
        "equipment_ref" => conn.execute(
            "UPDATE instruments SET equipment_ref = ? WHERE pid = ? AND tag = ?",
            rusqlite::params![value, project_id, tag],
        ).map_err(|e| format!("Update equipment_ref: {}", e))?,
        "area" => conn.execute(
            "UPDATE instruments SET area = ? WHERE pid = ? AND tag = ?",
            rusqlite::params![value, project_id, tag],
        ).map_err(|e| format!("Update area: {}", e))?,
        "description" => conn.execute(
            "UPDATE instruments SET extra_json = json_set(COALESCE(extra_json,'{}'), '$.description', ?) \
             WHERE pid = ? AND tag = ?",
            rusqlite::params![value, project_id, tag],
        ).map_err(|e| format!("Update description: {}", e))?,
        other => return Err(format!("Unknown field '{}' — allowed: equipment_ref, area, description", other)),
    };
    Ok(UpdateInstrumentResponse { success: true, tag, field, new_value: value })
}

#[tauri::command]
pub fn add_connection(project_id: String, source_tag: String, target_tag: String, conn_type: String) -> Result<AddConnectionResponse, String> {
    let db = open_db()?;
    let id = format!("{}\x1e{}\x1e{}", source_tag, target_tag, conn_type);
    db.execute(
        "INSERT OR IGNORE INTO connections (id, pid, from_tag, to_tag, type) VALUES (?, ?, ?, ?, ?)",
        rusqlite::params![id, project_id, source_tag, target_tag, conn_type],
    ).map_err(|e| format!("Add connection: {}", e))?;
    Ok(AddConnectionResponse { success: true, id })
}

#[tauri::command]
pub fn delete_instrument(project_id: String, tag: String) -> Result<TagResponse, String> {
    let mut conn = open_db()?;
    let tx = conn.transaction().map_err(|e| format!("Begin tx: {}", e))?;
    tx.execute(
        "DELETE FROM instruments WHERE pid = ? AND tag = ?",
        rusqlite::params![project_id, tag],
    ).map_err(|e| format!("Delete instrument: {}", e))?;
    tx.execute(
        "DELETE FROM review WHERE pid = ? AND key = ?",
        rusqlite::params![project_id, tag],
    ).map_err(|e| format!("Delete review row: {}", e))?;
    tx.commit().map_err(|e| format!("Commit: {}", e))?;
    Ok(TagResponse { success: true, tag })
}

#[tauri::command]
pub fn get_node_kinds() -> Result<NodeKinds, String> {
    let conn = open_db()?;
    let mut instrs = Vec::new();
    let mut equip = Vec::new();
    
    if let Ok(mut stmt) = conn.prepare("SELECT DISTINCT type FROM instruments WHERE type IS NOT NULL AND type != ''") {
        if let Ok(rows) = stmt.query_map([], |row| row.get(0)) {
            for k in rows.flatten() { instrs.push(k); }
        }
    }
    
    if let Ok(mut stmt) = conn.prepare("SELECT DISTINCT type FROM equipment WHERE type IS NOT NULL AND type != ''") {
        if let Ok(rows) = stmt.query_map([], |row| row.get(0)) {
            for k in rows.flatten() { equip.push(k); }
        }
    }
    
    Ok(NodeKinds { instruments: instrs, equipment: equip })
}
