"""
Diagnostic Parser - Parse instrument log files (CSV, JSON)

Handles various instrument log formats:
- CSV files with readings, alarms, events
- JSON structured logs
- Common industrial formats (historian exports, SCADA exports)
"""

import json
import logging
import os
import threading
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from io import StringIO
from typing import Any

import time
import numpy as np

logger = logging.getLogger(__name__)

# ============================================================================
# CONSTANTS - Common column name mappings
# ============================================================================

TIMESTAMP_COLUMNS = [
    'timestamp', 'time', 'datetime', 'date_time', 'date', 'eventtime',
    'event_time', 'logtime', 'log_time', 'recorded_at', 'created_at'
]

TAG_COLUMNS = [
    'tag', 'tag_number', 'tagname', 'tag_name', 'instrument', 'instrument_tag',
    'point', 'pointname', 'point_name', 'pid', 'asset_tag', 'device_id', 'sensor'
]

VALUE_COLUMNS = [
    'value', 'reading', 'measurement', 'pv', 'process_value', 'data',
    'actual', 'measured', 'result'
]

UNIT_COLUMNS = [
    'unit', 'units', 'eng_unit', 'engineering_unit', 'uom', 'unit_of_measure'
]

MESSAGE_COLUMNS = [
    'message', 'msg', 'description', 'desc', 'text', 'comment', 'remarks',
    'notes', 'alarm_text', 'event_text', 'details'
]

ALARM_TYPE_COLUMNS = [
    'alarm_type', 'alarmtype', 'alarm', 'alarm_code', 'alarm_class',
    'priority', 'alarm_priority', 'level'
]

SEVERITY_COLUMNS = [
    'severity', 'sev', 'priority', 'criticality', 'importance', 'urgency'
]

LOG_TYPE_COLUMNS = [
    'type', 'log_type', 'event_type', 'eventtype', 'category', 'record_type'
]

# Value mapping for severity levels
SEVERITY_MAPPING = {
    # Critical
    'critical': 'critical', 'crit': 'critical', 'high': 'critical',
    'emergency': 'emergency', 'urgent': 'emergency', 'emerg': 'emergency',
    # Warning
    'warning': 'warning', 'warn': 'warning', 'medium': 'warning', 'moderate': 'warning',
    # Info
    'info': 'info', 'information': 'info', 'low': 'info', 'normal': 'info', 'ok': 'info'
}

# Value mapping for log types
LOG_TYPE_MAPPING = {
    'reading': 'reading', 'value': 'reading', 'measurement': 'reading', 'pv': 'reading',
    'alarm': 'alarm', 'alert': 'alarm', 'fault': 'alarm',
    'event': 'event', 'status': 'event', 'change': 'event',
    'diagnostic': 'diagnostic', 'diag': 'diagnostic', 'health': 'diagnostic'
}

# Common alarm type codes
ALARM_TYPE_MAPPING = {
    'hh': 'HH', 'high high': 'HH', 'highhigh': 'HH',
    'h': 'H', 'high': 'H', 'hi': 'H',
    'l': 'L', 'low': 'L', 'lo': 'L',
    'll': 'LL', 'low low': 'LL', 'lowlow': 'LL',
    'rate': 'RATE', 'roc': 'RATE',  # Rate of change
    'dev': 'DEV', 'deviation': 'DEV',
    'fail': 'FAIL', 'failure': 'FAIL', 'fault': 'FAIL',
    'comm': 'COMM', 'communication': 'COMM', 'comms': 'COMM'
}


# ============================================================================
# CSV PARSING
# ============================================================================

def parse_csv_logs(
    file_content: bytes | str,
    filename: str = 'unknown.csv'
) -> dict[str, Any]:
    """
    Parse CSV file containing instrument logs.

    Automatically detects column mappings for common log formats.

    Args:
        file_content: Raw CSV content (bytes or string)
        filename: Original filename for logging

    Returns:
        Dict with:
        - success: bool
        - logs: list of parsed log entries
        - columns_detected: dict of detected column mappings
        - row_count: number of rows processed
        - error: error message if failed
    """
    try:
        import pandas as pd

        logger.info(f"[DIAGNOSTIC_PARSER] Parsing CSV file: {filename}")

        # Handle bytes input
        if isinstance(file_content, bytes):
            file_content = file_content.decode('utf-8', errors='replace')

        # Parse with pandas
        df = pd.read_csv(StringIO(file_content))
        logger.info(f"[DIAGNOSTIC_PARSER] CSV loaded: {len(df)} rows, {len(df.columns)} columns")

        # Normalize column names
        df.columns = df.columns.str.strip().str.lower()

        # Detect column mappings
        column_map = _detect_columns(df.columns.tolist())
        logger.info(f"[DIAGNOSTIC_PARSER] Detected columns: {column_map}")

        # Parse each row into standardized log format
        logs = []
        for _, row in df.iterrows():
            log_entry = _parse_row(row, column_map)
            if log_entry:
                logs.append(log_entry)

        logger.info(f"[DIAGNOSTIC_PARSER] ✓ Parsed {len(logs)} log entries from CSV")

        return {
            "success": True,
            "logs": logs,
            "columns_detected": column_map,
            "row_count": len(logs),
            "original_columns": df.columns.tolist()
        }

    except Exception as e:
        logger.error(f"[DIAGNOSTIC_PARSER] CSV parsing failed: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return {
            "success": False,
            "error": str(e),
            "logs": []
        }


def _detect_columns(columns: list[str]) -> dict[str, str | None]:
    """Detect which CSV columns map to our standard fields."""
    column_map = {
        'timestamp': None,
        'tag_number': None,
        'value': None,
        'unit': None,
        'message': None,
        'alarm_type': None,
        'severity': None,
        'log_type': None
    }

    columns_lower = [c.lower().strip() for c in columns]

    # Find best match for each field
    for col_lower, col_orig in zip(columns_lower, columns, strict=False):
        # Timestamp
        if any(ts in col_lower for ts in TIMESTAMP_COLUMNS):
            if column_map['timestamp'] is None:
                column_map['timestamp'] = col_orig

        # Tag number
        if any(tag in col_lower for tag in TAG_COLUMNS):
            if column_map['tag_number'] is None:
                column_map['tag_number'] = col_orig

        # Value
        if any(val in col_lower for val in VALUE_COLUMNS):
            if column_map['value'] is None:
                column_map['value'] = col_orig

        # Unit
        if any(unit in col_lower for unit in UNIT_COLUMNS):
            if column_map['unit'] is None:
                column_map['unit'] = col_orig

        # Message
        if any(msg in col_lower for msg in MESSAGE_COLUMNS):
            if column_map['message'] is None:
                column_map['message'] = col_orig

        # Alarm type
        if any(alarm in col_lower for alarm in ALARM_TYPE_COLUMNS):
            if column_map['alarm_type'] is None:
                column_map['alarm_type'] = col_orig

        # Severity
        if any(sev in col_lower for sev in SEVERITY_COLUMNS):
            if column_map['severity'] is None:
                column_map['severity'] = col_orig

        # Log type
        if any(lt in col_lower for lt in LOG_TYPE_COLUMNS):
            if column_map['log_type'] is None:
                column_map['log_type'] = col_orig

    return column_map


