"""Theme system for HeatSync GUI."""

import os
import json
from typing import Dict, Any

# Current active theme
_ACTIVE_THEME = None


class Theme:
    """Represents a color theme."""
    
    def __init__(self, name: str, data: Dict[str, Any]):
        """Initialize theme with name and color data."""
        self.name = name
        self.data = data
    
    def __getattr__(self, key: str) -> str:
        """Get color by attribute name."""
        if key.startswith('_'):
            return super().__getattribute__(key)
        return self.data.get(key, "#ffffff")
    
    def __getitem__(self, key: str) -> str:
        """Get color by key."""
        return self.data.get(key, "#ffffff")


def load_theme(name: str) -> Theme:
    """Load a theme by name from the themes directory."""
    theme_path = os.path.join(
        os.path.dirname(__file__),
        f"{name}.json"
    )
    
    if not os.path.exists(theme_path):
        raise ValueError(f"Theme '{name}' not found at {theme_path}")
    
    with open(theme_path, 'r') as f:
        data = json.load(f)
    
    return Theme(name, data)


def get_active_theme() -> Theme:
    """Get the currently active theme."""
    global _ACTIVE_THEME
    if _ACTIVE_THEME is None:
        _ACTIVE_THEME = load_theme("lcars")
    return _ACTIVE_THEME


def set_active_theme(name: str) -> Theme:
    """Set the active theme by name."""
    global _ACTIVE_THEME
    _ACTIVE_THEME = load_theme(name)
    return _ACTIVE_THEME


def list_available_themes() -> list:
    """List all available themes."""
    themes_dir = os.path.dirname(__file__)
    themes = []
    
    for file in os.listdir(themes_dir):
        if file.endswith('.json') and not file.startswith('_'):
            themes.append(file[:-5])  # Remove .json extension
    
    return sorted(themes)
