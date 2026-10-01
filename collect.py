"""국내·해외 자동차/타이어 뉴스를 모아 요약해 news.json에 저장합니다. 영문 기사는 번역 없이 원문 그대로 올립니다. (파이썬 기본 기능만 사용)"""
import json, os, re, urllib.request, urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime

KST = timezone(timedelta(hours=9))
MODEL = "claude-haiku-4-5-20251001"
KEEP_DAYS = 14      # 페이지에 보관하는 기간
MAX_AGE_DAYS = 3    # 이보다 오래된 기사는 수집하지 않음
BATCH = 20          # 한 번에 요약하는 기사 수
CATS = ["tire", "car", "part", "ev", "trade"]


def gn(query, lang="en"):
    """구글 뉴스 검색 RSS 주소를 만듭니다."""
    p = {"hl": "ko", "gl": "KR", "ceid": "KR:ko"} if lang == "ko" else {"hl": "en-US", "gl": "US", "ceid": "US:en"}
    return "https://news.google.com/rss/search?" + urllib.parse.urlencode({"q": query, **p})


# ── 수집처 설정 ─────────────────────────────────────────────
# name: 표시할 출처명(None이면 기사에 적힌 매체명 사용) / hint: 기본 카테고리 / limit: 수집처당 최대 기사 수
# feeds: 앞에서부터 차례로 시도하고, 기사를 가져오면 멈춥니다. (직접 RSS가 막히면 구글 뉴스 검색으로 대체)
SOURCES = [
    # 국내
    {"name": None, "region": "kr", "hint": "tire", "limit": 6, "feeds": [gn("타이어 OR 한국타이어 OR 금호타이어 OR 넥센타이어 when:1d", "ko")]},
    {"name": None, "region": "kr", "hint": "car", "limit": 6, "feeds": [gn("완성차 OR 자동차 판매 OR 현대차 OR 기아 when:1d", "ko")]},
    {"name": None, "region": "kr", "hint": "part", "limit": 6, "feeds": [gn("자동차 부품 OR 자동차 부품업계 when:1d", "ko")]},
    {"name": None, "region": "kr", "hint": "ev", "limit": 6, "feeds": [gn("전기차 OR 배터리 자동차 when:1d", "ko")]},
    {"name": None, "region": "kr", "hint": "trade", "limit": 6, "feeds": [gn("자동차 관세 OR 타이어 관세 OR 반덤핑 타이어 when:2d", "ko")]},
    # 해외 타이어 전문지
    {"name": "Tire Business", "region": "global", "hint": "tire", "limit": 6,
     "feeds": ["https://www.tirebusiness.com/arc/outboundfeeds/rss/?outputType=xml", gn("site:tirebusiness.com when:3d")]},
    {"name": "Tyrepress", "region": "global", "hint": "tire", "limit": 6,
     "feeds": ["https://www.tyrepress.com/feed/", gn("site:tyrepress.com when:3d")]},
    {"name": "Modern Tire Dealer", "region": "global", "hint": "tire", "limit": 6,
     "feeds": [gn("site:moderntiredealer.com when:3d")]},
    {"name": "Tire Review", "region": "global", "hint": "tire", "limit": 6,
     "feeds": ["https://www.tirereview.com/feed/", gn("site:tirereview.com when:3d")]},
    # 해외 통신사·자동차 매체
    {"name": "Reuters", "region": "global", "hint": "car", "limit": 5,
     "feeds": [gn("site:reuters.com (automakers OR automotive OR tires OR EV) when:1d")]},
    {"name": "AP", "region": "global", "hint": "car", "limit": 4,
     "feeds": [gn("site:apnews.com (automakers OR auto industry OR electric vehicles) when:1d")]},
    {"name": "Bloomberg", "region": "global", "hint": "car", "limit": 4,
     "feeds": [gn("site:bloomberg.com (automakers OR EV OR auto tariffs) when:1d")]},
    {"name": "Automotive News", "region": "global", "hint": "car", "limit": 5,
     "feeds": [gn("site:autonews.com when:1d")]},
    {"name": "Just Auto", "region": "global", "hint": "part", "limit": 4,
     "feeds": [gn("site:just-auto.com when:2d")]},
]
# ───────────────────────────────────────────────────────────

A = "{http://www.w3.org/2005/Atom}"


def to_kst(s):
    try:
        dt = parsedate_to_datetime(s)
    except Exception:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(KST)


