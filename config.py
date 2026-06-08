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
    "INTU", "COP", "ISRG", "PLTR", "GEV", "LMT", "TJX", "MDLZ", "BLK", "T",
    "ABBV", "GILD", "C", "BMY", "BKNG", "VRTX", "ADI", "MDT", "BA", "ELV",
    "ADP", "CI", "CB", "MMC", "REGN", "SYK", "DE"
]

US_NAME_MAP = {
    "MSFT": "마이크로소프트", "AAPL": "애플", "NVDA": "엔비디아", "AMZN": "아마존", "META": "메타",
    "GOOGL": "알파벳 A", "GOOG": "알파벳 C", "BRK-B": "버크셔 해서웨이", "TSLA": "테슬라", "AVGO": "브로드컴",
    "WMT": "월마트", "LLY": "일라이 릴리", "JPM": "JP모건 체이스", "V": "비자", "XOM": "엑손모빌",
    "UNH": "유나이티드헬스", "MA": "마스터카드", "HD": "홈디포", "PG": "프록터 앤 갬블", "COST": "코스트코",
    "ORCL": "오라클", "NFLX": "넷플릭스", "BAC": "뱅크오브아메리카", "CVX": "셰브론", "AMD": "AMD",
    "KO": "코카콜라", "PEP": "펩시코", "ADBE": "어도비", "CRM": "세일즈포스", "CSCO": "시스코 시스템즈",
    "INTC": "인텔", "QCOM": "퀄컴", "CMCSA": "컴캐스트", "MCD": "맥도날드", "IBM": "IBM",
    "TMO": "써모 피셔", "ACN": "액센추어", "WFC": "웰스 파고", "AXP": "아메리칸 익스프레스", "GE": "제너럴 일렉트릭",
    "NKE": "나이키", "LIN": "린데", "PM": "필립 모리스", "ABT": "애보트", "TMUS": "티모바일",
    "CAT": "캐터필러", "TXN": "텍사스 인스트루먼트", "NOW": "서비스나우", "MS": "모건 스탠리", "DIS": "월트 디즈니",
    "AMAT": "어플라이드 머티어리얼즈", "HON": "하니웰", "AMGN": "암젠", "UNP": "유니온 퍼시픽", "GS": "골드만삭스",
    "PFE": "화이자", "RTX": "레이시온", "LOW": "로우스", "NEE": "넥스트에라 에너시", "SPGI": "S&P 글로벌",
    "INTU": "인튜이트", "COP": "코노코필립스", "ISRG": "인튜이티브 서지컬", "PLTR": "팔란티어", "GEV": "GE 버노바",
    "LMT": "록히드 마틴", "TJX": "TJX 컴퍼니즈", "MDLZ": "몬델리즈 인터내셔널", "BLK": "블랙록", "T": "AT&T",
    "ABBV": "애브비", "GILD": "길리어드 사이언시즈", "C": "씨티그룹", "BMY": "브리스톨 마이어스 스퀴브",
    "BKNG": "부킹 홀딩스", "VRTX": "버텍스 파마슈티컬스", "ADI": "아날로그 디바이스", "MDT": "메드트로닉", "BA": "보잉",
    "ELV": "엘레반스 헬스", "ADP": "오토매틱 데이터 프로세싱", "CI": "시그나", "CB": "첩", "MMC": "마시 앤 맥레넌",
    "REGN": "리제네론 파마슈티컬스", "SYK": "스트라이커", "DE": "존 디어"
}

# --- 한국 코스피 설정 (야후 파이낸스용 .KS 티커 규격) ---
DEFAULT_KOSPI_TICKERS = [
    "005930.KS", "000660.KS", "373220.KS", "207940.KS", "005380.KS",
    "000270.KS", "068270.KS", "005490.KS", "035420.KS", "051910.KS",
    "006400.KS", "035720.KS", "012330.KS", "028260.KS", "105560.KS",
    "055550.KS", "000810.KS", "017670.KS", "015760.KS", "032830.KS",
    "003550.KS", "018260.KS", "009150.KS", "033780.KS", "011200.KS",
    "000720.KS", "010950.KS", "023590.KS", "047050.KS", "003670.KS"
]

