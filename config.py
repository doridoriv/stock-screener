import os

APP_TITLE = "저렴한주식쇼핑 by 유경빈+유채화뿅뿅"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(BASE_DIR, "cache")
US_MARKETCAP_CACHE_FILE = os.path.join(CACHE_DIR, "us_marketcap_cache.json")

if not os.path.exists(CACHE_DIR):
    os.makedirs(CACHE_DIR)

# [방법 B] 미국 시장 기본 티커 구성
DEFAULT_US_TICKERS = [
    "MSFT", "AAPL", "NVDA", "AMZN", "META", "GOOGL", "GOOG", "BRK-B", "TSLA", "AVGO",
    "WMT", "LLY", "JPM", "V", "XOM", "UNH", "MA", "HD", "PG", "COST",
    "ORCL", "NFLX", "BAC", "CVX", "AMD", "KO", "PEP", "ADBE", "CRM", "CSCO",
    "INTC", "QCOM", "CMCSA", "MCD", "IBM", "TMO", "ACN", "WFC", "AXP", "GE",
    "NKE", "LIN", "PM", "ABT", "TMUS", "CAT", "TXN", "NOW", "MS", "DIS"
]

US_NAME_MAP = {
    "MSFT": "마이크로소프트", "AAPL": "애플", "NVDA": "엔비디아", "AMZN": "아마존", "META": "메타",
    "GOOGL": "알파벳 A", "GOOG": "알파벳 C", "BRK-B": "버크셔 해서웨이", "TSLA": "테슬라", "AVGO": "브로드컴",
    "WMT": "월마트", "LLY": "일라이 릴리", "JPM": "JP모건 체이스", "V": "비자", "XOM": "엑슨모빌",
    "UNH": "유나이티드헬스", "MA": "마스터카드", "HD": "홈디포", "PG": "프록터 앤 갬블", "COST": "코스트코"
}

# [방법 B] 한국 코스피(KOSPI) 주요 상위 종목 고정 정의 (.KS)
DEFAULT_KOSPI_TICKERS = [
    "005930.KS", "000660.KS", "373220.KS", "207940.KS", "005380.KS", 
    "000270.KS", "068270.KS", "005490.KS", "035420.KS", "051910.KS",
    "035720.KS", "006400.KS", "012330.KS", "105560.KS", "055550.KS",
    "003550.KS", "015760.KS", "032830.KS", "018260.KS", "000810.KS"
]

KOSPI_NAME_MAP = {
    "005930.KS": "삼성전자", "000660.KS": "SK하이닉스", "373220.KS": "LG에너지솔루션", "207940.KS": "삼성바이오로직스", "005380.KS": "현대차",
    "000270.KS": "기아", "068270.KS": "셀트리온", "005490.KS": "POSCO홀딩스", "035420.KS": "NAVER", "051910.KS": "LG화학",
    "035720.KS": "카카오", "006400.KS": "삼성SDI", "012330.KS": "현대모비스", "105560.KS": "KB금융", "055550.KS": "신한지주",
    "003550.KS": "LG", "015760.KS": "한국전력", "032830.KS": "삼성생명", "018260.KS": "한온시스템", "000810.KS": "삼성화재"
}

# [방법 B] 한국 코스닥(KOSDAQ) 주요 상위 종목 고정 정의 (.KQ)
DEFAULT_KOSDAQ_TICKERS = [
    "247540.KQ", "086520.KQ", "091990.KQ", "022100.KQ", "066970.KQ",
    "293490.KQ", "196170.KQ", "036930.KQ", "035900.KQ", "041510.KQ",
    "058470.KQ", "214150.KQ", "028300.KQ", "078600.KQ", "067160.KQ"
]

KOSDAQ_NAME_MAP = {
    "247540.KQ": "에코프로비엠", "086520.KQ": "에코프로", "091990.KQ": "셀트리온제약", "022100.KQ": "포스코DX", "066970.KQ": "엘앤에프",
    "293490.KQ": "카카오게임즈", "196170.KQ": "알테오젠", "036930.KQ": "주성엔지니어링", "035900.KQ": "제이콘텐트리", "041510.KQ": "에스엠",
    "058470.KQ": "리노공업", "214150.KQ": "클래시스", "028300.KQ": "HLB", "078600.KQ": "대주전자재료", "067160.KQ": "메디톡스"
}