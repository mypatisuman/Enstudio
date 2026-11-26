pub mod email_dns;

/// Parse PNG or JPEG dimensions from raw bytes without an external crate.
pub fn parse_image_dims(bytes: &[u8]) -> (u32, u32) {
    // PNG: signature 8 bytes + IHDR chunk: length(4) + "IHDR"(4) + width(4) + height(4)
    if bytes.len() >= 24 && bytes.starts_with(b"\x89PNG\r\n\x1a\n") {
        let w = u32::from_be_bytes([bytes[16], bytes[17], bytes[18], bytes[19]]);
        let h = u32::from_be_bytes([bytes[20], bytes[21], bytes[22], bytes[23]]);
        return (w, h);
    }
    // JPEG: scan segments for SOF0-SOF3 / SOF5-SOF7 / SOF9-SOF11 markers
    if bytes.len() >= 4 && bytes[0] == 0xFF && bytes[1] == 0xD8 {
        let mut i = 2usize;
        while i + 3 < bytes.len() {
            if bytes[i] != 0xFF { break; }
            let marker = bytes[i + 1];
            // SOF markers that carry frame dimensions
            if matches!(marker, 0xC0..=0xC3 | 0xC5..=0xC7 | 0xC9..=0xCB | 0xCD..=0xCF)
                && i + 8 < bytes.len() {
                    let h = u16::from_be_bytes([bytes[i+5], bytes[i+6]]) as u32;
                    let w = u16::from_be_bytes([bytes[i+7], bytes[i+8]]) as u32;
                    return (w, h);
                }
            if i + 3 < bytes.len() {
                let seg_len = u16::from_be_bytes([bytes[i+2], bytes[i+3]]) as usize;
                if seg_len < 2 { break; }
                i += 2 + seg_len;
            } else { break; }
        }
    }
    (0, 0)
}