KOSPI_NAME_MAP = {
    "005930.KS": "삼성전자", "000660.KS": "SK하이닉스", "373220.KS": "LG에너지솔루션",
    "207940.KS": "삼성바이오로직스", "005380.KS": "현대차", "000270.KS": "기아",
    "068270.KS": "셀트리온", "005490.KS": "POSCO홀딩스", "035420.KS": "NAVER",
    "051910.KS": "LG화학", "006400.KS": "삼성SDI", "035720.KS": "카카오",
    "012330.KS": "현대모비스", "028260.KS": "삼성물산", "105560.KS": "KB금융",
    "055550.KS": "신한지주", "000810.KS": "삼성화재", "017670.KS": "SK텔레콤",
    "015760.KS": "한국전력", "032830.KS": "삼성생명", "003550.KS": "LG",
    "018260.KS": "삼성에스디에스", "009150.KS": "삼성전기", "033780.KS": "KT&G",
    "011200.KS": "HMM", "000720.KS": "현대건설", "010950.KS": "S-Oil",
    "023590.KS": "다우기술", "047050.KS": "포스코인터내셔널", "003670.KS": "포스코퓨처엠"
}

# --- 한국 코스닥 설정 (야후 파이낸스용 .KQ 티커 규격) ---
DEFAULT_KOSDAQ_TICKERS = [
    "247540.KQ", "086520.KQ", "091990.KQ", "196170.KQ", "022100.KQ",
    "066970.KQ", "293490.KQ", "035760.KQ", "253450.KQ", "039200.KQ",
    "145020.KQ", "058470.KQ", "214150.KQ", "036830.KQ", "095700.KQ",
    "068760.KQ", "214320.KQ", "278280.KQ", "034220.KQ", "078600.KQ"
]

KOSDAQ_NAME_MAP = {
    "247540.KQ": "에코프로비엠", "086520.KQ": "에코프로", "091990.KQ": "셀트리온제약",
    "196170.KQ": "알테오젠", "022100.KQ": "포스코DX", "066970.KQ": "엘앤에프",
    "293490.KQ": "카카오게임즈", "035760.KQ": "CJ ENM", "253450.KQ": "스튜디오드래곤",
    "039200.KQ": "오스템임플란트", "145020.KQ": "휴젤", "058470.KQ": "리노공업",
    "214150.KQ": "클래시스", "036830.KQ": "솔브레인", "095700.KQ": "제넥신",
    "068760.KQ": "셀트리온헬스케어", "214320.KQ": "이오테크닉스", "278280.KQ": "천보",
    "034220.KQ": "LG디스플레이", "078600.KQ": "대주전자재료"
}

COL_INFOS = [
    {"id": "rank", "text": "순위", "width": 50, "anchor": "center"},
    {"id": "symbol", "text": "티커", "width": 70, "anchor": "center"},
    {"id": "name", "text": "종목명", "width": 160, "anchor": "w"},            
    {"id": "market_cap", "text": "시가총액(억)", "width": 100, "anchor": "e"},
    {"id": "price", "text": "현재가", "width": 90, "anchor": "e"}, 
    {"id": "peak", "text": "최고점", "width": 90, "anchor": "e"},
    {"id": "peak_diff", "text": "최고점대비", "width": 90, "anchor": "center"},
    {"id": "ma200", "text": "200일선", "width": 90, "anchor": "e"},
    {"id": "diff", "text": "이격도", "width": 80, "anchor": "center"},
    {"id": "rsi", "text": "RSI", "width": 70, "anchor": "center"},
    {"id": "per", "text": "PER", "width": 70, "anchor": "center"},
    {"id": "pbr", "text": "PBR", "width": 70, "anchor": "center"},
    {"id": "roe", "text": "ROE", "width": 70, "anchor": "center"},
    {"id": "peg", "text": "PEG", "width": 70, "anchor": "center"},
    {"id": "eps3y", "text": "EPS 추이", "width": 120, "anchor": "center"},
    {"id": "cagr", "text": "성장률", "width": 80, "anchor": "center"}
]