def _parse_row(row, column_map: dict) -> dict[str, Any] | None:
    """Parse a single row into a standardized log entry."""
    import pandas as pd

    # Skip empty rows
    non_empty = sum(1 for v in row if pd.notna(v) and str(v).strip())
    if non_empty < 2:
        return None

    entry = {}

    # Parse timestamp
    ts_col = column_map.get('timestamp')
    if ts_col and ts_col in row:
        entry['timestamp'] = _parse_timestamp(row[ts_col])
    else:
        entry['timestamp'] = None

    # Parse tag number
    tag_col = column_map.get('tag_number')
    if tag_col and tag_col in row and pd.notna(row[tag_col]):
        entry['tag_number'] = str(row[tag_col]).strip()
    else:
        entry['tag_number'] = ''

    # Parse value
    val_col = column_map.get('value')
    if val_col and val_col in row and pd.notna(row[val_col]):
        try:
            entry['value'] = float(row[val_col])
        except (ValueError, TypeError):
            entry['value'] = str(row[val_col])
    else:
        entry['value'] = None

    # Parse unit
    unit_col = column_map.get('unit')
    if unit_col and unit_col in row and pd.notna(row[unit_col]):
        entry['unit'] = str(row[unit_col]).strip()
    else:
        entry['unit'] = ''

    # Parse message
    msg_col = column_map.get('message')
    if msg_col and msg_col in row and pd.notna(row[msg_col]):
        entry['message'] = str(row[msg_col]).strip()
    else:
        entry['message'] = ''

    # Parse alarm type
    alarm_col = column_map.get('alarm_type')
    if alarm_col and alarm_col in row and pd.notna(row[alarm_col]):
        alarm_val = str(row[alarm_col]).strip().lower()
        entry['alarm_type'] = ALARM_TYPE_MAPPING.get(alarm_val, alarm_val.upper())
    else:
        entry['alarm_type'] = None

    # Parse severity
    sev_col = column_map.get('severity')
    if sev_col and sev_col in row and pd.notna(row[sev_col]):
        sev_val = str(row[sev_col]).strip().lower()
        entry['severity'] = SEVERITY_MAPPING.get(sev_val, 'info')
    else:
        entry['severity'] = 'info'

    # Parse log type
    type_col = column_map.get('log_type')
    if type_col and type_col in row and pd.notna(row[type_col]):
        type_val = str(row[type_col]).strip().lower()
        entry['log_type'] = LOG_TYPE_MAPPING.get(type_val, 'reading')
    else:
        # Infer log type from other fields
        if entry.get('alarm_type'):
            entry['log_type'] = 'alarm'
        elif entry.get('value') is not None:
            entry['log_type'] = 'reading'
        else:
            entry['log_type'] = 'event'

    return entry


def _parse_timestamp(value) -> datetime | None:
    """Parse various timestamp formats."""
    import pandas as pd

    if pd.isna(value):
        return None

    if isinstance(value, datetime):
        return value

    value_str = str(value).strip()

    # Common timestamp formats to try
    formats = [
        '%Y-%m-%d %H:%M:%S',
        '%Y-%m-%d %H:%M:%S.%f',
        '%Y-%m-%dT%H:%M:%S',
        '%Y-%m-%dT%H:%M:%S.%fZ',
        '%Y-%m-%dT%H:%M:%SZ',
        '%m/%d/%Y %H:%M:%S',
        '%m/%d/%Y %H:%M',
        '%d/%m/%Y %H:%M:%S',
        '%d-%m-%Y %H:%M:%S',
        '%Y%m%d%H%M%S',
    ]

    for fmt in formats:
        try:
            return datetime.strptime(value_str, fmt)
        except ValueError:
            continue

    # Try pandas parser as fallback
    try:
        return pd.to_datetime(value_str).to_pydatetime()
    except Exception:
        return None


# ============================================================================
# JSON PARSING
# ============================================================================

def parse_json_logs(
    file_content: bytes | str,
    filename: str = 'unknown.json'
) -> dict[str, Any]:
    """
    Parse JSON file containing instrument logs.

    Supports:
    - Array of log objects
    - Object with 'data' or 'logs' array
    - Line-delimited JSON (JSONL)

    Args:
        file_content: Raw JSON content (bytes or string)
        filename: Original filename for logging

    Returns:
        Dict with success status and parsed logs
    """
    try:
        logger.info(f"[DIAGNOSTIC_PARSER] Parsing JSON file: {filename}")

        # Handle bytes input
        if isinstance(file_content, bytes):
            file_content = file_content.decode('utf-8', errors='replace')

        logs = []

        # Try standard JSON first
        try:
            data = json.loads(file_content)

            if isinstance(data, list):
                # Array of log objects
                for item in data:
                    if isinstance(item, dict):
                        log_entry = _normalize_json_log(item)
                        if log_entry:
                            logs.append(log_entry)

            elif isinstance(data, dict):
                # Object with nested array
                log_array = data.get('data') or data.get('logs') or data.get('events') or data.get('readings')
                if isinstance(log_array, list):
                    for item in log_array:
                        if isinstance(item, dict):
                            log_entry = _normalize_json_log(item)
                            if log_entry:
                                logs.append(log_entry)

        except json.JSONDecodeError:
            # Try line-delimited JSON (JSONL)
            for line in file_content.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    item = json.loads(line)
                    if isinstance(item, dict):
                        log_entry = _normalize_json_log(item)
                        if log_entry:
                            logs.append(log_entry)
                except json.JSONDecodeError:
                    continue

        logger.info(f"[DIAGNOSTIC_PARSER] ✓ Parsed {len(logs)} log entries from JSON")

        return {
            "success": True,
            "logs": logs,
            "row_count": len(logs)
        }

    except Exception as e:
        logger.error(f"[DIAGNOSTIC_PARSER] JSON parsing failed: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return {
            "success": False,
            "error": str(e),
            "logs": []
        }


