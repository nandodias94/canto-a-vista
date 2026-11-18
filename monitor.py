
import os
import json
import base64
import requests
from datetime import datetime, timezone

API_KEY = os.environ["FOOTBALL_API_KEY"]
BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]
REPOSITORY = os.environ["GITHUB_REPOSITORY"]

BASE_URL = "https://v3.football.api-sports.io"
HEADERS = {"x-apisports-key": API_KEY}
STATE_FILE = "canto_state.json"


def api_get(endpoint, params=None):
    response = requests.get(
        f"{BASE_URL}/{endpoint}",
        headers=HEADERS,
        params=params,
        timeout=25
    )
    response.raise_for_status()
    data = response.json()

    if data.get("errors"):
        raise RuntimeError(str(data["errors"]))

    return data.get("response", [])


def telegram(message):
    response = requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        json={"chat_id": CHAT_ID, "text": message},
        timeout=20
    )
    response.raise_for_status()


def github_headers():
    return {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json"
    }


def load_state():
    url = f"https://api.github.com/repos/{REPOSITORY}/contents/{STATE_FILE}"
    response = requests.get(url, headers=github_headers(), timeout=20)

    if response.status_code == 404:
        return {"sent": []}, None

    response.raise_for_status()
    data = response.json()
    content = base64.b64decode(data["content"]).decode("utf-8")

    return json.loads(content), data["sha"]


def save_state(state, sha):
    url = f"https://api.github.com/repos/{REPOSITORY}/contents/{STATE_FILE}"

    content = base64.b64encode(
        json.dumps(state, indent=2).encode("utf-8")
    ).decode("utf-8")

    payload = {
        "message": "Atualizar histórico Canto à Vista",
        "content": content
    }

    if sha:
        payload["sha"] = sha

    response = requests.put(
        url,
        headers=github_headers(),
        json=payload,
        timeout=20
    )
    response.raise_for_status()


def stat_value(team_stats, name):
    for item in team_stats:
        if item.get("type") == name:
            value = item.get("value")
            return int(value or 0)
    return 0


def get_match_stats(fixture_id):
    data = api_get("fixtures/statistics", {"fixture": fixture_id})

    if len(data) < 2:
        return None

    corners = 0
    shots = 0
    shots_on_target = 0

    for team in data:
        stats = team.get("statistics", [])
        corners += stat_value(stats, "Corner Kicks")
        shots += stat_value(stats, "Total Shots")
        shots_on_target += stat_value(stats, "Shots on Goal")

    return corners, shots, shots_on_target


def main():
    telegram("🟢 CANTO À VISTA — Teste de ligação concluído!")
    state, sha = load_state()
    sent = set(state.get("sent", []))

    fixtures = api_get("fixtures", {"live": "all"})

    candidates = []

    for match in fixtures:
        fixture = match["fixture"]
        teams = match["teams"]
        goals = match["goals"]

        minute = fixture["status"].get("elapsed") or 0
        fixture_id = fixture["id"]

        if fixture_id in sent:
            continue

        if not 70 <= minute <= 88:
            continue

        if teams["home"]["winner"] is True or teams["away"]["winner"] is True:
            continue

        home_goals = goals["home"] or 0
        away_goals = goals["away"] or 0

        # Jogos empatados ou com diferença máxima de um golo
        if abs(home_goals - away_goals) > 1:
            continue

        candidates.append(match)

    # Analisar primeiro os jogos mais próximos do final
    candidates.sort(
        key=lambda m: m["fixture"]["status"]["elapsed"] or 0,
        reverse=True
    )

    # Apenas uma consulta estatística por execução
    for match in candidates[:1]:
        fixture = match["fixture"]
        fixture_id = fixture["id"]

        stats = get_match_stats(fixture_id)

        if stats is None:
            continue

        corners, shots, shots_on_target = stats

        # Filtros iniciais de pressão ofensiva
        if corners < 6:
            continue

        if shots < 10:
            continue

        if shots_on_target < 3:
            continue

        home = match["teams"]["home"]["name"]
        away = match["teams"]["away"]["name"]

        score_home = match["goals"]["home"] or 0
        score_away = match["goals"]["away"] or 0
        minute = fixture["status"]["elapsed"]

        message = (
            "⚽ CANTO À VISTA ⚽\n\n"
            f"🏟 {home} - {away}\n"
            f"📊 Resultado: {score_home}-{score_away}\n"
            f"⏱ Minuto: {minute}'\n\n"
            f"🚩 Cantos: {corners}\n"
            f"🥅 Remates: {shots}\n"
            f"🎯 Remates à baliza: {shots_on_target}\n\n"
            "📈 Indicadores de pressão ofensiva.\n"
            "Possível oportunidade de mais um canto.\n"
            "⚠️ Alerta estatístico, não garantia de canto."
        )

        telegram(message)

        sent.add(fixture_id)
        state["sent"] = list(sent)[-500:]
        save_state(state, sha)

        print(f"Alerta enviado: {home} - {away}")
        break

    print(f"Jogos em direto: {len(fixtures)}")
    print(f"Jogos elegíveis: {len(candidates)}")
    print("Monitorização concluída.")


if __name__ == "__main__":
    main()
