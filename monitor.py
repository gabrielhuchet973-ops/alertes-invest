"""Alertes d'investissement : achat sur forte baisse, vente sur objectif.
Lance par GitHub Actions. Notifications via ntfy.sh (secret NTFY_TOPIC)."""
import json, os, datetime as dt
import requests
import yfinance as yf

BUDGET = 40          # euros par alerte d'achat
FEE = 1.0            # frais Trade Republic par ordre
SELL_TARGET = 12     # % de gain net vise
TRAIL_START = 8      # % de gain a partir duquel on surveille le recul
TRAIL_DROP = 4       # % de recul depuis le pic qui declenche la vente
COOLDOWN_DAYS = 7    # pas deux alertes d'achat sur le meme titre en moins de 7 jours

# ticker Yahoo : (nom, seuil de baisse en % depuis le plus haut de 6 mois)
WATCH = {
    "IWDA.AS": ("ETF MSCI World", 8),
    "SXR8.DE": ("ETF S&P 500", 8),
    "SXRV.DE": ("ETF Nasdaq 100", 10),
    "AAPL": ("Apple", 15),
    "MSFT": ("Microsoft", 15),
    "MC.PA": ("LVMH", 20),
    "TTE.PA": ("TotalEnergies", 15),
}

def load(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        return default

def save(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def notify(title, msg, tag):
    topic = os.environ.get("NTFY_TOPIC")
    print(f"[{title}] {msg}")
    if not topic:
        return
    requests.post(f"https://ntfy.sh/{topic}", data=msg.encode("utf-8"),
                  headers={"Title": title, "Tags": tag}, timeout=15)

def price_info(ticker):
    h = yf.Ticker(ticker).history(period="6mo")["Close"].dropna()
    if h.empty:
        return None
    return float(h.iloc[-1]), float(h.max())

def main():
    positions = load("positions.json", [])
    state = load("state.json", {"last_buy": {}, "sold_alerted": []})
    today = dt.date.today()

    # 1) Alertes d'achat
    for ticker, (name, threshold) in WATCH.items():
        try:
            info = price_info(ticker)
        except Exception as e:
            print(f"{ticker}: erreur {e}")
            continue
        if not info:
            continue
        price, high = info
        drop = (high - price) / high * 100
        last = state["last_buy"].get(ticker)
        recent = last and (today - dt.date.fromisoformat(last)).days < COOLDOWN_DAYS
        if drop >= threshold and not recent:
            notify("Alerte achat",
                   f"{name} ({ticker}) : -{drop:.1f}% depuis le plus haut de 6 mois "
                   f"(cours {price:.2f}). Idee : investir {BUDGET} EUR. "
                   f"Frais d'ordre ~{FEE/BUDGET*100:.1f}%.",
                   "chart_with_downwards_trend")
            state["last_buy"][ticker] = today.isoformat()

    # 2) Alertes de vente sur les positions saisies
    for p in positions:
        try:
            info = price_info(p["ticker"])
        except Exception as e:
            print(f"{p['ticker']}: erreur {e}")
            continue
        if not info:
            continue
        price, _ = info
        p["peak"] = max(p.get("peak", p["buy_price"]), price)
        value = p["amount"] * price / p["buy_price"]
        net_pct = (value - p["amount"] - 2 * FEE) / p["amount"] * 100
        peak_gain = (p["peak"] / p["buy_price"] - 1) * 100
        pid = p["id"]
        if pid in state["sold_alerted"]:
            continue
        if net_pct >= SELL_TARGET:
            notify("Alerte vente",
                   f"{p['ticker']} : +{net_pct:.1f}% net de frais, objectif atteint. "
                   f"Valeur ~{value:.2f} EUR.", "moneybag")
            state["sold_alerted"].append(pid)
        elif peak_gain >= TRAIL_START and price <= p["peak"] * (1 - TRAIL_DROP / 100):
            notify("Alerte vente",
                   f"{p['ticker']} recule de {TRAIL_DROP}% depuis son pic "
                   f"(gain net actuel {net_pct:.1f}%). A envisager de vendre.", "warning")
            state["sold_alerted"].append(pid)

    save("positions.json", positions)
    save("state.json", state)

if __name__ == "__main__":
    main()
