#!/usr/bin/env python3
"""
Thread-safe file locking utilities for JSON configuration files.
Prevents race conditions when reading/modifying/writing JSON data.
"""

import fcntl
import json
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def locked_json_file(filepath, mode='r'):
    """
    Context manager for thread-safe JSON file operations with file locking.
    
    Args:
        filepath: Path to JSON file
        mode: File mode ('r' for read, 'w' for write, 'r+' for read-modify-write)
    
    Yields:
        Parsed JSON data (for 'r' or 'r+' mode) or file handle (for 'w' mode)
    
    Example usage for reading:
        with locked_json_file('/path/to/file.json', 'r') as data:
            print(data['key'])
    
    Example usage for read-modify-write:
        with locked_json_file('/path/to/file.json', 'r+') as (data, file_handle):
            data['key'] = 'new_value'
            file_handle.seek(0)
            file_handle.truncate()
            json.dump(data, file_handle, indent=2)
    """
    filepath = Path(filepath)
    
    # Ensure parent directory exists
    filepath.parent.mkdir(parents=True, exist_ok=True)
    
    # Create empty JSON file if it doesn't exist (for 'r+' mode)
    if mode == 'r+' and not filepath.exists():
        with open(filepath, 'w') as f:
            json.dump({}, f)
    
    # Open file with appropriate mode
    file_handle = open(filepath, mode)
    
    try:
        # Acquire exclusive or shared lock
        if 'w' in mode or '+' in mode:
            fcntl.flock(file_handle.fileno(), fcntl.LOCK_EX)  # Exclusive lock
        else:
            fcntl.flock(file_handle.fileno(), fcntl.LOCK_SH)  # Shared lock
        
        # Parse JSON for read modes
        if mode in ('r', 'r+'):
            try:
                data = json.load(file_handle)
            except json.JSONDecodeError:
                data = {}
            
            if mode == 'r':
                yield data
            else:  # mode == 'r+'
                yield data, file_handle
        else:  # mode == 'w'
            yield file_handle
            
    finally:
        # Release lock and close file
        fcntl.flock(file_handle.fileno(), fcntl.LOCK_UN)
        file_handle.close()


def load_json_safe(filepath, default=None):
    """
    Safely load JSON file with file locking.
    
    Args:
        filepath: Path to JSON file
        default: Default value if file doesn't exist or is invalid (default: {})
    
    Returns:
        Parsed JSON data or default value
    """
    if default is None:
        default = {}
    
    filepath = Path(filepath)
    if not filepath.exists():
        return default
    
    try:
        with locked_json_file(filepath, 'r') as data:
            return data
    except (IOError, json.JSONDecodeError):
        return default


def save_json_safe(filepath, data):
    """
    Safely save JSON file with file locking.
    
    Args:
        filepath: Path to JSON file
        data: Data to save as JSON
    
    Returns:
        True if successful, False otherwise
    """
    try:
        filepath = Path(filepath)
        filepath.parent.mkdir(parents=True, exist_ok=True)
        
        with locked_json_file(filepath, 'w') as f:
            json.dump(data, f, indent=2)
        return True
    except IOError:
        return False


def update_json_safe(filepath, update_func):
    """
    Safely update JSON file with atomic read-modify-write and file locking.
    
    Args:
        filepath: Path to JSON file
        update_func: Function that takes data dict and modifies it in place
    
    Returns:
        True if successful, False otherwise
    
    Example:
        def add_timestamp(data):
            data['last_modified'] = datetime.now().isoformat()
        
        update_json_safe('/path/to/file.json', add_timestamp)
    """
    try:
        with locked_json_file(filepath, 'r+') as (data, f):
            update_func(data)
            f.seek(0)
            f.truncate()
            json.dump(data, f, indent=2)
        return True
    except (IOError, json.JSONDecodeError):
        return False