def _normalize_json_log(item: dict) -> dict[str, Any] | None:
    """Normalize a JSON log object to standard format."""
    # Build standardized entry
    entry = {}

    # Find timestamp (try multiple keys)
    for key in TIMESTAMP_COLUMNS:
        if key in item:
            entry['timestamp'] = _parse_timestamp(item[key])
            break

    # Find tag number
    for key in TAG_COLUMNS:
        if key in item:
            entry['tag_number'] = str(item[key]).strip()
            break
    else:
        entry['tag_number'] = ''

    # Find value
    for key in VALUE_COLUMNS:
        if key in item:
            try:
                entry['value'] = float(item[key])
            except (ValueError, TypeError):
                entry['value'] = item[key]
            break
    else:
        entry['value'] = None

    # Find unit
    for key in UNIT_COLUMNS:
        if key in item:
            entry['unit'] = str(item[key]).strip()
            break
    else:
        entry['unit'] = ''

    # Find message
    for key in MESSAGE_COLUMNS:
        if key in item:
            entry['message'] = str(item[key]).strip()
            break
    else:
        entry['message'] = ''

    # Find alarm type
    for key in ALARM_TYPE_COLUMNS:
        if key in item:
            alarm_val = str(item[key]).strip().lower()
            entry['alarm_type'] = ALARM_TYPE_MAPPING.get(alarm_val, alarm_val.upper())
            break
    else:
        entry['alarm_type'] = None

    # Find severity
    for key in SEVERITY_COLUMNS:
        if key in item:
            sev_val = str(item[key]).strip().lower()
            entry['severity'] = SEVERITY_MAPPING.get(sev_val, 'info')
            break
    else:
        entry['severity'] = 'info'

    # Find log type
    for key in LOG_TYPE_COLUMNS:
        if key in item:
            type_val = str(item[key]).strip().lower()
            entry['log_type'] = LOG_TYPE_MAPPING.get(type_val, 'reading')
            break
    else:
        # Infer from other fields
        if entry.get('alarm_type'):
            entry['log_type'] = 'alarm'
        elif entry.get('value') is not None:
            entry['log_type'] = 'reading'
        else:
            entry['log_type'] = 'event'

    return entry


# ============================================================================
# UNIFIED PARSER
# ============================================================================

def parse_instrument_logs(
    file_content: bytes | str,
    filename: str
) -> dict[str, Any]:
    """
    Unified parser that auto-detects file format.

    Args:
        file_content: Raw file content
        filename: Original filename (used for format detection)

    Returns:
        Dict with success status, parsed logs, and format detected
    """
    filename_lower = filename.lower()

    if filename_lower.endswith('.json') or filename_lower.endswith('.jsonl'):
        result = parse_json_logs(file_content, filename)
        result['format'] = 'json'
        return result

    elif filename_lower.endswith('.csv'):
        result = parse_csv_logs(file_content, filename)
        result['format'] = 'csv'
        return result

    else:
        # Try to detect format from content
        if isinstance(file_content, bytes):
            content_sample = file_content[:1000].decode('utf-8', errors='replace')
        else:
            content_sample = file_content[:1000]

        content_sample = content_sample.strip()

        # Check if it looks like JSON
        if content_sample.startswith('{') or content_sample.startswith('['):
            result = parse_json_logs(file_content, filename)
            result['format'] = 'json'
            return result
        else:
            # Default to CSV
            result = parse_csv_logs(file_content, filename)
            result['format'] = 'csv'
            return result


# ============================================================================
# SAMPLE DATA GENERATOR (for testing)
# ============================================================================

def generate_sample_logs(
    tag_numbers: list[str],
    hours: int = 24,
    readings_per_hour: int = 6,
    include_alarms: bool = True
) -> list[dict[str, Any]]:
    """
    Generate sample instrument log data for testing.

    Args:
        tag_numbers: List of instrument tags (e.g., ["PT-101", "FT-201"])
        hours: Number of hours of data to generate
        readings_per_hour: Number of readings per hour per instrument
        include_alarms: Whether to include random alarm events

    Returns:
        List of log entries
    """
    import random
    from datetime import timedelta

    logs = []
    now = datetime.now()
    interval_minutes = 60 // readings_per_hour

    # Define typical ranges for each tag prefix
    tag_ranges = {
        'PT': {'unit': 'psi', 'min': 30, 'max': 100, 'hh': 95, 'll': 35},
        'FT': {'unit': 'gpm', 'min': 50, 'max': 200, 'hh': 190, 'll': 60},
        'TT': {'unit': 'degC', 'min': 20, 'max': 80, 'hh': 75, 'll': 25},
        'LT': {'unit': '%', 'min': 10, 'max': 90, 'hh': 85, 'll': 15},
    }

    for tag in tag_numbers:
        prefix = tag.split('-')[0] if '-' in tag else 'PT'
        config = tag_ranges.get(prefix, tag_ranges['PT'])

        base_value = (config['min'] + config['max']) / 2
        noise_factor = (config['max'] - config['min']) * 0.1

        for hour_offset in range(hours):
            for reading in range(readings_per_hour):
                timestamp = now - timedelta(hours=hour_offset, minutes=reading * interval_minutes)

                # Generate reading with some noise and drift
                drift = (hour_offset / hours) * 0.05 * (config['max'] - config['min'])
                value = base_value + drift + random.gauss(0, noise_factor)
                value = max(config['min'], min(config['max'], value))

                logs.append({
                    'timestamp': timestamp.isoformat(),
                    'tag_number': tag,
                    'value': round(value, 2),
                    'unit': config['unit'],
                    'log_type': 'reading',
                    'severity': 'info'
                })

                # Random alarm events
                if include_alarms and random.random() < 0.02:
                    alarm_type = random.choice(['HH', 'H', 'L', 'LL'])
                    logs.append({
                        'timestamp': timestamp.isoformat(),
                        'tag_number': tag,
                        'value': config['hh'] if 'H' in alarm_type else config['ll'],
                        'unit': config['unit'],
                        'log_type': 'alarm',
                        'alarm_type': alarm_type,
                        'severity': 'critical' if alarm_type in ['HH', 'LL'] else 'warning',
                        'message': f"{alarm_type} alarm triggered on {tag}"
                    })

    # Sort by timestamp
    logs.sort(key=lambda x: x['timestamp'], reverse=True)

    return logs


# ============================================================================
# ANOMALY DETECTION
# ============================================================================

@dataclass
class AnomalyResult:
    """Result of anomaly detection for a single reading."""
    is_anomaly: bool
    anomaly_score: float  # 0.0 = normal, 1.0 = definitely anomaly
    anomaly_type: str | None  # 'zscore', 'iqr', 'roc', 'stuck', etc.
    details: dict[str, Any]


@dataclass
class InstrumentStatistics:
    """Running statistics for an instrument."""
    tag_number: str
    count: int
    mean: float
    std: float
    min_value: float
    max_value: float
    q1: float
    q3: float
    last_value: float | None
    last_timestamp: datetime | None
    values_buffer: list[float]

    @property
    def iqr(self) -> float:
        return self.q3 - self.q1


