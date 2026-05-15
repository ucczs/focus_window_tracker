import argparse
import csv
import io
import os
import signal
import threading
import time
from datetime import datetime
from pathlib import Path

LOG_DIR = Path(__file__).parent
DEFAULT_MAX_BYTES = 10 * 1024 * 1024

SHUTDOWN_ROW_TEMPLATE = [-1, "shutdown-process", "shutting down"]


def default_log_file():
    counter = 1
    while True:
        candidate = LOG_DIR / f"AppsInFocus-{counter:06d}.csv"
        if not candidate.exists():
            return candidate
        counter += 1


def parse_args():
    parser = argparse.ArgumentParser(
        description="Track active window changes and append them to a log file.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--log-file",
        default=os.environ.get("ACTIVITY_TRACKER_LOG_FILE", str(default_log_file())),
        help="Path to the current log file.",
    )
    parser.add_argument(
        "--max-bytes",
        type=int,
        default=int(os.environ.get("ACTIVITY_TRACKER_MAX_BYTES", DEFAULT_MAX_BYTES)),
        help="Rotate when the current log file would exceed this size. Set to 0 to disable rotation.",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=0.5,
        help="Seconds to wait between active window checks.",
    )
    return parser.parse_args()


def build_rotated_log_path(log_path, timestamp):
    suffix = log_path.suffix
    stem = log_path.stem if suffix else log_path.name
    candidate = log_path.with_name(f"{stem}-{timestamp}{suffix}")
    counter = 1
    while candidate.exists():
        candidate = log_path.with_name(f"{stem}-{timestamp}-{counter}{suffix}")
        counter += 1
    return candidate


def rotate_log_file(log_path):
    if not log_path.exists() or log_path.stat().st_size == 0:
        return
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    archived_path = build_rotated_log_path(log_path, timestamp)
    log_path.rename(archived_path)


CSV_HEADER = ["timestamp", "pid", "program", "window_title"]


class ActivityLogger:
    def __init__(self, log_path, max_bytes):
        self.log_path = log_path
        self.max_bytes = max_bytes
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._open_log_file()

    def _open_log_file(self):
        is_new = not self.log_path.exists() or self.log_path.stat().st_size == 0
        self._raw_file = self.log_path.open("a", encoding="utf-8", newline="")
        self._writer = csv.writer(self._raw_file)
        if is_new:
            self._writer.writerow(CSV_HEADER)
            self._raw_file.flush()

    def _row_bytes(self, row):
        buf = io.StringIO()
        csv.writer(buf).writerow(row)
        return len(buf.getvalue().encode("utf-8"))

    def _should_rotate(self, row):
        if self.max_bytes <= 0 or not self.log_path.exists():
            return False
        return self.log_path.stat().st_size + self._row_bytes(row) > self.max_bytes

    def write(self, row):
        with self._lock:
            if self._should_rotate(row):
                self._raw_file.close()
                rotate_log_file(self.log_path)
                self._open_log_file()
            self._writer.writerow(row)
            self._raw_file.flush()

    def write_shutdown_event(self):
        self.write([datetime.now().isoformat()] + SHUTDOWN_ROW_TEMPLATE)

    def close(self):
        with self._lock:
            self._raw_file.close()

def start_sleep_listener(logger):
    """Subscribe to systemd-logind's PrepareForSleep D-Bus signal (via jeepney).

    Runs in a daemon thread. Writes a shutdown event before each suspend.
    Falls back gracefully if jeepney is not installed.
    """
    try:
        from jeepney import DBus, MatchRule
        from jeepney.io.blocking import open_dbus_connection
    except ModuleNotFoundError:
        print("[tracker] jeepney not found – sleep detection disabled. "
              "Install it with: pip install jeepney")
        return

    def _listen():
        try:
            conn = open_dbus_connection(bus="SYSTEM")
            rule = MatchRule(
                type="signal",
                interface="org.freedesktop.login1.Manager",
                member="PrepareForSleep",
                path="/org/freedesktop/login1",
            )
            conn.send_and_get_reply(DBus().AddMatch(rule))
            while True:
                msg = conn.receive()
                # body is (before,) – True means "about to sleep"
                if msg.body and msg.body[0]:
                    logger.write_shutdown_event()
        except Exception as exc:
            print(f"[tracker] Sleep listener error: {exc}")

    t = threading.Thread(target=_listen, daemon=True, name="sleep-listener")
    t.start()


def create_window_manager():
    try:
        import ewmh
    except ModuleNotFoundError as exc:
        raise SystemExit(
            "Missing dependency. Install packages from requirements.txt before running the tracker."
        ) from exc
    return ewmh.EWMH()


def get_process_name(pid):
    try:
        return Path(f"/proc/{pid}/comm").read_text(encoding="utf-8").strip()
    except OSError:
        return None


def get_active_window_info(window_manager):
    win = window_manager.getActiveWindow()
    if not win:
        return None, None, None
    title = window_manager.getWmName(win)
    pid = window_manager.getWmPid(win)
    program = get_process_name(pid)
    return title, pid, program


def main():
    args = parse_args()
    logger = ActivityLogger(Path(args.log_file).expanduser(), args.max_bytes)

    # Write a shutdown row on SIGTERM (systemd sends this on system shutdown)
    def _sigterm_handler(signum, frame):
        logger.write_shutdown_event()
        logger.close()
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, _sigterm_handler)

    # Write a shutdown row before each suspend/sleep
    start_sleep_listener(logger)

    window_manager = create_window_manager()
    last = None
    try:
        while True:
            title, pid, program = get_active_window_info(window_manager)
            if title != last:
                logger.write([datetime.now().isoformat(), pid, program, title])
                last = title
            time.sleep(args.poll_interval)
    finally:
        logger.close()


if __name__ == "__main__":
    main()