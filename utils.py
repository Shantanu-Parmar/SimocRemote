# simoc_dashboard/utils.py
import os
import io
import json
import datetime
import pandas as pd
from collections import deque
import re
import logging

logger = logging.getLogger(__name__)

# Regex to extract sensor name from filename like SRS_SRS_SCD-30.jsonl
SENSOR_PATTERN = re.compile(r'^[^_]+_[^_]+_(.+)\.jsonl$')


def discover_sensors(log_dir: str, blocked_substrings: list) -> dict:
    """
    Discover all valid sensors from JSONL files in the log directory.

    Args:
        log_dir (str): Path to directory containing sensor log files.
        blocked_substrings (list): List of substrings to block (e.g., ["mock"]).

    Returns:
        dict: Mapping of sensor_name → {file, params, colors}
    """
    sensors = {}
    if not os.path.exists(log_dir):
        logger.warning(f"Log directory does not exist: {log_dir}")
        return sensors

    base_colors = [
        "#FF8C00", "#FF4444", "#4488FF", "#FF66AA", "#44AA44",
        "#FFFF44", "#AA44FF", "#44FFFF", "#FFAA44", "#88FF88"
    ]

    for filename in os.listdir(log_dir):
        match = SENSOR_PATTERN.match(filename)
        if not match:
            continue

        sensor_name = match.group(1)

        # Block sensors with forbidden substrings
        if any(blocked in sensor_name.lower() for blocked in blocked_substrings):
            logger.info(f"Blocked sensor (matches block list): {sensor_name}")
            continue

        filepath = os.path.join(log_dir, filename)

        params = set()
        try:
            with open(filepath, 'r') as f:
                for _ in range(30):  # Read first 30 lines to detect params
                    line = f.readline()
                    if not line.strip():
                        continue
                    try:
                        entry = json.loads(line)
                        if 'timestamp' in entry:
                            params = {k for k in entry.keys() if k not in ['timestamp', 'n']}
                            if params:
                                break
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            logger.error(f"Error reading file {filename}: {e}")
            continue

        
        if params:
            param_list = sorted(list(params))

            # Special handling for BNO085 or MOCK_IMU: keep ONLY linear_accel_* and rename to acc_x/y/z
            # Special handling for BNO085 or MOCK_IMU: keep ONLY linear_accel_x/y/z (original names), drop everything else
            if 'BNO085' in sensor_name.upper() or 'MOCK_IMU' in sensor_name.upper():
                keep_params = {'linear_accel_x', 'linear_accel_y', 'linear_accel_z'}
                param_list = [p for p in param_list if p in keep_params]  # drop all others, keep original names
            assigned_colors = []
            for p in param_list:
                if p.lower() == 'co2':
                    assigned_colors.append("#00FF00")  # Bright green for CO₂
                else:
                    assigned_colors.append(base_colors[len(assigned_colors) % len(base_colors)])

            sensors[sensor_name] = {
                "file": filename,
                "params": param_list,
                "colors": assigned_colors
            }
            logger.info(f"Discovered sensor: {sensor_name} with params {param_list}")


    return dict(sorted(sensors.items()))


def get_timestamp(line: str) -> datetime.datetime:
    """Extract and parse timestamp from a JSON line."""
    try:
        entry = json.loads(line)
        return datetime.datetime.strptime(entry['timestamp'], '%Y-%m-%d %H:%M:%S.%f')
    except Exception:
        return datetime.datetime.min


def find_start_offset(f, target: datetime.datetime, lo=0, hi=None) -> int:
    """Binary search for first line >= target timestamp."""
    if hi is None:
        f.seek(0, 2)
        hi = f.tell()
    while lo < hi:
        mid = (lo + hi) // 2
        f.seek(mid)
        f.readline()  # Skip partial line
        line = f.readline()
        if not line:
            hi = mid
            continue
        if get_timestamp(line) < target:
            lo = f.tell()
        else:
            hi = mid
    return lo


def find_end_offset(f, target: datetime.datetime, lo=0, hi=None) -> int:
    """Binary search for first line > target timestamp."""
    if hi is None:
        f.seek(0, 2)
        hi = f.tell()
    while lo < hi:
        mid = (lo + hi) // 2
        f.seek(mid)
        f.readline()
        line = f.readline()
        if not line:
            hi = mid
            continue
        if get_timestamp(line) <= target:
            lo = f.tell()
        else:
            hi = mid
    return lo


def get_data_in_range(filepath: str, start: datetime.datetime, end: datetime.datetime) -> list:
    """
    Retrieve all data entries within a time range from a JSONL file.

    Args:
        filepath (str): Path to the JSONL file.
        start (datetime): Start of range (inclusive).
        end (datetime): End of range (inclusive).

    Returns:
        list: List of parsed JSON entries.
    """
    if not os.path.exists(filepath):
        logger.warning(f"Data file not found: {filepath}")
        return []

    data = []
    try:
        with open(filepath, 'r') as f:
            start_offset = find_start_offset(f, start)
            end_offset = find_end_offset(f, end, lo=start_offset)
            f.seek(start_offset)
            while f.tell() < end_offset:
                line = f.readline()
                if not line.strip():
                    continue
                try:
                    entry = json.loads(line)
                    ts = datetime.datetime.strptime(entry['timestamp'], '%Y-%m-%d %H:%M:%S.%f')
                    if start <= ts <= end:
                        data.append(entry)
                except (json.JSONDecodeError, ValueError, KeyError):
                    continue
    except Exception as e:
        logger.error(f"Error reading range from {filepath}: {e}")

    return data


def get_decimated_data(filepath: str, num_points: int = 1000) -> list:
    """
    Sample approximately num_points evenly spaced entries from file.
    """
    if not os.path.exists(filepath):
        return []

    try:
        with open(filepath, 'r') as f:
            f.seek(0, 2)
            file_size = f.tell()
            if file_size == 0:
                return []
            step = max(1, file_size // num_points)
            data = []
            pos = 0
            for _ in range(num_points):
                f.seek(pos)
                f.readline()  # Align to line start
                line = f.readline()
                if line.strip():
                    try:
                        entry = json.loads(line)
                        data.append(entry)
                    except json.JSONDecodeError:
                        pass
                pos += step
            return data
    except Exception as e:
        logger.error(f"Error decimating data from {filepath}: {e}")
        return []


def get_last_data(filepath: str) -> dict | None:
    """
    Get the most recent entry from a JSONL file.
    """
    if not os.path.exists(filepath):
        return None

    try:
        with open(filepath, 'r') as f:
            lines = deque(f, 1)
            if lines:
                line = lines.pop()
                return json.loads(line)
    except Exception as e:
        logger.error(f"Error reading last data from {filepath}: {e}")
    return None