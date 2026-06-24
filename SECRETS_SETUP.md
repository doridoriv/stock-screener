# Secrets setup

Never commit real API keys to this repository.

## Required names

- `DART_API_KEY`
- `KRX_API_KEY`
- `SERPAPI_KEY`
- `FINNHUB_API_KEY`

## Local run

Create an untracked `.env` file in this folder.

```env
DART_API_KEY=your_key_here
KRX_API_KEY=your_key_here
SERPAPI_KEY=your_key_here
FINNHUB_API_KEY=your_key_here
```

`.env` is ignored by Git.

## Streamlit Cloud

Open app settings and add the same names under Secrets.

```toml
DART_API_KEY = "your_key_here"
KRX_API_KEY = "your_key_here"
SERPAPI_KEY = "your_key_here"
FINNHUB_API_KEY = "your_key_here"
```

## GitHub Actions

Add the same names under repository Settings > Secrets and variables > Actions.
The workflow reads them as environment variables and never prints them.
