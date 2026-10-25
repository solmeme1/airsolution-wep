"""베트맨 경기(한글 팀명)와 API-Football 경기(영문 팀명)를 연결한다.

베트맨은 정식 클럽명(토트넘 홋스퍼, AFC본머스, VfB슈투트가르트 …)을 쓰므로
1) 클럽 접두·접미어와 숫자를 지워 정규화하고
2) 별칭 사전 키가 이름 안에 들어 있으면(가장 긴 키 우선) 그 영문명으로 본다.
같은 킥오프 시각(±30분) 후보 중 홈·원정 점수 합이 가장 높은 경기를 고르며,
한쪽만 맞은 경우 반대편 팀명을 학습 파일(team_alias_learned.json)에 저장해 다음부터 쓴다.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

AFFIX = ["ACF", "RCD", "SSC", "AFC", "OGC", "OSC", "SCO", "TSG", "VfB", "VfL", "FSV", "CFC", "TSV", "BSC",
         "UD", "SD", "CD", "CF", "SS", "US", "AC", "AJ", "AS", "BC", "RC", "SC", "FC", "SV", "VV"]


def _norm(s: str) -> str:
    return re.sub(r"[^0-9a-z가-힣]", "", (s or "").lower())


def _norm_ko(s: str) -> str:
    s = re.sub(r"\d{2,4}", "", s or "")
    for a in AFFIX:
        s = re.sub(rf"(?<![A-Za-z]){a}(?![a-z])", "", s)
    return _norm(s)


def _norm_en(s: str) -> str:
    s = re.sub(r"\b(FC|CF|AFC|SC|AC|SSC|SV|VfB|VfL|TSG|RCD|UD|CD|SD)\b", "", s or "")
    return _norm(s)


class Matcher:
    def __init__(self, alias_path: Path, learned_path: Path | None = None):
        data = json.loads(alias_path.read_text(encoding="utf-8"))
        self.learned_path = learned_path
        learned = {}
        if learned_path and learned_path.exists():
            learned = json.loads(learned_path.read_text(encoding="utf-8"))
        self.learned = learned
        teams = dict(data.get("teams", {}))
        teams.update({k: [v] for k, v in learned.items()})
        self.teams = {_norm_ko(k) or _norm(k): [_norm_en(v) for v in vs] for k, vs in teams.items()}
        self.keys = sorted(self.teams, key=len, reverse=True)
        self.leagues = data.get("leagues", {})

    def _aliases(self, ko: str) -> list[str] | None:
        k = _norm_ko(ko) or _norm(ko)
        if k in self.teams:
            return self.teams[k]
        for key in self.keys:  # 가장 긴 키부터: "맨체스터시티"가 "맨체스터"보다 먼저
            if len(key) >= 2 and key in k:
                return self.teams[key]
        return None

    def _team_score(self, ko: str, en: str) -> float:
        e = _norm_en(en)
        if not e:
            return 0.0
        al = self._aliases(ko)
        if al:
            if any(a == e for a in al):
                return 1.0
            # 부분 일치는 살짝 낮게: "Paris FC"(paris)가 "Paris Saint Germain"보다 우선되도록
            return 0.95 if any(a and (a in e or e in a) for a in al) else 0.0
        k = _norm(ko)
        if re.fullmatch(r"[0-9a-z]+", k or "-"):  # 베트맨이 영문으로 쓴 경우
            return 0.9 if (k in e or e in k) else 0.0
        return 0.0

    def pick_name(self, ko: str, names: list[str]) -> str | None:
        """영문 팀명 목록(예: football-data 팀명) 중 베트맨 팀명에 해당하는 것."""
        scored = sorted(((self._team_score(ko, n), n) for n in names), reverse=True)
        return scored[0][1] if scored and scored[0][0] >= 0.9 else None

    def _league_ids(self, league: str) -> set[int]:
        hits = [k for k in self.leagues if k.lower() in (league or "").lower()]
        # "K리그1" 안의 "리그1"(리그앙)처럼 더 긴 키에 포함되는 짧은 키는 버린다
        hits = [k for k in hits if not any(k != o and k in o for o in hits)]
        return {i for k in hits for i in self.leagues[k]}

    def _learn(self, ko: str, en: str) -> None:
        if not self.learned_path or ko in self.learned:
            return
        self.learned[ko] = en
        self.teams[_norm_ko(ko) or _norm(ko)] = [_norm_en(en)]
        self.keys = sorted(self.teams, key=len, reverse=True)
        self.learned_path.write_text(json.dumps(self.learned, ensure_ascii=False, indent=1), encoding="utf-8")

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

        best, best_s = None, (0.0, 0.0)
        for f in cands:
            sh = self._team_score(game["home"], f["teams"]["home"]["name"])
            sa = self._team_score(game["away"], f["teams"]["away"]["name"])
            if sh + sa > sum(best_s):
                best, best_s = f, (sh, sa)
        if best and sum(best_s) >= 1.8:
            return best, "팀명"
        if best and sum(best_s) >= 0.9:
            # 한쪽만 맞음: 같은 시각에 그 팀이 나오는 경기는 하나뿐이므로 반대편 이름을 학습
            if best_s[0] >= 0.9:
                self._learn(game["away"], best["teams"]["away"]["name"])
            else:
                self._learn(game["home"], best["teams"]["home"]["name"])
            return best, "팀명(한쪽)+시각"

        lids = self._league_ids(game.get("league", ""))
        if lids:
            in_league = [f for f in cands if f["league"]["id"] in lids]
            if len(in_league) == 1:
                return in_league[0], "리그+시각(팀명 확인 필요)"
        return None, f"후보 {len(cands)}개 중 팀명 불일치"
