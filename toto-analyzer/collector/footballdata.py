"""football-data.co.uk 무료 CSV(키 불필요)로 팀 통계를 만든다.

API-Football 무료 요금제가 막히거나 한도가 찼을 때의 대체 수단이다.
유럽 주요 리그의 경기 결과·xG가 담겨 있어 최근 폼, 홈/원정 득실, 상대전적을 계산할 수 있다.
(부상·라인업은 없음)
"""
from __future__ import annotations

import csv
import io
import time
from datetime import date, datetime
from pathlib import Path

import requests

URL = "https://www.football-data.co.uk/mmz4281/{season}/{div}.csv"
# 베트맨 리그명에 들어가는 단어 → football-data 리그 코드
LEAGUE_KEYS = {
    "프리미어": "E0", "EPL": "E0", "챔피언십": "E1", "라리가": "SP1", "세리에": "I1", "분데스": "D1",
    "리그1": "F1", "리그앙": "F1", "에레디비": "N1", "포르투갈": "P1", "스코틀": "SC0", "스코티시": "SC0",
}


def season_code(d: date, back: int = 0) -> str:
    y = d.year if d.month >= 7 else d.year - 1
    y -= back
    return f"{y % 100:02d}{(y + 1) % 100:02d}"


def _date(s: str) -> date | None:
    for fmt in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(s, fmt).date()
        except (ValueError, TypeError):
            pass
    return None


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


class FootballData:
    def __init__(self, cache_dir: Path, seasons: int = 3, log=print):
        self.cache = cache_dir / "footballdata"
        self.cache.mkdir(parents=True, exist_ok=True)
        self.seasons = seasons
        self.log = log
        self.rows: dict[str, list[dict]] = {}

    def _load(self, div: str, season: str, current: bool) -> list[dict]:
        p = self.cache / f"{div}_{season}.csv"
        ttl = 6 * 3600 if current else 10 ** 9
        if not p.exists() or time.time() - p.stat().st_mtime > ttl:
            try:
                r = requests.get(URL.format(season=season, div=div), timeout=30)
                if r.status_code == 200 and r.content:
                    p.write_bytes(r.content)
                    time.sleep(1)
            except requests.RequestException as e:
                self.log(f"  football-data {div} {season} 받기 실패: {e}")
        if not p.exists():
            return []
        text = p.read_bytes().decode("utf-8-sig", "replace")
        out = []
        for r in csv.DictReader(io.StringIO(text)):
            d = _date(r.get("Date", ""))
            if d and r.get("HomeTeam") and r.get("FTHG") not in (None, ""):
                out.append({"date": d, "home": r["HomeTeam"], "away": r["AwayTeam"],
                            "gh": int(float(r["FTHG"])), "ga": int(float(r["FTAG"])),
                            "xh": _f(r.get("HxG")), "xa": _f(r.get("AxG"))})
        return out

    def div_for(self, league: str) -> str | None:
        lg = league or ""
        if "K리그" in lg or lg.startswith("J"):
            return None
        hits = [k for k in LEAGUE_KEYS if k in lg]
        hits = [k for k in hits if not any(k != o and k in o for o in hits)]
        return LEAGUE_KEYS[hits[0]] if hits else None

    def matches(self, div: str) -> list[dict]:
        if div not in self.rows:
            today = date.today()
            rows = []
            for back in range(self.seasons):
                rows += self._load(div, season_code(today, back), current=(back == 0))
            rows.sort(key=lambda r: r["date"])
            self.rows[div] = rows
        return self.rows[div]

    def teams(self, div: str) -> list[str]:
        rows = self.matches(div)
        recent = rows[-200:]
        return sorted({r["home"] for r in recent} | {r["away"] for r in recent})

    def stats(self, div: str, home: str, away: str) -> dict:
        """API-Football predictions 를 줄인 형태와 같은 구조로 돌려준다 (web 모델이 그대로 사용)."""
        rows = self.matches(div)

        def team(name: str, venue: str) -> dict:
            games = [r for r in rows if name in (r["home"], r["away"])]
            last = games[-5:]
            pts, gf5, ga5, form = 0, 0, 0, ""
            for r in last:
                me_h = r["home"] == name
                f, a = (r["gh"], r["ga"]) if me_h else (r["ga"], r["gh"])
                gf5 += f
                ga5 += a
                res = "W" if f > a else "D" if f == a else "L"
                pts += {"W": 3, "D": 1, "L": 0}[res]
                form += res

            def avg(sub, side):
                # 득점 = 실제 득점과 xG(있으면) 평균. 최근 10경기.
                sub = sub[-10:]
                if not sub:
                    return None, None
                gf, ga = [], []
                for r in sub:
                    me_h = r["home"] == name
                    g_for, g_ag = (r["gh"], r["ga"]) if me_h else (r["ga"], r["gh"])
                    x_for, x_ag = (r["xh"], r["xa"]) if me_h else (r["xa"], r["xh"])
                    gf.append((g_for + x_for) / 2 if x_for is not None else g_for)
                    ga.append((g_ag + x_ag) / 2 if x_ag is not None else g_ag)
                return round(sum(gf) / len(gf), 2), round(sum(ga) / len(ga), 2)

            hf, ha = avg([r for r in games if r["home"] == name], "home")
            af, aa = avg([r for r in games if r["away"] == name], "away")
            tf, ta = avg(games, "total")
            n = len(last)
            return {
                "name": name,
                "last5": {"form": round(pts / (3 * n) * 100) if n else None, "att": None, "def": None,
                          "gf": round(gf5 / n, 2) if n else None, "ga": round(ga5 / n, 2) if n else None},
                "form": form,
                "played": {"home": None, "away": None, "total": len(games)},
                "gf": {"home": hf, "away": af, "total": tf},
                "ga": {"home": ha, "away": aa, "total": ta},
            }

        h2h = [r for r in rows if {r["home"], r["away"]} == {home, away}][-10:][::-1]
        return {
            "percent": {"home": None, "draw": None, "away": None},
            "advice": None,
            "under_over": None,
            "home": team(home, "home"),
            "away": team(away, "away"),
            "comparison": {},
            "h2h": [{"date": r["date"].isoformat(), "home": r["home"], "away": r["away"],
                     "gh": r["gh"], "ga": r["ga"]} for r in h2h],
            "source": "football-data.co.uk",
        }
