"""Load a .env file into the environment (zero dependencies).

Real environment variables always win over .env (standard dotenv behavior), so
you can override any value inline: `OPENAI_MODEL=gpt-4.1 python agent.py ...`.
"""
import os


def load_env(path: str | None = None) -> None:
    here = os.path.dirname(os.path.abspath(__file__))
    path = path or os.path.join(here, ".env")
    if not os.path.exists(path):
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key:
                os.environ.setdefault(key, val)  # real env wins over .env
