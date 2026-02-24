"""Configuration management for HeatSync."""

import os
import json
from pathlib import Path


def get_config_dir() -> Path:
    """Get the HeatSync config directory."""
    if os.name == 'nt':  # Windows
        config_dir = Path(os.environ.get('APPDATA', Path.home())) / 'HeatSync'
    else:  # Linux/Mac
        config_dir = Path.home() / '.config' / 'heatsync'
    
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir


def get_config_file() -> Path:
    """Get the config file path."""
    return get_config_dir() / 'config.json'


def load_config() -> dict:
    """Load configuration from file."""
    config_file = get_config_file()
    
    if config_file.exists():
        try:
            with open(config_file, 'r') as f:
                return json.load(f)
        except Exception:
            pass
    
    return get_default_config()


def get_default_config() -> dict:
    """Get default configuration."""
    return {
        'theme': 'default',
        'geometry': None,
        'docked': False,
    }


def save_config(config: dict):
    """Save configuration to file."""
    config_file = get_config_file()
    try:
        with open(config_file, 'w') as f:
            json.dump(config, f, indent=2)
    except Exception as e:
        print(f"[WARN] Failed to save config: {e}")


def set_theme(theme_name: str):
    """Set the active theme in config."""
    config = load_config()
    config['theme'] = theme_name
    save_config(config)


def get_theme() -> str:
    """Get the active theme from config."""
    config = load_config()
    return config.get('theme', 'default')