class AnomalyDetector:
    """
    Detects anomalies in instrument readings using multiple methods:
    Z-Score, IQR, Rate of Change, and Stuck Value detection.
    """

    def __init__(
        self,
        zscore_threshold: float = 3.0,
        iqr_multiplier: float = 1.5,
        roc_threshold: float = 0.5,
        stuck_duration_minutes: float = 30.0,
        buffer_size: int = 100
    ):
        self.zscore_threshold = zscore_threshold
        self.iqr_multiplier = iqr_multiplier
        self.roc_threshold = roc_threshold
        self.stuck_duration_minutes = stuck_duration_minutes
        self.buffer_size = buffer_size
        self.stats: dict[str, InstrumentStatistics] = {}
        self.stuck_tracking: dict[str, dict] = defaultdict(
            lambda: {'value': None, 'since': None, 'count': 0}
        )

    def add_reading(self, tag_number: str, value: float, timestamp: datetime | None = None) -> None:
        """Add a reading to build baseline statistics."""
        if tag_number not in self.stats:
            self.stats[tag_number] = InstrumentStatistics(
                tag_number=tag_number, count=0, mean=0.0, std=0.0,
                min_value=float('inf'), max_value=float('-inf'),
                q1=0.0, q3=0.0, last_value=None, last_timestamp=None, values_buffer=[]
            )

        stats = self.stats[tag_number]
        stats.count += 1
        stats.values_buffer.append(value)
        if len(stats.values_buffer) > self.buffer_size:
            stats.values_buffer.pop(0)

        values = stats.values_buffer
        stats.mean = np.mean(values)
        stats.std = np.std(values) if len(values) > 1 else 0.0
        stats.min_value = min(stats.min_value, value)
        stats.max_value = max(stats.max_value, value)
        if len(values) >= 4:
            stats.q1 = np.percentile(values, 25)
            stats.q3 = np.percentile(values, 75)
        stats.last_value = value
        stats.last_timestamp = timestamp

    def detect(self, tag_number: str, value: float, timestamp: datetime | None = None) -> AnomalyResult:
        """Detect if a reading is anomalous."""
        timestamp = timestamp or datetime.now()

        if tag_number not in self.stats or self.stats[tag_number].count < 5:
            self.add_reading(tag_number, value, timestamp)
            return AnomalyResult(
                is_anomaly=False, anomaly_score=0.0, anomaly_type=None,
                details={'reason': 'insufficient_data'}
            )

        stats = self.stats[tag_number]
        scores: dict[str, float] = {}
        details: dict[str, Any] = {}

        r = self._detect_zscore(value, stats)
        scores['zscore'] = r['score']
        details['zscore'] = r

        r = self._detect_iqr(value, stats)
        scores['iqr'] = r['score']
        details['iqr'] = r

        if stats.last_value is not None and stats.last_timestamp is not None:
            r = self._detect_rate_of_change(value, timestamp, stats.last_value, stats.last_timestamp)
            scores['roc'] = r['score']
            details['roc'] = r

        r = self._detect_stuck_value(tag_number, value, timestamp)
        scores['stuck'] = r['score']
        details['stuck'] = r

        max_score = max(scores.values())
        is_anomaly = max_score >= 0.7
        anomaly_type = max(scores, key=scores.get) if is_anomaly else None

        self.add_reading(tag_number, value, timestamp)

        return AnomalyResult(
            is_anomaly=is_anomaly,
            anomaly_score=round(max_score, 3),
            anomaly_type=anomaly_type,
            details={'scores': scores, 'methods': details, 'threshold': 0.7,
                     'statistics': {'mean': round(stats.mean, 3), 'std': round(stats.std, 3), 'count': stats.count}}
        )

    def _detect_zscore(self, value: float, stats: InstrumentStatistics) -> dict:
        if stats.std == 0:
            return {'score': 0.0, 'zscore': 0.0}
        zscore = abs(value - stats.mean) / stats.std
        score = min(1.0, zscore / self.zscore_threshold)
        return {'score': round(score, 3), 'zscore': round(zscore, 3),
                'mean': round(stats.mean, 3), 'std': round(stats.std, 3)}

    def _detect_iqr(self, value: float, stats: InstrumentStatistics) -> dict:
        if stats.iqr == 0:
            # Sensor is flatlined — any deviation from the frozen median is anomalous.
            # Use the mean as the reference point since Q1==Q3==mean in this case.
            reference = stats.mean if stats.mean != 0 else stats.last_value or 0
            if reference == 0:
                # Absolute check: any non-zero value on a zero-mean flatline is an anomaly
                score = 1.0 if abs(value) > 1e-6 else 0.0
            else:
                # Relative deviation from flatline: >5% deviation = score 1.0
                deviation_pct = abs(value - reference) / abs(reference)
                score = min(1.0, deviation_pct / 0.05)
            return {'score': round(score, 3), 'iqr': 0.0,
                    'lower_bound': round(reference, 3), 'upper_bound': round(reference, 3),
                    'note': 'flatline_sensor_spike_detection'}
        lower = stats.q1 - self.iqr_multiplier * stats.iqr
        upper = stats.q3 + self.iqr_multiplier * stats.iqr
        if value < lower:
            score = min(1.0, (lower - value) / stats.iqr / self.iqr_multiplier)
        elif value > upper:
            score = min(1.0, (value - upper) / stats.iqr / self.iqr_multiplier)
        else:
            score = 0.0
        return {'score': round(score, 3), 'iqr': round(stats.iqr, 3),
                'lower_bound': round(lower, 3), 'upper_bound': round(upper, 3)}

    def _detect_rate_of_change(
        self, value: float, timestamp: datetime,
        last_value: float, last_timestamp: datetime
    ) -> dict:
        time_delta = (timestamp - last_timestamp).total_seconds() / 60
        if time_delta <= 0:
            return {'score': 0.0, 'roc': 0.0}
        # Use epsilon to avoid divide-by-zero when last_value is legitimately 0
        denom = abs(last_value) if abs(last_value) > 1e-9 else 1e-9
        roc = abs(value - last_value) / denom / time_delta
        change_pct = abs(value - last_value) / denom * 100
        score = min(1.0, roc / self.roc_threshold)
        return {'score': round(score, 3), 'roc': round(roc, 3),
                'change_pct': round(change_pct, 2)}

    def _detect_stuck_value(self, tag_number: str, value: float, timestamp: datetime) -> dict:
        tracking = self.stuck_tracking[tag_number]
        if tracking['value'] is not None:
            is_same = abs(value - tracking['value']) / max(abs(tracking['value']), 0.001) < 0.001
        else:
            is_same = False

        if is_same:
            tracking['count'] += 1
            duration = (timestamp - tracking['since']).total_seconds() / 60
            score = min(1.0, duration / self.stuck_duration_minutes)
            return {'score': round(score, 3), 'stuck_minutes': round(duration, 1)}
        else:
            tracking['value'] = value
            tracking['since'] = timestamp
            tracking['count'] = 1
            return {'score': 0.0, 'stuck_count': 1}

    def get_statistics(self, tag_number: str) -> dict[str, Any] | None:
        if tag_number not in self.stats:
            return None
        s = self.stats[tag_number]
        return {'tag_number': tag_number, 'count': s.count,
                'mean': round(s.mean, 3), 'std': round(s.std, 3),
                'min': round(s.min_value, 3), 'max': round(s.max_value, 3),
                'q1': round(s.q1, 3), 'q3': round(s.q3, 3), 'iqr': round(s.iqr, 3)}

    def get_all_statistics(self) -> dict[str, dict[str, Any]]:
        return {tag: self.get_statistics(tag) for tag in self.stats}