def parse_feed(raw):
    """RSS와 Atom을 모두 읽어 (제목, 링크, 날짜, 매체명) 목록으로 돌려줍니다."""
    root = ET.fromstring(raw)
    out = []
    for it in root.iter("item"):
        src = it.find("source")
        out.append((it.findtext("title"), it.findtext("link"), it.findtext("pubDate"), src.text if src is not None else ""))
    for en in root.iter(A + "entry"):
        ln = en.find(A + "link")
        out.append((en.findtext(A + "title"), ln.get("href") if ln is not None else None,
                    en.findtext(A + "updated") or en.findtext(A + "published"), ""))
    return out


def fetch_source(cfg):
    now = datetime.now(KST)
    for url in cfg["feeds"]:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            raw = urllib.request.urlopen(req, timeout=30).read()
            items = []
            for title, link, date, src in parse_feed(raw):
                if not (title and link and date):
                    continue
                ts = to_kst(date)
                if now - ts > timedelta(days=MAX_AGE_DAYS):
                    continue
                if "news.google.com" in url:   # 구글 뉴스 제목 끝의 " - 매체명" 제거
                    title = re.sub(r"\s+-\s+[^-]+$", "", title)
                items.append({"c": cfg["hint"], "o": title.strip(), "h": title.strip(), "url": link.strip(),
                              "src": cfg["name"] or src, "r": cfg["region"], "ts": ts.strftime("%Y-%m-%dT%H:%M")})
            if items:
                items.sort(key=lambda n: n["ts"], reverse=True)
                print("수집 성공:", cfg["name"] or cfg["hint"], len(items), "건 ←", url[:60])
                return items[:cfg["limit"]]
            print("기사 없음:", url[:60])
        except Exception as e:
            print("수집 실패:", url[:60], e)
    return []


def summarize(items):
    """제목만 보고 요약합니다. 기사 제목의 언어(한국어/영어)와 같은 언어로 쓰며, 번역하지 않습니다."""
    payload = [{"id": i, "category": n["c"], "title": n["o"], "source": n["src"]} for i, n in enumerate(items)]
    prompt = (
        "다음은 자동차·타이어 업계 뉴스 제목 목록입니다(한국어 또는 영어). 각 항목에 대해 JSON 배열만 출력하세요.\n"
        '형식: [{"id":0,"keep":true,"c":"tire","s":"1~2문장 요약","p":"업계 포인트 한 줄"}]\n'
        "규칙: (1) c는 tire, car, part, ev, trade 중 하나입니다(tire 타이어, car 완성차, part 부품, ev 전기차·배터리, trade 관세·무역). "
        "(2) 제목을 번역하지 마세요. s와 p는 제목과 같은 언어로 쓰세요(제목이 한국어면 한국어, 영어면 영어). "
        "(3) 제목에 없는 사실, 숫자, 원인은 절대 추가하지 마세요. 제목만으로 알 수 없으면 s는 제목의 뜻을 쉬운 말로 풀어쓰기만 하세요. "
        "(4) p는 이 소식이 타이어·자동차 업계에서 갖는 의미를 조심스럽게 한 줄로 쓰되 단정은 피하세요. "
        "(5) 자동차·타이어 업계와 무관하거나 광고성·구인·행사 안내면 keep을 false로 하세요.\n\n"
        + json.dumps(payload, ensure_ascii=False))
    body = json.dumps({"model": MODEL, "max_tokens": 6000,
                       "messages": [{"role": "user", "content": prompt}]}).encode()
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=body, headers={
        "x-api-key": os.environ["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01",
        "content-type": "application/json"})
    text = json.loads(urllib.request.urlopen(req, timeout=180).read())["content"][0]["text"]
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    return {r["id"]: r for r in json.loads(text)}


def main():
    old = json.load(open("news.json", encoding="utf-8")) if os.path.exists("news.json") else []
    seen = {n["url"] for n in old}
    fresh, titles = [], set()
    for cfg in SOURCES:
        for n in fetch_source(cfg):
            if n["url"] not in seen and n["o"] not in titles:
                titles.add(n["o"]); fresh.append(n)
    added = 0
    for i in range(0, len(fresh), BATCH):
        chunk = fresh[i:i + BATCH]
        try:
            res = summarize(chunk)
        except Exception as e:
            print("요약 실패:", e); continue
        for j, n in enumerate(chunk):
            r = res.get(j)
            if r and r.get("keep"):
                n["s"], n["p"] = r["s"], r["p"]
                if r.get("c") in CATS:
                    n["c"] = r["c"]
                old.append(n); added += 1
    cutoff = (datetime.now(KST) - timedelta(days=KEEP_DAYS)).strftime("%Y-%m-%dT%H:%M")
    old = sorted([n for n in old if n["ts"] >= cutoff], key=lambda n: n["ts"], reverse=True)
    json.dump(old, open("news.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("저장된 뉴스:", len(old), "건 / 새 후보:", len(fresh), "건 / 새로 추가:", added, "건")


if __name__ == "__main__":
    main()
