"""베트맨 경기(한글 팀명)와 API-Football 경기(영문 팀명)를 연결한다.

같은 킥오프 시각(±30분) 후보 중에서 팀 별칭 사전으로 고르고,
별칭이 없으면 리그 + 시각이 유일하게 맞는 경기를 고른다.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path


def _norm(s: str) -> str:
    return re.sub(r"[^0-9a-z가-힣]", "", s.lower())


class Matcher:
    def __init__(self, alias_path: Path):
        data = json.loads(alias_path.read_text(encoding="utf-8"))
        self.teams = {_norm(k): [_norm(v) for v in vs] for k, vs in data.get("teams", {}).items()}
        self.leagues = data.get("leagues", {})

    def _team_score(self, ko: str, en: str) -> float:
        k, e = _norm(ko), _norm(en)
        if not k or not e:
            return 0.0
        if k in self.teams:
            return 1.0 if any(a in e or e in a for a in self.teams[k]) else 0.0
        if re.fullmatch(r"[0-9a-z]+", k):  # 베트맨이 영문으로 쓴 경우
            return 0.9 if (k in e or e in k) else 0.0
        return 0.0

    def _league_ids(self, league: str) -> set[int]:
        hits = [k for k in self.leagues if k.lower() in (league or "").lower()]
        # "K리그1" 안의 "리그1"(리그앙)처럼 더 긴 키에 포함되는 짧은 키는 버린다
        hits = [k for k in hits if not any(k != o and k in o for o in hits)]
        return {i for k in hits for i in self.leagues[k]}

    def match(self, game: dict, fixtures: list[dict]) -> tuple[dict | None, str]:
        ko_time = game.get("kickoff")
        cands = []
        for f in fixtures:
            fdate = f["fixture"]["date"][:16]  # "2026-10-25T23:00"
            if ko_time:
                try:
                    diff = abs((datetime.fromisoformat(fdate) - datetime.fromisoformat(ko_time)).total_seconds())
                except ValueError:
                    continue
                if diff > 30 * 60:
                    continue
            cands.append(f)
        if not cands:
            return None, "시각 일치 경기 없음"

        best, best_score = None, 0.0
        for f in cands:
            s = (self._team_score(game["home"], f["teams"]["home"]["name"])
                 + self._team_score(game["away"], f["teams"]["away"]["name"]))
            if s > best_score:
                best, best_score = f, s
        if best and best_score >= 1.0:
            return best, "팀명" if best_score >= 1.8 else "팀명(한쪽)+시각"

        lids = self._league_ids(game.get("league", ""))
        if lids:
            in_league = [f for f in cands if f["league"]["id"] in lids]
            if len(in_league) == 1:
                return in_league[0], "리그+시각(팀명 확인 필요)"
        return None, f"후보 {len(cands)}개 중 팀명 불일치"
