# Switching Themes in HeatSync (Compiled Version)

## Method 1: System Tray Menu (Easiest)

When running HeatSync, right-click the system tray icon and select **"Theme"** to see all available themes:

- **Theme** → *theme_name*

Simply click the desired theme to select it. You'll see a notification confirming the change.

**Note:** The theme will be applied on the next restart.

## Method 2: Configuration File

Themes are saved to your config directory:

- **Windows**: `%APPDATA%\HeatSync\config.json`
- **Linux/Mac**: `~/.config/heatsync/config.json`

To change the theme manually, edit `config.json`:

```json
{
  "theme": "lcars",
  "geometry": null,
  "docked": false
}
```

Change the `"theme"` value to any available theme name (e.g., `"default"`, `"lcars"`), then restart HeatSync.

## Available Themes

- **default** - Original NZXT CAM-style with cool blues and purples
- **lcars** - Star Trek: The Next Generation LCARS style with iconic orange and blue

## Creating Custom Themes

Add new theme JSON files to the `themes/` folder. Each theme requires:

```json
{
  "name": "My Theme",
  "description": "Description here",
  "background": "#000000",
  "card_background": "#0a0a0a",
  "card_border": "#ffffff",
  "text_high": "#ffffff",
  "text_mid": "#cccccc",
  "text_low": "#666666",
  "primary": "#ff0000",
  "secondary": "#00ff00",
  "accent": "#0000ff",
  "success": "#00ff00",
  "warning": "#ffff00",
  "danger": "#ff0000",
  "track_bg": "#1a1a1a",
  "track_border": "#333333"
}
```

Then restart HeatSync to see your new theme in the menu.

## Theme Selection Persistence

Your theme choice is automatically saved and will be restored when you restart HeatSync.
