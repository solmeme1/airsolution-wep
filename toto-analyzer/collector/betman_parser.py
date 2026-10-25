"""베트맨 화면 텍스트(표를 복사한 탭 구분 텍스트)에서 경기 목록을 뽑아내는 파서.

베트맨 화면 구조는 바뀔 수 있으므로 특정 HTML 구조에 의존하지 않고
"한 줄 = 한 경기 행, 셀은 탭으로 구분"이라는 가정만 사용한다.
웹 화면(web/index.html)의 붙여넣기 파서도 같은 규칙을 쓴다.
"""
from __future__ import annotations

import re
from datetime import datetime

ODDS_RE = re.compile(r"^\d{1,3}\.\d{2}$")          # 배당: 소수점 둘째 자리 (1.85, 12.50)
HANDI_RE = re.compile(r"(?:^|\s|H|핸디캡?)\s*([+-]\d+(?:\.\d)?)\s*$")
UO_LINE_RE = re.compile(r"(\d+\.5)")
DATE_RE = re.compile(r"(\d{1,2})[./-](\d{1,2})\s*(?:\([^)]*\))?\s*(\d{1,2}):(\d{2})")
PCT_RE = re.compile(r"^(\d{1,3}(?:\.\d+)?)\s*%$")

SOCCER_HINTS = ("축구", "EPL", "프리미어", "라리가", "세리에", "분데스", "리그앙", "리그1",
                "K리그", "J리그", "J1", "J2", "UCL", "UEL", "챔스", "에레디비", "MLS",
                "챔피언십", "A리그", "포르투갈", "스코틀", "FA컵", "월드컵", "아시안컵", "유로")
OTHER_SPORT_HINTS = ("농구", "야구", "배구", "NBA", "KBL", "MLB", "KBO", "NPB", "V리그",
                     "WKBL", "NHL", "하키", "골프")


def _cells(line: str) -> list[str]:
    if "\t" in line:
        parts = line.split("\t")
    elif "|" in line:
        parts = line.split("|")
    else:
        parts = re.split(r"\s{2,}", line)
    return [p.strip() for p in parts if p.strip()]


def _kickoff(text: str, year: int) -> str | None:
    m = DATE_RE.search(text)
    if not m:
        return None
    mo, d, h, mi = (int(x) for x in m.groups())
    try:
        return datetime(year, mo, d, h, mi).strftime("%Y-%m-%dT%H:%M")
    except ValueError:
        return None


def _teams(cells: list[str]) -> tuple[str, str] | None:
    # 1) "vs" 단독 셀 양옆
    for i, c in enumerate(cells):
        if c.lower() in ("vs", "v", ":") and 0 < i < len(cells) - 1:
            return cells[i - 1], cells[i + 1]
    # 2) 한 셀 안에 "홈 vs 원정"
    for c in cells:
        if re.search(r"\s(vs|VS|Vs)\s", c):
            a, b = re.split(r"\s(?:vs|VS|Vs)\s", c, maxsplit=1)
            return _clean_team(a), _clean_team(b)
    return None


def _clean_team(name: str) -> str:
    # 팀명 옆에 붙은 핸디캡/기준점 표기 제거: "맨체스U H -1.0" -> "맨체스U"
    name = re.sub(r"\s*(H|핸디캡?)\s*[+-]?\d+(\.\d)?\s*$", "", name)
    name = re.sub(r"\s*(U/O|언더오버)\s*\d+(\.\d)?\s*$", "", name)
    return name.strip()


def _sport_is_soccer(text: str) -> bool | None:
    if any(h in text for h in OTHER_SPORT_HINTS):
        return False
    if any(h in text for h in SOCCER_HINTS):
        return True
    return None


def _league(cells: list[str]) -> str:
    for c in cells:
        name = c.replace("축구", "").strip()
        if name and any(h in c for h in SOCCER_HINTS) and len(c) <= 20:
            return name
    return ""


def parse_proto(text: str, year: int | None = None, soccer_only: bool = True) -> list[dict]:
    """프로토 승부식 행 파싱. 한 경기의 일반/핸디캡/언더오버는 각각 별도 행으로 나온다."""
    year = year or datetime.now().year
    out: list[dict] = []
    for raw in text.splitlines():
        cells = _cells(raw)
        if len(cells) < 4:
            continue
        line = " ".join(cells)
        teams = _teams(cells)
        if not teams:
            continue
        odds = [float(c) for c in cells if ODDS_RE.match(c)]
        if len(odds) < 2:
            continue
        soccer = _sport_is_soccer(line)
        if soccer_only and soccer is False:
            continue

        market, mline = "1x2", None
        if re.search(r"U/O|언더|오버", line):
            market = "uo"
            m = UO_LINE_RE.search(line.replace(teams[0], "").replace(teams[1], ""))
            mline = float(m.group(1)) if m else None
        elif re.search(r"핸디|(^|\s)H\s*[+-]", line):
            market = "handicap"
            for c in cells:
                m = HANDI_RE.search(c)
                if m and not ODDS_RE.match(c):
                    mline = float(m.group(1))
                    break

        if market == "uo":
            if len(odds) < 2:
                continue
            o = {"under": odds[-2], "over": odds[-1]}
        elif len(odds) >= 3:
            o = {"home": odds[-3], "draw": odds[-2], "away": odds[-1]}
        else:
            # 무승부 없는 핸디캡(.5 기준점) 등
            o = {"home": odds[-2], "away": odds[-1]}

        no = next((c for c in cells if re.fullmatch(r"\d{1,3}", c)), None)
        out.append({
            "no": int(no) if no else None,
            "league": _league(cells),
            "kickoff": _kickoff(line, year),
            "home": teams[0],
            "away": teams[1],
            "market": market,
            "line": mline,
            "odds": o,
            "soccer": soccer,
            "raw": raw.strip()[:300],
        })
    return out


def parse_toto(text: str, year: int | None = None) -> list[dict]:
    """축구토토 승무패 14경기 행 파싱 (배당 없음, 투표율이 있으면 함께 수집)."""
    year = year or datetime.now().year
    out: list[dict] = []
    seen: set[int] = set()
    for raw in text.splitlines():
        cells = _cells(raw)
        if len(cells) < 3:
            continue
        teams = _teams(cells)
        if not teams:
            continue
        no = next((int(c) for c in cells if re.fullmatch(r"\d{1,2}", c)), None)
        if no is None or not 1 <= no <= 14 or no in seen:
            continue
        seen.add(no)
        pcts = [float(PCT_RE.match(c).group(1)) for c in cells if PCT_RE.match(c)]
        line = " ".join(cells)
        out.append({
            "no": no,
            "league": _league(cells),
            "kickoff": _kickoff(line, year),
            "home": teams[0],
            "away": teams[1],
            "votes": {"home": pcts[0], "draw": pcts[1], "away": pcts[2]} if len(pcts) >= 3 else None,
            "raw": raw.strip()[:300],
        })
    out.sort(key=lambda r: r["no"])
    return out
