import os

APP_TITLE = "저렴한주식쇼핑 by 유경빈+유채화뿅뿅"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 캐시 시스템 저장 디렉터리 경로 설정
CACHE_DIR = os.path.join(BASE_DIR, "cache")
US_MARKETCAP_CACHE_FILE = os.path.join(CACHE_DIR, "us_marketcap_cache.json")

if not os.path.exists(CACHE_DIR):
    os.makedirs(CACHE_DIR)

# 안전성 확보를 위한 크롤링 지연 시간 및 재시도 설정 (안전제일)
REQUEST_TIMEOUT = 10
MAX_RETRIES = 5
BACKOFF_FACTOR = 1.0  # 지수 백오프 계수
MIN_SLEEP = 0.5
MAX_SLEEP = 1.5
US_MAX_WORKERS = 1  # Number of parallel workers for US market (configurable)
FIXED_TOP_N = 100

# User-Agent 풀 (데이터 제공처의 차단을 피하기 위해 사용)
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/119.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0"
]

# 미국 시장 기본 분석 티커 풀 목록 (기본 백업용)
DEFAULT_US_TICKERS = [
    "MSFT", "AAPL", "NVDA", "AMZN", "META", "GOOGL", "GOOG", "BRK-B", "TSLA", "AVGO",
    "WMT", "LLY", "JPM", "V", "XOM", "UNH", "MA", "HD", "PG", "COST",
    "ORCL", "NFLX", "BAC", "CVX", "AMD", "KO", "PEP", "ADBE", "CRM", "CSCO",
    "INTC", "QCOM", "CMCSA", "MCD", "IBM", "TMO", "ACN", "WFC", "AXP", "GE",
    "NKE", "LIN", "PM", "ABT", "TMUS", "CAT", "TXN", "NOW", "MS", "DIS",
    "AMAT", "HON", "AMGN", "UNP", "GS", "PFE", "RTX", "LOW", "NEE", "SPGI",
    "INTU", "COP", "ABBV", "LMT", "MDT", "SYK", "EL",
    "BKNG", "ISRG", "BLK", "TJX", "VRTX", "C", "SCHW", "DE", "ADP", "PLTR",
    "MDLZ", "ADI", "LRCX", "CB", "MMC", "GILD", "PANW", "AMT", "KLAC", "SO",
    "MO", "DUK", "BSX", "CI", "ZTS", "ICE", "CME", "EQIX", "SHW", "MCO",
    "PH", "REGN", "WM", "CDNS", "SNPS", "ORLY", "NOC", "USB", "PNC", "APD",
    "EOG", "AON", "ITW", "CL", "TGT", "FDX", "EMR", "MAR", "ROP", "HCA",
    "PSX", "GM", "NXPI", "MPC", "FCX", "SLB", "NSC", "CSX", "AFL", "TRV"
]

# 미국 티커 한글 맵핑 규격 정의
US_NAME_MAP = {
    "MSFT": "마이크로소프트", "AAPL": "애플", "NVDA": "엔비디아", "AMZN": "아마존",
    "META": "메타 플랫폼스", "GOOGL": "알파벳A", "GOOG": "알파벳C", "BRK-B": "버크셔해서웨이",
    "TSLA": "테슬라", "AVGO": "브로드컴", "WMT": "월마트", "LLY": "일라이릴리",
    "JPM": "JP모건 체이스", "V": "비자", "XOM": "엑슨모빌", "UNH": "유나이티드헬스",
    "MA": "마스터카드", "HD": "홈디포", "PG": "프록터앤갬블", "COST": "코스트코",
    "ORCL": "오라클", "NFLX": "넷플릭스", "BAC": "뱅크오브아메리카", "CVX": "쉐브론",
    "AMD": "AMD", "KO": "코카콜라", "PEP": "펩시코", "ADBE": "어도비",
    "CRM": "세일즈포스", "CSCO": "시스코 시스템즈"
}

# 기존 평가 가중치 스키마 보존
SCORE_WEIGHTS = {
    "per": 15, "pbr": 10, "roe": 20, "peg": 20,
    "eps3y": 10, "cagr": 15, "rsi": 5, "peak_diff": 5
}

# 기존 종합 투자 등급 테이블 기준 스키마 보존
GRADE_RULES = [
    (85, "S"),
    (70, "A"),
    (55, "B"),
    (40, "C"),
    (0, "D")
]

# ==========================================
# [패치 반영] 고정 너비(width) 전면 제거 및 신규 4대 지표 추가 정의
# ==========================================
# st.dataframe(..., use_container_width=True) 구조와 100% 호환되도록
# 정렬 기준(anchor)과 한글 이름 위주로 경량 최적화했습니다.

TABLE_COLUMNS = [
    {"id": "rank", "text": "순위", "anchor": "center"},
    {"id": "symbol", "text": "티커", "anchor": "center"},
    {"id": "name", "text": "종목명", "anchor": "w"},
    {"id": "score", "text": "종합점수", "anchor": "center"},
    {"id": "grade", "text": "등급", "anchor": "center"},
    
    # 4대 필수 수집 지표 컬럼 배치
    {"id": "eps_growth", "text": "EPS성장률(%)", "anchor": "center"},
    {"id": "hist_per_avg", "text": "과거평균PER", "anchor": "center"},
    {"id": "us_10y_bond", "text": "美10년물금리", "anchor": "center"},
    {"id": "foreign_supply", "text": "외인/기관지분(%)", "anchor": "center"},
    
    # 기존 지표 컬럼 배치
    {"id": "market_cap", "text": "시가총액", "anchor": "e"},
    {"id": "price", "text": "기준가격", "anchor": "e"},
    {"id": "price_basis", "text": "가격기준", "anchor": "center"},
    {"id": "after_market_price", "text": "애프터가격", "anchor": "e"},
    {"id": "after_market_change_pct", "text": "애프터등락률(%)", "anchor": "center"},
    {"id": "price_time", "text": "가격수집시각", "anchor": "center"},
    {"id": "peak", "text": "최고점", "anchor": "e"},
    {"id": "peak_diff", "text": "최고점대비(%)", "anchor": "center"},
    {"id": "ma200", "text": "200일선", "anchor": "e"},
    {"id": "diff", "text": "200일괴리율(%)", "anchor": "center"},
    {"id": "rsi", "text": "RSI", "anchor": "center"},
    {"id": "per", "text": "현재PER", "anchor": "center"},
    {"id": "pbr", "text": "PBR", "anchor": "center"},
    {"id": "roe", "text": "ROE(%)", "anchor": "center"},
    {"id": "revenue_growth", "text": "매출성장률(%)", "anchor": "center"},
    {"id": "operating_growth", "text": "영업이익성장률(%)", "anchor": "center"},
    {"id": "debt_ratio", "text": "부채비율(%)", "anchor": "center"},
    {"id": "dividend_yield", "text": "배당수익률(%)", "anchor": "center"},
    {"id": "payout_ratio", "text": "배당성향(%)", "anchor": "center"},
    {"id": "dividend_per_share", "text": "주당배당금", "anchor": "center"},
    {"id": "peg", "text": "PEG", "anchor": "center"},
    {"id": "eps3y", "text": "EPS 3년 추세", "anchor": "center"},
    {"id": "cagr", "text": "CAGR(%)", "anchor": "center"},
    {"id": "data_date", "text": "데이터기준일", "anchor": "center"}
]
