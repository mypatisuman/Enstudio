use std::collections::HashMap;
use std::sync::{Arc, Mutex};

// Keyed by project_id — lets multiple projects extract concurrently while
// still blocking a second concurrent run on the SAME project.
pub struct ProcessState {
    pub(crate) child: Arc<Mutex<HashMap<String, std::process::Child>>>,
}

impl ProcessState {
    pub fn new() -> Self {
        Self { child: Arc::new(Mutex::new(HashMap::new())) }
    }
}
