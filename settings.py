import json
import os

_base_dir = os.path.dirname(os.path.abspath(__file__))
SETTINGS_FILE = 'settings.json'
PROXIES_FILE = 'proxies.txt'

DEFAULTS = {
    "proxies_enabled": False,
    "parallel_enabled": False,
    "parallel_max_workers": 3,
    "ua_rotation_enabled": True,
    "resume_enabled": True,
    "delay_between_requests": [2, 4],
    "retry_attempts": 2,
    "session_rotate_every": 50,
}


def _settings_path():
    return os.path.join(_base_dir, SETTINGS_FILE)


def _proxies_path():
    return os.path.join(_base_dir, PROXIES_FILE)


def load_settings():
    """Load settings from settings.json, merged with defaults for missing keys."""
    settings = dict(DEFAULTS)
    path = _settings_path()
    if os.path.isfile(path):
        try:
            with open(path, 'r') as f:
                stored = json.load(f)
            settings.update(stored)
        except (json.JSONDecodeError, IOError):
            pass
    return settings


def save_settings(data):
    """Save settings dict to settings.json."""
    path = _settings_path()
    with open(path, 'w') as f:
        json.dump(data, f, indent=2)


def get(key):
    """Get a single setting value."""
    return load_settings().get(key, DEFAULTS.get(key))


def load_proxies():
    """Load proxies from proxies.txt. Format: host:port:username:password per line.
    Returns list of dicts with host, port, user, pass keys."""
    path = _proxies_path()
    if not os.path.isfile(path):
        return []
    proxies = []
    with open(path, 'r') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.split(':')
            if len(parts) == 4:
                proxies.append({
                    'host': parts[0],
                    'port': parts[1],
                    'user': parts[2],
                    'pass': parts[3],
                })
            elif len(parts) == 2:
                # host:port without auth
                proxies.append({
                    'host': parts[0],
                    'port': parts[1],
                    'user': None,
                    'pass': None,
                })
    return proxies


def save_proxies(content):
    """Save raw proxy list content to proxies.txt."""
    path = _proxies_path()
    with open(path, 'w') as f:
        f.write(content)


def load_proxies_raw():
    """Load raw proxies.txt content as string."""
    path = _proxies_path()
    if not os.path.isfile(path):
        return ""
    with open(path, 'r') as f:
        return f.read()
