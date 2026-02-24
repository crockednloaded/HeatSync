# HeatSync Themes

This directory contains color themes for the HeatSync system monitor GUI.

## Available Themes

### default
The original NZXT CAM-style theme with cool blues and purples.

### lcars
Star Trek: The Next Generation LCARS (Library Computer Access/Retrieval System) inspired theme featuring iconic orange, blue, and yellow colors.

## Creating a Custom Theme

1. Create a new JSON file in this directory with your theme name (e.g., `mytheme.json`)
2. Define all required color properties (see `default.json` for reference)
3. Restart HeatSync to use the theme

## Theme Structure

Each theme JSON file must contain:

- `name`: Display name of the theme
- `description`: Brief description of the theme
- `background`: Main background color
- `card_background`: Card/widget background color
- `card_border`: Card/widget border color
- `text_high`: Primary text color
- `text_mid`: Secondary text color
- `text_low`: Tertiary/dim text color
- `primary`: Primary accent color
- `secondary`: Secondary accent color
- `accent`: Tertiary accent color
- `success`: Success/positive indicator color
- `warning`: Warning indicator color
- `danger`: Danger/critical indicator color
- `track_bg`: Progress bar/track background
- `track_border`: Progress bar/track border

Additional theme-specific colors can also be defined.

## Usage in Code

```python
from themes import get_active_theme, set_active_theme

# Get current theme
theme = get_active_theme()
bg_color = theme.background
text_color = theme.text_high

# Switch theme
set_active_theme("lcars")
theme = get_active_theme()

# List available themes
from themes import list_available_themes
themes = list_available_themes()
```