def detect_anomalies_batch(
    logs: list[dict[str, Any]],
    training_ratio: float = 0.3,
    existing_detector: 'AnomalyDetector | None' = None,
    **detector_kwargs
) -> dict[str, Any]:
    """
    Detect anomalies in a batch of instrument logs.

    Warm-up strategy (avoids baseline poisoning):
    - If an existing_detector is supplied (stateful mode), all logs are scored
      against the pre-built baseline. No training split is performed.
    - If no existing_detector, the first `training_ratio` portion is used as a
      warm-up pass (add_reading only, no scoring). This prevents anomalous
      readings that happen to land at the start of the batch from poisoning the
      baseline used to judge the rest of the batch.

    Args:
        logs: List of log dicts with tag_number, value, timestamp.
        training_ratio: Fraction of logs to warm-up on when no existing_detector.
        existing_detector: Pre-warmed AnomalyDetector instance for stateful tracking.
        **detector_kwargs: Passed to AnomalyDetector constructor when creating fresh.
    """
    if not logs:
        return {'success': False, 'error': 'No logs provided'}

    sorted_logs = sorted(logs, key=lambda x: x.get('timestamp', ''))

    if existing_detector is not None:
        # Stateful mode: score everything against the long-running baseline
        detector = existing_detector
        warmup_logs = []
        detection_logs = sorted_logs
    else:
        # Fresh mode: warm-up on first portion so anomalous early readings
        # do not poison the baseline used to score the rest
        split_idx = max(int(len(sorted_logs) * training_ratio), 0)
        warmup_logs = sorted_logs[:split_idx]
        detection_logs = sorted_logs[split_idx:]
        detector = AnomalyDetector(**detector_kwargs)

        for log in warmup_logs:
            if log.get('value') is not None and log.get('tag_number'):
                ts = _parse_timestamp(log.get('timestamp'))
                try:
                    detector.add_reading(log['tag_number'], float(log['value']), ts)
                except (ValueError, TypeError):
                    continue

    anomalies = []
    normal_count = 0
    for log in detection_logs:
        if log.get('value') is None or not log.get('tag_number'):
            continue
        ts = _parse_timestamp(log.get('timestamp'))
        try:
            value = float(log['value'])
        except (ValueError, TypeError):
            continue

        result = detector.detect(log['tag_number'], value, ts)
        if result.is_anomaly:
            anomalies.append({
                'tag_number': log['tag_number'],
                'value': value,
                'timestamp': ts.isoformat() if ts else None,
                'anomaly_type': result.anomaly_type,
                'anomaly_score': result.anomaly_score,
                'details': result.details
            })
        else:
            normal_count += 1

        # P0.x FIX: Yield every 100 logs to prevent Gunicorn worker starvation in single-worker setup
        if (normal_count + len(anomalies)) % 100 == 0:
            time.sleep(0)

    return {
        'success': True,
        'total_logs': len(logs),
        'warmup_logs': len(warmup_logs),
        'detection_logs': len(detection_logs),
        'anomalies_detected': len(anomalies),
        'normal_readings': normal_count,
        'anomaly_rate': round(len(anomalies) / max(len(detection_logs), 1) * 100, 2),
        'anomalies': anomalies,
        'instrument_statistics': detector.get_all_statistics(),
        'stateful_mode': existing_detector is not None,
    }


def analyze_trends(
    logs: list[dict[str, Any]],
    window_minutes: int = 60
) -> dict[str, Any]:
    """Analyze trends (slope, direction) in instrument readings per tag."""
    by_tag: dict[str, list] = defaultdict(list)
    for log in logs:
        if log.get('tag_number') and log.get('value') is not None:
            ts = _parse_timestamp(log.get('timestamp'))
            try:
                by_tag[log['tag_number']].append({'value': float(log['value']), 'timestamp': ts})
            except (ValueError, TypeError):
                continue

    trends: dict[str, Any] = {}
    for tag, readings in by_tag.items():
        if len(readings) < 3:
            trends[tag] = {'trend': 'insufficient_data', 'points': len(readings)}
            continue

        readings.sort(key=lambda x: x['timestamp'] or datetime.min)
        values = [r['value'] for r in readings]
        x = np.arange(len(values))
        slope, _ = np.polyfit(x, values, 1)
        mean_val = np.mean(values)
        norm_slope = (slope / abs(mean_val) * 100) if mean_val != 0 else 0

        if abs(norm_slope) < 0.5:
            trend_type = 'stable'
        elif norm_slope > 0:
            trend_type = 'increasing' if norm_slope < 2 else 'rapidly_increasing'
        else:
            trend_type = 'decreasing' if norm_slope > -2 else 'rapidly_decreasing'

        trends[tag] = {
            'trend': trend_type,
            'slope': round(slope, 4),
            'normalized_slope_pct': round(norm_slope, 2),
            'mean': round(mean_val, 3),
            'std': round(float(np.std(values)), 3),
            'min': round(min(values), 3),
            'max': round(max(values), 3),
            'points': len(values)
        }

        # P0.x FIX: Yield after each tag analysis to allow concurrent HTTP/Health requests
        time.sleep(0)

    return {'success': True, 'instrument_count': len(trends), 'trends': trends}


# ============================================================================
# CONSTANTS
# ============================================================================

DEFAULT_POLL_INTERVAL = 30  # seconds
MIN_POLL_INTERVAL = 10      # minimum allowed poll interval
MAX_SCAN_LINES = 10_000     # max lines to process per poll cycle

SOURCE_TYPE_FILE = "file"   # server-accessible file path (CSV or JSON/JSONL)


# ============================================================================
# MONITOR SERVICE SINGLETON
# ============================================================================

