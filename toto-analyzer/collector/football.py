"""API-Football(v3) 클라이언트. 무료 요금제는 하루 100회라서 응답을 디스크에 캐시한다."""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import requests

BASE = "https://v3.football.api-sports.io"


class QuotaExceeded(RuntimeError):
    pass


class Football:
    def __init__(self, key: str, cache_dir: Path, timezone: str = "Asia/Seoul"):
        self.key = key
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.timezone = timezone
        self.remaining: int | None = None
        self.calls = 0

    def _get(self, path: str, params: dict, ttl: int) -> list:
        sig = hashlib.sha1(json.dumps([path, params], sort_keys=True).encode()).hexdigest()[:16]
        cache = self.cache_dir / f"{path.strip('/').replace('/', '_')}_{sig}.json"
        if cache.exists() and time.time() - cache.stat().st_mtime < ttl:
            return json.loads(cache.read_text(encoding="utf-8"))
        if self.remaining is not None and self.remaining <= 1:
            raise QuotaExceeded("오늘 API 호출 한도를 모두 사용했습니다.")

        r = requests.get(BASE + path, params=params, headers={"x-apisports-key": self.key}, timeout=20)
        self.calls += 1
        rem = r.headers.get("x-ratelimit-requests-remaining")
        if rem is not None and rem.isdigit():
            self.remaining = int(rem)
        r.raise_for_status()
        body = r.json()
        errors = body.get("errors")
        if errors:
            msg = json.dumps(errors, ensure_ascii=False)
            if "limit" in msg.lower() or "requests" in msg.lower():
                raise QuotaExceeded(msg)
            raise RuntimeError(f"API-Football 오류: {msg}")
        data = body.get("response", [])
        cache.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        time.sleep(6.5)  # 무료 요금제 분당 10회 제한
        return data

    def status(self) -> dict:
        r = requests.get(BASE + "/status", headers={"x-apisports-key": self.key}, timeout=20)
        r.raise_for_status()
        return r.json().get("response", {})

    def fixtures_by_date(self, date: str) -> list:
        return self._get("/fixtures", {"date": date, "timezone": self.timezone}, ttl=3 * 3600)

    def predictions(self, fixture_id: int) -> dict | None:
        res = self._get("/predictions", {"fixture": fixture_id}, ttl=12 * 3600)
        return res[0] if res else None

    def injuries(self, fixture_id: int) -> list:
        return self._get("/injuries", {"fixture": fixture_id}, ttl=3 * 3600)

    def lineups(self, fixture_id: int) -> list:
        # 라인업은 보통 킥오프 20~40분 전에 나온다. 없으면 짧게만 캐시.
        return self._get("/fixtures/lineups", {"fixture": fixture_id}, ttl=15 * 60)
