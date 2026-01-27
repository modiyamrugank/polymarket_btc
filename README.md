# Polymarket BTC 15-Minute Trading Bot

A trading bot that bets on Polymarket's BTC 15-minute up/down markets based on candlestick patterns.

## Strategy

The bot uses a simple momentum-based strategy aligned with Polymarket's 15-minute windows:

### Timing

```
15-min Window:    |-------- 15 minutes --------|
                  :00        :05        :10    :15
                   |----------|----------|------|
                   Candle 1   Candle 2   BET!   Market
                   (5 min)    (5 min)           Resolves
```

- **15-minute windows**: :00-:15, :15-:30, :30-:45, :45-:00
- **Bet times**: :10, :25, :40, :55 (after two 5-min candles close)
- **Resolution**: 5 minutes after each bet

### Signal Logic

| Candles in Window | Action |
|-------------------|--------|
| GREEN + GREEN | Bet **UP** (BTC will go up) |
| RED + RED | Bet **DOWN** (BTC will go down) |
| GREEN + RED | **SKIP** (no clear trend) |
| RED + GREEN | **SKIP** (no clear trend) |

The bot analyzes the two 5-minute candles within each 15-minute window to predict the final 5-minute movement.

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

1. **Window Tracking**: Bot identifies the current 15-minute window (e.g., 12:00-12:15)
2. **Wait for Candles**: Waits until minute :10 of the window (e.g., 12:10)
3. **Price Fetcher**: Gets the two 5-minute candles within the window from Binance
4. **Candle Analyzer**: Analyzes the candle colors to generate a signal (UP/DOWN/SKIP)
5. **Market Discovery**: Finds the active Polymarket BTC 15-minute market
6. **Bet Placement**: Places the bet for the remaining 5 minutes (or simulates in monitoring mode)
7. **Tracking**: Records all bets with timestamps, signals, and outcomes
8. **Next Window**: Waits for the next 15-minute window and repeats

## Risks & Disclaimers

- **This is experimental software** - use at your own risk
- Past performance does not guarantee future results
- The simple 2-candle strategy may not be profitable long-term
- Polymarket availability varies by region
- Never risk more than you can afford to lose
- Keep your private key secure and never share it

## License

MIT
