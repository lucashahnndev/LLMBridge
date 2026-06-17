from __future__ import annotations


def build_local_frontend_origins(*, frontend_host: str, frontend_port: int) -> list[str]:
    hosts = {
        frontend_host.strip(),
        "localhost",
        "127.0.0.1",
        "[::1]",
    }
    return sorted(
        {
            f"http://{host}:{frontend_port}"
            for host in hosts
            if host
        }
    )
