from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass
class ServerConfig:
    host: str = "0.0.0.0"
    port: int = 3001
    database_url: str = ""
    api_key: str = ""
    cors_origins: list[str] = field(default_factory=lambda: ["http://localhost:3001"])
    rate_limit_per_minute: int = 100


def load_server_config(config: dict | None = None) -> ServerConfig:
    srv = (config or {}).get("server", {})
    db = (config or {}).get("database", {})

    return ServerConfig(
        host=os.environ.get("SW_SERVER_HOST", srv.get("host", "0.0.0.0")),
        port=int(os.environ.get("SW_SERVER_PORT", srv.get("port", 3001))),
        database_url=os.environ.get(
            "SW_DATABASE_URL",
            os.environ.get(db.get("url_env", "SW_DATABASE_URL"), ""),
        ),
        api_key=os.environ.get("SW_API_KEY", ""),
        cors_origins=srv.get("cors_origins", ["http://localhost:3001"]),
        rate_limit_per_minute=int(os.environ.get("SW_RATE_LIMIT", 100)),
    )
