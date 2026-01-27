# Polymarket BTC 15-Minute Trading Bot

A trading bot that bets on Polymarket's BTC 15-minute up/down markets based on candlestick patterns.

## Strategy

The bot uses a simple momentum-based strategy:

| Last 2 Candles | Action |
|---------------|--------|
| GREEN + GREEN | Bet **UP** (BTC will go up) |
| RED + RED | Bet **DOWN** (BTC will go down) |
| GREEN + RED | **SKIP** (no clear trend) |
| RED + GREEN | **SKIP** (no clear trend) |

The bot analyzes the last two closed 5-minute candles from Binance to predict the next 15-minute price movement.

## Features

- Real-time BTC price data from Binance (no API key required for public data)
- Automatic Polymarket market discovery
- Configurable bet amounts and odds thresholds
- **Monitoring mode**: Runs without credentials, logging what bets would be placed
- Bet history tracking with win/loss statistics
- Structured logging for easy debugging

## Installation

1. Clone the repository:
```bash
git clone https://github.com/your-repo/polymarket_btc.git
cd polymarket_btc
```

2. Create a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Copy the environment template:
```bash
cp .env.example .env
```

5. Edit `.env` with your configuration (see Configuration section)

## Configuration

Edit the `.env` file with your settings:

### Required for Live Trading
```bash
WALLET_ADDRESS=0x...     # Your Polygon wallet address
PRIVATE_KEY=0x...        # Your wallet private key (keep secret!)
```

### Optional
```bash
POLYMARKET_API_KEY=      # For higher rate limits
BET_AMOUNT=1.0           # Amount to bet in USDC
MIN_ODDS=0.4             # Minimum odds (40%)
MAX_ODDS=0.65            # Maximum odds (65%)
DRY_RUN=true             # Set to false for live trading
LOG_LEVEL=INFO           # DEBUG, INFO, WARNING, ERROR
```

## Usage

### Run the Bot
```bash
python main.py
```

### Run Once (single iteration)
```bash
python main.py --once
```

### View Statistics
```bash
python main.py --status
```

### Test Candle Fetching
```bash
python main.py --test-candles
```

### Test Market Discovery
```bash
python main.py --test-market
```

## Monitoring Mode

If `WALLET_ADDRESS` or `PRIVATE_KEY` are not set, the bot runs in **monitoring mode**:

- Fetches real BTC candle data
- Analyzes candle patterns
- Logs what bets would be placed
- Tracks simulated results in `bet_history.json`
- No actual bets are placed

This is useful for:
- Testing the strategy before committing funds
- Monitoring market conditions
- Validating the bot's logic

## Project Structure

```
polymarket_btc/
├── main.py                 # Entry point
├── requirements.txt        # Dependencies
├── .env.example           # Environment template
├── .gitignore
├── README.md
└── src/
    ├── __init__.py
    ├── config.py          # Configuration management
    ├── price_fetcher.py   # Binance candle data
    ├── candle_analyzer.py # Signal generation logic
    ├── polymarket_client.py # Polymarket API integration
    ├── tracker.py         # Bet tracking & statistics
    └── bot.py             # Main bot logic
```

## How It Works

1. **Price Fetcher**: Gets 5-minute BTC/USDT candles from Binance's public API
2. **Candle Analyzer**: Examines the last two closed candles to generate a signal
3. **Market Discovery**: Searches Polymarket for active BTC 15-minute markets
4. **Bet Placement**: Places the bet via Polymarket's CLOB API (or simulates in monitoring mode)
5. **Tracking**: Records all bets and calculates performance statistics

## Risks & Disclaimers

- **This is experimental software** - use at your own risk
- Past performance does not guarantee future results
- The simple 2-candle strategy may not be profitable long-term
- Polymarket availability varies by region
- Never risk more than you can afford to lose
- Keep your private key secure and never share it

## License

MIT
