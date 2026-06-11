import os

APP_TITLE = "저렴한주식쇼핑 by 유경빈+유채화뿅뿅"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(BASE_DIR, "cache")
US_MARKETCAP_CACHE_FILE = os.path.join(CACHE_DIR, "us_marketcap_cache.json")

if not os.path.exists(CACHE_DIR):
    os.makedirs(CACHE_DIR)

DEFAULT_US_TICKERS = [
    "MSFT", "AAPL", "NVDA", "AMZN", "META", "GOOGL", "GOOG", "BRK-B", "TSLA", "AVGO",
    "WMT", "LLY", "JPM", "V", "XOM", "UNH", "MA", "HD", "PG", "COST",
    "ORCL", "NFLX", "BAC", "CVX", "AMD", "KO", "PEP", "ADBE", "CRM", "CSCO",
    "INTC", "QCOM", "CMCSA", "MCD", "IBM", "TMO", "ACN", "WFC", "AXP", "GE",
    "NKE", "LIN", "PM", "ABT", "TMUS", "CAT", "TXN", "NOW", "MS", "DIS",
    "AMAT", "HON", "AMGN", "UNP", "GS", "PFE", "RTX", "LOW", "NEE", "SPGI",
    "INTU", "COP", "ISRG", "PLTR", "GEV", "LMT", "LRCX", "TJX",
    "MDLZ", "BLK", "T", "ABBV", "GILD", "C", "BMY", "BKNG", "VRTX", "ADI",
    "MDT", "BA", "ELV", "ADP", "CI", "CB", "MMC", "REGN", "SYK", "DE"
]

US_NAME_MAP = {
    "MSFT": "마이크로소프트", "AAPL": "애플", "NVDA": "엔비디아", "AMZN": "아마존", "META": "메타",
    "GOOGL": "알파벳 A", "GOOG": "알파벳 C", "BRK-B": "버크셔 해서웨이 B", "TSLA": "테슬라", "AVGO": "브로드컴",
    "WMT": "월마트", "LLY": "일라이 릴리", "JPM": "제이피모간 체이스", "V": "비자", "XOM": "엑슨모빌",
    "UNH": "유나이티드헬스 그룹", "MA": "마스터카드", "HD": "홈디포", "PG": "프록터 앤 갬블(P&G)", "COST": "코스트코",
    "ORCL": "오라클", "NFLX": "넷플릭스", "BAC": "뱅크 오브 아메리카", "CVX": "셰브론", "AMD": "어드밴스드 마이크로 디바이스",
    "KO": "코카콜라", "PEP": "펩시코", "ADBE": "어도비", "CRM": "세일즈포스", "CSCO": "시스코 시스템즈",
    "INTC": "인텔", "QCOM": "퀄컴", "CMCSA": "컴캐스트", "MCD": "맥도날드", "IBM": "IBM",
    "TMO": "써모 피셔 사이언티픽", "ACN": "액센추어", "WFC": "웰스 파고", "AXP": "아메리칸 익스프레스", "GE": "제너럴 일렉트릭(GE)",
    "NKE": "나이키", "LIN": "린데", "PM": "필립모리스 인터내셔널", "ABT": "애보트 래보라토리", "TMUS": "티모바일 US",
    "CAT": "캐터필러", "TXN": "텍사스 인스트루먼트", "NOW": "서비스나우", "MS": "모간 스탠리", "DIS": "월트 디즈니",
    "AMAT": "어플라이드 머티어리얼즈", "HON": "허니웰", "AMGN": "암젠", "UNP": "유니온 퍼시픽", "GS": "골드만삭스",
    "PFE": "화이자", "RTX": "레이시온 테크놀로지스", "LOW": "로우스", "NEE": "넥스트에라 에너지", "SPGI": "S&P 글로벌",
    "INTU": "인튜이트", "COP": "코노코필립스", "ISRG": "인튜이티브 서지컬", "PLTR": "팔란티어 테크놀로지스", "GEV": "GE 버노바",
    "LMT": "록히드 마틴", "LRCX": "램 리서치", "TJX": "TJX 컴퍼니즈", "MDLZ": "몬델리즈 인터내셔널", "BLK": "블랙록",
    "T": "AT&T", "ABBV": "애브비", "GILD": "길리어드 사이언시즈", "C": "씨티그룹", "BMY": "브리스톨 마이어스 스퀴브",
    "BKNG": "부킹 홀딩스", "VRTX": "버텍스 파마슈티컬스", "ADI": "아날로그 디바이스", "MDT": "메드트로닉", "BA": "보잉",
    "ELV": "엘레반스 헬스", "ADP": "오토매틱 데이터 프로세싱", "CI": "시그나", "CB": "처브", "MMC": "마시 앤 맥레넌",
    "REGN": "리제네론 파마슈티컬스", "SYK": "스트라이커", "DE": "존 디어"
}

COL_INFOS = [
    {"id": "rank", "text": "순위", "width": 50, "anchor": "center"},
    {"id": "symbol", "text": "티커", "width": 70, "anchor": "center"},
    {"id": "name", "text": "종목명", "width": 160, "anchor": "w"},
    {"id": "market_cap", "text": "시가총액", "width": 100, "anchor": "e"},
    {"id": "price", "text": "현재가", "width": 90, "anchor": "e"},
    {"id": "peak", "text": "최고점", "width": 90, "anchor": "e"},
    {"id": "peak_diff", "text": "최고점대비", "width": 80, "anchor": "center"},
    {"id": "ma200", "text": "200일선", "width": 90, "anchor": "e"},
    {"id": "diff", "text": "200일괴리율", "width": 80, "anchor": "center"},
    {"id": "rsi", "text": "RSI", "width": 70, "anchor": "center"},
    {"id": "per", "text": "PER", "width": 70, "anchor": "center"},
    {"id": "pbr", "text": "PBR", "width": 70, "anchor": "center"},
    {"id": "roe", "text": "ROE", "width": 70, "anchor": "center"},
    {"id": "peg", "text": "PEG", "width": 70, "anchor": "center"},
    {"id": "eps3y", "text": "EPS3Y", "width": 70, "anchor": "center"},
    {"id": "cagr", "text": "CAGR", "width": 80, "anchor": "center"},
    {"id": "score", "text": "점수", "width": 70, "anchor": "center"},
    {"id": "grade", "text": "등급", "width": 60, "anchor": "center"},
    {"id": "confidence", "text": "신뢰도", "width": 80, "anchor": "center"},
]

SCORE_WEIGHTS = {
    "per": 15,
    "pbr": 10,
    "roe": 20,
    "peg": 20,
    "eps3y": 10,
    "cagr": 15,
    "rsi": 5,
    "peak_diff": 5,
}

GRADE_RULES = [
    (90, "S"),
    (80, "A"),
    (70, "B"),
    (60, "C"),
    (0, "D"),
]