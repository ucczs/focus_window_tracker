# Focus Window tracker

<img src="./media/fwt_logo.png" alt="drawing" width="200"/>


Focus Window Tracker monitors which window is active on your desktop and logs every focus change to a CSV file. Each log entry captures:

- **timestamp** — when the focus change occurred (ISO 8601)
- **pid** — process ID of the owning application
- **program** — executable name of the application (e.g. `firefox`, `alacritty`, `code`)
- **window_title** — title of the focused window at that moment

The tracker polls the active window via EWMH (Extended Window Manager Hints) and only writes a new row when the focused window actually changes, keeping the log compact. Log files are automatically rotated once they reach a configurable size limit (default 10 MB).

# Setup to run always in the background

## Create service file

A ready-made service file is shown below at `window-tracker.service`. Edit the paths inside it to match your setup, then install it as a **user** systemd service (no root required):

```bash
# 1. Copy the service file to the systemd user unit directory
mkdir -p ~/.config/systemd/user
nano window-tracker.service ~/.config/systemd/user/window-tracker.service
```

The service file looks like this for reference:

```ini
[Unit]
Description=Window focus tracker
After=graphical-session.target

[Service]
ExecStart=/home/<user>/git/activity_tracker_linux/.venv/bin/python3 /home/<user>/activity_tracker_linux/tracker.py --log-file /home/<user>/activity_tracker_linux/logs/AppsInFocus-000001.csv
Restart=on-failure
RestartSec=5
Environment=DISPLAY=:0
PassEnvironment=DISPLAY XAUTHORITY

[Install]
WantedBy=graphical-session.target
```

## Enable and start the service

Import the display environment into systemd from your login session. Add this to ~/.bash_profile (or ~/.profile):
```bash
systemctl --user import-environment DISPLAY XAUTHORITY
```


Add service to systemd
```bash
# Reload systemd so it picks up the new file
systemctl --user daemon-reload

# Enable the service so it starts automatically on login
systemctl --user enable window-tracker.service

# Start it immediately (without logging out and back in)
systemctl --user start window-tracker.service
```


## Check status and logs

```bash
# View current status
systemctl --user status window-tracker.service

# Follow live logs
journalctl --user -u window-tracker.service -f
```

## Reload after script changes

When you edit `tracker.py` (or any other script file), a simple restart is enough — no need to touch the service file:

```bash
systemctl --user restart window-tracker.service
```

If you also edited the service file itself (e.g. changed CLI arguments or paths), reload the daemon first:

```bash
systemctl --user daemon-reload
systemctl --user restart window-tracker.service
```

Confirm everything came back up cleanly:

```bash
systemctl --user status window-tracker.service
```

## Stop or disable the service

```bash
# Stop without disabling (will start again on next login)
systemctl --user stop window-tracker.service

# Stop and prevent it from starting on login
systemctl --user disable --now window-tracker.service
```