class LogMonitorService:
    """
    Singleton background service that continuously polls configured log sources.

    Each source has its own polling state tracked in MongoDB (last_offset, last_mtime).
    A single background thread iterates over all active sources on each tick.
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True

        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._running = False

        # Persistent stateful detector — baseline survives across poll cycles.
        # Reusing the same instance means the sliding-window statistics for every
        # tag accumulate over time instead of being obliterated every 30 seconds.
        self._detector = AnomalyDetector(
            zscore_threshold=3.0,
            iqr_multiplier=1.5,
            roc_threshold=0.5,
            stuck_duration_minutes=30.0,
            buffer_size=200,   # larger buffer for long-running service
        )

        # Cache sources in memory to avoid DB hit on every tick
        self._sources_cache: dict[str, dict] = {}
        self._cache_lock = threading.Lock()
        self._last_cache_refresh = 0.0
        self._cache_ttl = 60  # seconds

        # Watermark for instrument_logs continuous polling (Phase 2)
        self._last_instrument_logs_check: datetime = datetime.now(UTC)

        logger.info("[LOG_MONITOR] LogMonitorService initialized")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self):
        """Start the background monitoring thread."""
        if self._running:
            return
        self._stop_event.clear()
        self._running = True
        self._thread = threading.Thread(
            target=self._monitor_loop,
            name="LogMonitorThread",
            daemon=True
        )
        self._thread.start()
        logger.info("[LOG_MONITOR] Background monitoring thread started")

    def stop(self):
        """Signal the background thread to stop and wait for it."""
        if not self._running:
            return
        self._stop_event.set()
        self._running = False
        if self._thread:
            self._thread.join(timeout=10)
        logger.info("[LOG_MONITOR] Background monitoring thread stopped")

    @property
    def is_running(self) -> bool:
        return self._running and (self._thread is not None) and self._thread.is_alive()

    # ------------------------------------------------------------------
    # Source management
    # ------------------------------------------------------------------

    def add_source(
        self,
        name: str,
        path: str,
        source_type: str = SOURCE_TYPE_FILE,
        poll_interval: int = DEFAULT_POLL_INTERVAL,
        asset_id: str | None = None,
        user_id: str | None = None,
        column_overrides: dict | None = None,
    ) -> dict[str, Any]:
        """
        Register a new log source and persist it to MongoDB.

        Args:
            name: Human-readable label for the source
            path: Server-side file path (CSV or JSON/JSONL)
            source_type: 'file' (only type currently supported)
            poll_interval: Seconds between polls (min 10)
            asset_id: Optional asset to link logs to
            user_id: Owner user ID
            column_overrides: Optional dict of {field: column_name} overrides

        Returns:
            Dict with success, source_id
        """
        try:
            from common.infra.mongodb_config import Collections, get_mongodb_connection

            if source_type != SOURCE_TYPE_FILE:
                return {"success": False, "error": f"Unsupported source type: {source_type}"}

            if not os.path.isabs(path):
                return {"success": False, "error": "Path must be an absolute server-side path"}

            poll_interval = max(MIN_POLL_INTERVAL, int(poll_interval))

            conn = get_mongodb_connection()
            db = conn.get("database")
            if db is None:
                return {"success": False, "error": "Database connection failed"}

            collection = db[Collections.MONITOR_SOURCES]

            # Check for duplicate path per user
            existing = collection.find_one({"path": path, "user_id": user_id})
            if existing:
                return {
                    "success": False,
                    "error": f"A source for path '{path}' already exists"
                }

            now = datetime.now(UTC)
            doc = {
                "name": name,
                "path": path,
                "source_type": source_type,
                "poll_interval": poll_interval,
                "asset_id": asset_id,
                "user_id": user_id,
                "column_overrides": column_overrides or {},
                "enabled": True,
                "created_at": now,
                "updated_at": now,
                # Poll state
                "last_polled_at": None,
                "last_byte_offset": 0,
                "last_mtime": 0.0,
                "total_entries_ingested": 0,
                "last_error": None,
                "last_anomaly_count": 0,
            }

            result = collection.insert_one(doc)
            source_id = str(result.inserted_id)

            # Invalidate cache
            self._invalidate_cache()

            logger.info(f"[LOG_MONITOR] Added source '{name}' -> {path} (id={source_id})")
            return {"success": True, "source_id": source_id}

        except Exception as e:
            logger.exception(f"[LOG_MONITOR] Failed to add source: {e}")
            return {"success": False, "error": str(e)}

    def remove_source(self, source_id: str, user_id: str) -> dict[str, Any]:
        """Remove a source (stops monitoring it)."""
        try:
            from bson import ObjectId

            from common.infra.mongodb_config import Collections, get_mongodb_connection

            conn = get_mongodb_connection()
            db = conn.get("database")
            if db is None:
                return {"success": False, "error": "Database connection failed"}

            collection = db[Collections.MONITOR_SOURCES]
            result = collection.delete_one({"_id": ObjectId(source_id), "user_id": user_id})
            if result.deleted_count == 0:
                return {"success": False, "error": "Source not found"}

            self._invalidate_cache()
            logger.info(f"[LOG_MONITOR] Removed source {source_id}")
            return {"success": True}

        except Exception as e:
            logger.exception(f"[LOG_MONITOR] Failed to remove source: {e}")
            return {"success": False, "error": str(e)}

    def toggle_source(self, source_id: str, user_id: str, enabled: bool) -> dict[str, Any]:
        """Enable or disable a source."""
        try:
            from bson import ObjectId

            from common.infra.mongodb_config import Collections, get_mongodb_connection

            conn = get_mongodb_connection()
            db = conn.get("database")
            if db is None:
                return {"success": False, "error": "Database connection failed"}

            collection = db[Collections.MONITOR_SOURCES]
            result = collection.update_one(
                {"_id": ObjectId(source_id), "user_id": user_id},
                {"$set": {"enabled": enabled, "updated_at": datetime.now(UTC)}}
            )
            if result.matched_count == 0:
                return {"success": False, "error": "Source not found"}

            self._invalidate_cache()
            return {"success": True, "enabled": enabled}

        except Exception as e:
            logger.exception(f"[LOG_MONITOR] Failed to toggle source: {e}")
            return {"success": False, "error": str(e)}

    def list_sources(self, user_id: str | None = None) -> list[dict]:
        """Return all sources, optionally filtered by user_id."""
        try:
            from common.infra.mongodb_config import Collections, get_mongodb_connection

            conn = get_mongodb_connection()
            db = conn.get("database")
            if db is None:
                return []

            query = {}
            if user_id:
                try:
                    uid_int = int(user_id)
                    query = {"$or": [{"user_id": user_id}, {"user_id": uid_int}]}
                except (ValueError, TypeError):
                    query = {"user_id": user_id}

            sources = list(
                db[Collections.MONITOR_SOURCES].find(query).sort("created_at", -1)
            )
            for s in sources:
                s["_id"] = str(s["_id"])
                # Serialize datetimes
                for key in ("created_at", "updated_at", "last_polled_at"):
                    if isinstance(s.get(key), datetime):
                        s[key] = s[key].isoformat()
            return sources

        except Exception as e:
            logger.exception(f"[LOG_MONITOR] Failed to list sources: {e}")
            return []

    def get_status(self) -> dict[str, Any]:
        """Return overall monitoring service status."""
        active_sources = [s for s in self._all_sources() if s.get("enabled")]
        return {
            "running": self.is_running,
            "active_sources": len(active_sources),
            "total_sources": len(self._all_sources()),
        }

    # ------------------------------------------------------------------
    # Background loop
    # ------------------------------------------------------------------

    def _monitor_loop(self):
        """Main loop: iterate active sources and poll each one, plus instrument_logs."""
        logger.info("[LOG_MONITOR] Monitor loop started")
        while not self._stop_event.is_set():
            try:
                sources = self._load_active_sources()
                if sources:
                    logger.debug(f"[LOG_MONITOR] Polling {len(sources)} active sources")
                    for source in sources:
                        if self._stop_event.is_set():
                            break
                        self._poll_source(source)

                # Always poll instrument_logs for simulator / external-API data
                if not self._stop_event.is_set():
                    self._poll_instrument_logs()

            except Exception as e:
                logger.exception(f"[LOG_MONITOR] Error in monitor loop: {e}")

            # Sleep in small increments so stop signal is responsive
            for _ in range(DEFAULT_POLL_INTERVAL):
                if self._stop_event.is_set():
                    break
                time.sleep(1)

        logger.info("[LOG_MONITOR] Monitor loop exited")

    def _load_active_sources(self) -> list[dict]:
        """Load enabled sources from MongoDB (cached)."""
        try:
            from common.infra.mongodb_config import Collections, get_mongodb_connection

            conn = get_mongodb_connection()
            db = conn.get("database")
            if db is None:
                return []
            sources = list(db[Collections.MONITOR_SOURCES].find({"enabled": True}))
            return sources
        except Exception as e:
            logger.error(f"[LOG_MONITOR] Failed to load sources: {e}")
            return []

    def _all_sources(self) -> list[dict]:
        """Load all sources (enabled or not) for status reporting."""
        try:
            from common.infra.mongodb_config import Collections, get_mongodb_connection

            conn = get_mongodb_connection()
            db = conn.get("database")
            if db is None:
                return []
            return list(db[Collections.MONITOR_SOURCES].find({}))
        except Exception:
            return []

    def _poll_source(self, source: dict):
        """
        Poll a single file-based log source, parse new data, run anomaly detection.
        """
        source_id = source.get("_id")
        path = source.get("path", "")
        poll_interval = source.get("poll_interval", DEFAULT_POLL_INTERVAL)

        # Respect per-source poll interval
        last_polled = source.get("last_polled_at")
        if last_polled is not None:
            if isinstance(last_polled, str):
                try:
                    last_polled = datetime.fromisoformat(last_polled)
                except Exception:
                    last_polled = None

            if last_polled and (datetime.now(UTC) - last_polled).total_seconds() < poll_interval:
                return  # Not yet time to poll this source

        try:
            new_entries, new_offset = self._read_new_entries(source)
        except Exception as e:
            self._update_source_state(source_id, error=str(e))
            logger.error(f"[LOG_MONITOR] Error reading source '{source.get('name')}': {e}")
            return

        if not new_entries:
            self._update_source_state(source_id, offset=new_offset)
            return

        logger.info(
            f"[LOG_MONITOR] Source '{source.get('name')}': {len(new_entries)} new entries"
        )

        # Ingest new entries
        try:
            from common.ai.rag.assets_rag import ingest_instrument_logs

            ingest_result = ingest_instrument_logs(
                user_id=str(source.get("user_id", "system")),
                logs_data=new_entries,
                asset_id=source.get("asset_id"),
                source_file=os.path.basename(path),
                generate_embeddings=False,  # Skip embeddings for speed in continuous mode
            )
            ingested = ingest_result.get("count", 0)
        except Exception as e:
            logger.error(f"[LOG_MONITOR] Ingestion error for source '{source.get('name')}': {e}")
            ingested = 0

        # Run anomaly detection on the new batch using the shared stateful detector
        anomaly_count = 0
        if new_entries:
            try:
                anomaly_result = detect_anomalies_batch(
                    new_entries,
                    existing_detector=self._detector,  # stateful — preserves baseline
                )
                anomaly_count = anomaly_result.get("anomalies_detected", 0)
                if anomaly_count:
                    logger.warning(
                        f"[LOG_MONITOR] Source '{source.get('name')}': "
                        f"{anomaly_count} anomalies detected in new batch"
                    )
                    self._persist_anomaly_results(
                        anomaly_result,
                        user_id=str(source.get("user_id", "system")),
                        source_name=source.get("name", os.path.basename(path)),
                    )
            except Exception as e:
                logger.error(f"[LOG_MONITOR] Anomaly detection error: {e}")

        # Persist updated state
        self._update_source_state(
            source_id,
            offset=new_offset,
            total_delta=ingested,
            anomaly_count=anomaly_count,
            clear_error=True,
        )

    def _read_new_entries(self, source: dict) -> tuple[list[dict], int]:
        """
        Read only new lines/bytes from a file source since last poll.

        Returns:
            (list_of_parsed_entries, new_byte_offset)
        """
        path = source.get("path", "")

        if not os.path.exists(path):
            raise FileNotFoundError(f"Log source path not found: {path}")

        current_mtime = os.path.getmtime(path)
        last_mtime = source.get("last_mtime", 0.0)
        last_offset = source.get("last_byte_offset", 0)

        # File not modified since last poll
        if current_mtime == last_mtime and last_offset > 0:
            return [], last_offset

        file_size = os.path.getsize(path)

        # File was truncated/rotated - reset
        if last_offset > file_size:
            logger.info(f"[LOG_MONITOR] File rotated or truncated: {path}, resetting offset")
            last_offset = 0

        if last_offset == file_size:
            return [], last_offset  # No new data

        # Read only the new portion
        with open(path, "rb") as f:
            f.seek(last_offset)
            new_bytes = f.read(MAX_SCAN_LINES * 512)  # cap memory usage
            new_offset = f.tell()

        if not new_bytes.strip():
            return [], new_offset

        ext = os.path.splitext(path)[1].lower()
        source.get("column_overrides") or {}

        if ext == ".csv":
            # Prepend header if not at start of file
            if last_offset > 0:
                new_bytes = _prepend_csv_header(path, new_bytes)
            result = parse_csv_logs(new_bytes, os.path.basename(path))
        elif ext in (".json", ".jsonl"):
            result = parse_json_logs(new_bytes, os.path.basename(path))
        else:
            raise ValueError(f"Unsupported file extension: {ext}")

        if not result.get("success"):
            raise ValueError(result.get("error", "Parse failed"))

        return result.get("logs", []), new_offset

    def _update_source_state(
        self,
        source_id,
        offset: int | None = None,
        total_delta: int = 0,
        anomaly_count: int = 0,
        error: str | None = None,
        clear_error: bool = False,
    ):
        """Persist poll state back to MongoDB."""
        try:
            from bson import ObjectId

            from common.infra.mongodb_config import Collections, get_mongodb_connection

            conn = get_mongodb_connection()
            db = conn.get("database")
            if db is None:
                return

            update: dict[str, Any] = {"last_polled_at": datetime.now(UTC)}
            if offset is not None:
                update["last_byte_offset"] = offset
            if total_delta:
                update["$inc"] = {"total_entries_ingested": total_delta}
            if anomaly_count:
                update["last_anomaly_count"] = anomaly_count
            if error:
                update["last_error"] = error
            if clear_error:
                update["last_error"] = None

            # Separate $set from $inc
            inc_op = update.pop("$inc", None)

            ops: dict[str, Any] = {"$set": update}
            if inc_op:
                ops["$inc"] = inc_op

            oid = ObjectId(source_id) if not isinstance(source_id, ObjectId) else source_id
            db[Collections.MONITOR_SOURCES].update_one({"_id": oid}, ops)

        except Exception as e:
            logger.error(f"[LOG_MONITOR] Failed to update source state: {e}")

    # ------------------------------------------------------------------
    # Cache helpers
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Anomaly result persistence
    # ------------------------------------------------------------------

    def _persist_anomaly_results(
        self,
        anomaly_result: dict[str, Any],
        user_id: str,
        source_name: str,
    ) -> None:
        """Write detected anomaly records to the anomaly_results MongoDB collection."""
        anomalies = anomaly_result.get("anomalies", [])
        if not anomalies:
            return
        try:
            from common.infra.mongodb_config import get_mongodb_connection

            conn = get_mongodb_connection()
            db = conn.get("database")
            if db is None:
                return

            now = datetime.now(UTC)
            docs = []
            for a in anomalies:
                score = float(a.get("anomaly_score", 0))
                severity = (
                    "critical" if score > 0.8
                    else "warning" if score > 0.5
                    else "info"
                )
                docs.append({
                    "user_id": user_id,
                    "tag_number": a.get("tag_number"),
                    "value": a.get("value"),
                    "timestamp": a.get("timestamp"),
                    "anomaly_type": a.get("anomaly_type"),
                    "anomaly_score": score,
                    "details": a.get("details", {}),
                    "severity": severity,
                    "source": source_name,
                    "detected_at": now,
                    "anomaly_rate": anomaly_result.get("anomaly_rate", 0),
                    "acknowledged": False,
                })

            if docs:
                db["anomaly_results"].insert_many(docs)
                logger.info(
                    f"[LOG_MONITOR] Persisted {len(docs)} anomaly records "
                    f"(source={source_name})"
                )
        except Exception as e:
            logger.error(f"[LOG_MONITOR] Failed to persist anomaly results: {e}")

    # ------------------------------------------------------------------
    # instrument_logs continuous polling (Phase 2)
    # ------------------------------------------------------------------

    def _poll_instrument_logs(self) -> None:
        """
        Check instrument_logs for entries written since last poll
        (simulator output + external API ingest), run anomaly detection,
        and persist any anomalies found.
        """
        try:
            from common.infra.mongodb_config import get_mongodb_connection

            conn = get_mongodb_connection()
            db = conn.get("database")
            if db is None:
                return

            since = self._last_instrument_logs_check
            now = datetime.now(UTC)

            new_docs = list(
                db["instrument_logs"]
                .find({
                    "source": {"$in": ["live_simulation", "external_api"]},
                    "ingested_at": {"$gt": since},
                })
                .sort("ingested_at", 1)
                .limit(5000)
            )

            self._last_instrument_logs_check = now

            if not new_docs:
                return

            logger.info(
                f"[LOG_MONITOR] instrument_logs: {len(new_docs)} new entries since last poll"
            )

            # Convert to the format detect_anomalies_batch expects
            entries = []
            user_ids: set[str] = set()
            for doc in new_docs:
                ts = doc.get("timestamp")
                entries.append({
                    "tag_number": doc.get("tag_number", ""),
                    "value": doc.get("value"),
                    "timestamp": (
                        ts.isoformat() if isinstance(ts, datetime) else ts
                    ),
                })
                uid = doc.get("user_id")
                if uid:
                    user_ids.add(str(uid))

                # P0.x FIX: Yield during heavy loop to allow health checks
                if len(entries) % 100 == 0:
                    time.sleep(0)

            anomaly_result = detect_anomalies_batch(
                entries,
                existing_detector=self._detector,   # stateful — cross-batch memory
            )
            anomaly_count = anomaly_result.get("anomalies_detected", 0)

            if anomaly_count:
                logger.warning(
                    f"[LOG_MONITOR] instrument_logs: {anomaly_count} anomalies detected"
                )
                primary_user = next(iter(user_ids), "system")
                self._persist_anomaly_results(
                    anomaly_result,
                    user_id=primary_user,
                    source_name="instrument_logs",
                )

        except Exception as e:
            logger.error(f"[LOG_MONITOR] _poll_instrument_logs error: {e}")

    # ------------------------------------------------------------------
    # Cache helpers
    # ------------------------------------------------------------------

    def _invalidate_cache(self):
        with self._cache_lock:
            self._last_cache_refresh = 0.0
            self._sources_cache = {}


def _prepend_csv_header(path: str, new_bytes: bytes) -> bytes:
    """Read the header row from the beginning of a CSV and prepend it to new_bytes."""
    try:
        with open(path, "rb") as f:
            header_line = f.readline()
        return header_line + new_bytes
    except Exception:
        return new_bytes


# ============================================================================
# MODULE-LEVEL SINGLETON ACCESSOR
# ============================================================================

_monitor_service: LogMonitorService | None = None


def get_monitor_service() -> LogMonitorService:
    """Get or create the singleton LogMonitorService."""
    global _monitor_service
    if _monitor_service is None:
        _monitor_service = LogMonitorService()
    return _monitor_service


def calculate_health_score(
    anomaly_result: dict[str, Any],
    trend_result: dict[str, Any],
) -> dict[str, Any]:
    """
    Calculate an asset health score (0-100) from anomaly detection and trend analysis.

    Returns:
        dict with health_score, health_status, trend_direction, factors
    """
    score = 100.0
    factors = []

    # --- Factor 1: Anomaly rate ---
    anomaly_rate = anomaly_result.get('anomaly_rate', 0.0)
    anomalies_detected = anomaly_result.get('anomalies_detected', 0)

    if anomaly_rate > 20:
        penalty = min(40, anomaly_rate * 1.5)
        score -= penalty
        factors.append(f"High anomaly rate ({anomaly_rate:.1f}%): -{penalty:.0f}")
    elif anomaly_rate > 5:
        penalty = anomaly_rate * 1.0
        score -= penalty
        factors.append(f"Moderate anomaly rate ({anomaly_rate:.1f}%): -{penalty:.0f}")
    elif anomaly_rate > 0:
        penalty = anomaly_rate * 0.5
        score -= penalty
        factors.append(f"Low anomaly rate ({anomaly_rate:.1f}%): -{penalty:.0f}")

    # --- Factor 2: Trend direction ---
    trends = trend_result.get('trends', {})
    degrading_count = 0
    overall_trend = 'stable'

    for tag, trend_info in trends.items():
        trend_type = trend_info.get('trend', 'stable')
        if trend_type in ('rapidly_increasing', 'rapidly_decreasing'):
            degrading_count += 1
        elif trend_type in ('increasing', 'decreasing'):
            # Mild change — could be good or bad depending on context
            # Treat as mild concern
            degrading_count += 0.5

    if degrading_count > 0 and len(trends) > 0:
        degrading_ratio = degrading_count / len(trends)
        penalty = degrading_ratio * 20
        score -= penalty
        overall_trend = 'degrading'
        factors.append(f"Degrading trends ({degrading_count}/{len(trends)} instruments): -{penalty:.0f}")
    elif len(trends) > 0:
        overall_trend = 'stable'

    # --- Factor 3: Anomaly severity (if available) ---
    anomalies = anomaly_result.get('anomalies', [])
    severe_count = sum(1 for a in anomalies if a.get('anomaly_score', 0) > 0.8)
    if severe_count > 0:
        penalty = min(20, severe_count * 5)
        score -= penalty
        factors.append(f"Severe anomalies ({severe_count}): -{penalty:.0f}")

    # Clamp score
    score = max(0, min(100, score))

    # Determine status
    if score >= 80:
        status = 'healthy'
    elif score >= 50:
        status = 'warning'
    else:
        status = 'critical'

    return {
        'health_score': round(score, 1),
        'health_status': status,
        'trend_direction': overall_trend,
        'active_anomalies': anomalies_detected,
        'factors': factors,
    }


def start_monitoring():
    """Start the global monitoring service (call once at app startup)."""
    svc = get_monitor_service()
    svc.start()
    return svc

