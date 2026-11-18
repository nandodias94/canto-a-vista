
import os
import json
import base64
import time
import requests

# =====================================
# CONFIGURAÇÕES
# =====================================

BASE_URL = "https://v3.football.api-sports.io"

API_KEY = os.getenv("FOOTBALL_API_KEY")
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
REPOSITORY = os.getenv("GITHUB_REPOSITORY")

STATE_FILE = "state.json"

MAX_RETRIES = 5

API_HEADERS = {
    "x-apisports-key": API_KEY
}

GH_HEADERS = {
    "Authorization": f"Bearer {GITHUB_TOKEN}",
    "Accept": "application/vnd.github+json"
}


# =====================================
# ESPERA E RETENTATIVAS
# =====================================

def retry_wait(attempt, response=None):
    wait = 2 ** (attempt + 1)

    if response is not None:
        try:
            wait = int(response.headers.get("Retry-After", wait))
        except (ValueError, TypeError):
            pass

    wait = min(max(wait, 1), 60)

    print(f"Nova tentativa em {wait} segundos.")
    time.sleep(wait)


# =====================================
# API FOOTBALL
# =====================================

def api_get(endpoint, params=None):

    url = f"{BASE_URL}/{endpoint}"

    for attempt in range(MAX_RETRIES):

        try:
            response = requests.get(
                url,
                headers=API_HEADERS,
                params=params,
                timeout=25
            )

            if response.status_code == 429:
                print("API-Football: limite de pedidos atingido.")
                retry_wait(attempt, response)
                continue

            if response.status_code in (500, 502, 503, 504):
                print(
                    f"API-Football erro {response.status_code}. "
                    f"Tentativa {attempt + 1}/{MAX_RETRIES}."
                )
                retry_wait(attempt)
                continue

            response.raise_for_status()

            data = response.json()

            if data.get("errors"):
                raise RuntimeError(str(data["errors"]))

            return data.get("response", [])

        except (
            requests.exceptions.Timeout,
            requests.exceptions.ConnectionError
        ) as error:

            print(f"Falha de ligação à API: {error}")

            if attempt < MAX_RETRIES - 1:
                retry_wait(attempt)

        except requests.exceptions.HTTPError:
            raise

    raise RuntimeError(
        f"API-Football indisponível: {endpoint}"
    )


# =====================================
# TELEGRAM
# =====================================

def telegram(message):

    url = (
        f"https://api.telegram.org/"
        f"bot{BOT_TOKEN}/sendMessage"
    )

    for attempt in range(MAX_RETRIES):

        try:
            response = requests.post(
                url,
                json={
                    "chat_id": CHAT_ID,
                    "text": message
                },
                timeout=20
            )

            if response.status_code == 429:

                wait = 10

                try:
                    data = response.json()
                    wait = data.get(
                        "parameters", {}
                    ).get("retry_after", 10)
                except (ValueError, TypeError):
                    pass

                print("Telegram: limite de envios atingido.")
                retry_wait(attempt)

                continue

            if response.status_code in (500, 502, 503, 504):

                print(
                    f"Telegram erro {response.status_code}. "
                    f"Tentativa {attempt + 1}/{MAX_RETRIES}."
                )

                retry_wait(attempt)
                continue

            response.raise_for_status()

            data = response.json()

            if data.get("ok"):
                print("Mensagem enviada para o Telegram.")
                return True

            if data.get("error_code") == 429:

                wait = data.get(
                    "parameters", {}
                ).get("retry_after", 10)

                time.sleep(min(int(wait), 60))
                continue

            raise RuntimeError(
                f"Erro Telegram: {data}"
            )

        except (
            requests.exceptions.Timeout,
            requests.exceptions.ConnectionError
        ) as error:

            print(f"Falha de ligação ao Telegram: {error}")

            if attempt < MAX_RETRIES - 1:
                retry_wait(attempt)

        except requests.exceptions.HTTPError:
            raise

    raise RuntimeError(
        "Telegram indisponível após várias tentativas."
    )


# =====================================
# HISTÓRICO DE ALERTAS
# =====================================

def load_state():

    url = (
        f"https://api.github.com/repos/{REPOSITORY}"
        f"/contents/{STATE_FILE}"
    )

    for attempt in range(MAX_RETRIES):

        try:
            response = requests.get(
                url,
                headers=GH_HEADERS,
                timeout=20
            )

            if response.status_code == 404:
                return {"sent": []}, None

            if response.status_code in (500, 502, 503, 504, 429):
                print(
                    f"GitHub erro {response.status_code} "
                    "ao consultar histórico."
                )
                retry_wait(attempt, response)
                continue

            response.raise_for_status()

            data = response.json()

            content = base64.b64decode(
                data["content"]
            ).decode("utf-8")

            state = json.loads(content)

            if not isinstance(state, dict):
                raise RuntimeError("Histórico inválido.")

            if not isinstance(state.get("sent", []), list):
                raise RuntimeError("Lista de alertas inválida.")

            return state, data["sha"]

        except (
            requests.exceptions.Timeout,
            requests.exceptions.ConnectionError
        ) as error:

            print(f"Erro ao consultar GitHub: {error}")

            if attempt < MAX_RETRIES - 1:
                retry_wait(attempt)

    raise RuntimeError(
        "Não foi possível consultar o histórico no GitHub."
    )


def save_state(state, sha):

    url = (
        f"https://api.github.com/repos/{REPOSITORY}"
        f"/contents/{STATE_FILE}"
    )

    content = base64.b64encode(
        json.dumps(
            state,
            indent=2,
            ensure_ascii=False
        ).encode("utf-8")
    ).decode("utf-8")

    payload = {
        "message": "Atualizar histórico Canto à Vista",
        "content": content
    }

    if sha:
        payload["sha"] = sha

    for attempt in range(MAX_RETRIES):

        try:
            response = requests.put(
                url,
                headers=GH_HEADERS,
                json=payload,
                timeout=20
            )

            if response.status_code in (500, 502, 503, 504, 429):
                print(
                    f"GitHub erro {response.status_code} "
                    "ao guardar histórico."
                )
                retry_wait(attempt, response)
                continue

            response.raise_for_status()

            print("Histórico guardado no GitHub.")
            return True

        except (
            requests.exceptions.Timeout,
            requests.exceptions.ConnectionError
        ) as error:

            print(f"Erro ao guardar histórico: {error}")

            if attempt < MAX_RETRIES - 1:
                retry_wait(attempt)

        except requests.exceptions.HTTPError:
            raise

    raise RuntimeError(
        "Não foi possível guardar o histórico no GitHub."
    )


# =====================================
# ESTATÍSTICAS
# =====================================

def stat_value(stats, name):

    for item in stats:

        if item.get("type") == name:

            value = item.get("value")

            if isinstance(value, str):
                value = value.replace("%", "")

            try:
                return int(float(value or 0))
            except (ValueError, TypeError):
                return 0

    return 0


def get_match_stats(fixture_id):

    data = api_get(
        "fixtures/statistics",
        {"fixture": fixture_id}
    )

    print(
        f"DEBUG - Jogo {fixture_id}: "
        f"{len(data)} equipas recebidas"
    )

    for item in data:
        print(
            "DEBUG - Equipa:",
            item.get("team", {}).get("name"),
            "| Estatísticas:",
            len(item.get("statistics", []))
        )

    if len(data) < 2:
        return None

    corners = 0
    shots = 0
    shots_target = 0

    for team in data:

        stats = team.get("statistics", [])

        corners += stat_value(stats, "Corner Kicks")
        shots += stat_value(stats, "Total Shots")
        shots_target += stat_value(stats, "Shots on Goal")

    return corners, shots, shots_target


# =====================================
# FASE DO JOGO
# =====================================

def get_phase(minute, status):

    # Primeira parte: minuto 35 até ao intervalo,
    # incluindo os minutos de compensação.

    if status == "1H" and minute >= 35:
        return "PRIMEIRA PARTE"

    # Final do jogo: minuto 75 até ao fim,
    # incluindo os minutos de compensação.

    if status == "2H" and minute >= 75:
        return "FINAL DO JOGO"

    return None


# =====================================
# EXECUÇÃO PRINCIPAL
# =====================================

def main():

    required = {
        "FOOTBALL_API_KEY": API_KEY,
        "TELEGRAM_BOT_TOKEN": BOT_TOKEN,
        "TELEGRAM_CHAT_ID": CHAT_ID,
        "GITHUB_TOKEN": GITHUB_TOKEN,
        "GITHUB_REPOSITORY": REPOSITORY
    }

    for name, value in required.items():

        if not value:
            raise RuntimeError(
                f"Configuração em falta: {name}"
            )

    state, sha = load_state()

    sent = set(state.get("sent", []))

    fixtures = api_get(
        "fixtures",
        {"live": "all"}
    )

    candidates = []

    for match in fixtures:

        fixture = match["fixture"]

        status = fixture["status"].get("short")
        minute = fixture["status"].get("elapsed") or 0

        phase = get_phase(minute, status)

        if not phase:
            continue

        fixture_id = fixture["id"]

        alert_key = f"{fixture_id}:{phase}"

        if alert_key in sent:
            continue

        goals = match["goals"]

        home_goals = goals["home"] or 0
        away_goals = goals["away"] or 0

        # Jogos equilibrados

        if abs(home_goals - away_goals) > 1:
            continue

        candidates.append(
            (minute, match, phase, alert_key)
        )

    candidates.sort(
        key=lambda item: item[0],
        reverse=True
    )

    print(f"Jogos em direto: {len(fixtures)}")
    print(f"Jogos dentro das janelas: {len(candidates)}")

    if not candidates:
        print("Nenhum jogo dentro das janelas de análise.")
        return

    # Uma consulta estatística por execução

    minute, match, phase, alert_key = candidates[0]

    fixture_id = match["fixture"]["id"]

    print("Jogo escolhido:", fixture_id)

    stats = get_match_stats(fixture_id)

    if stats is None:
        print("Estatísticas indisponíveis.")
        return

    corners, shots, shots_target = stats

    print(
        f"Jogo analisado: "
        f"{match['teams']['home']['name']} - "
        f"{match['teams']['away']['name']}"
    )

    print(
        f"Cantos: {corners} | "
        f"Remates: {shots} | "
        f"À baliza: {shots_target}"
    )

    # =================================
    # CRITÉRIOS EXIGENTES
    # =================================

    if phase == "PRIMEIRA PARTE":

        minimum_corners = 4
        minimum_shots = 8
        minimum_target = 2

    else:

        minimum_corners = 6
        minimum_shots = 10
        minimum_target = 3

    if corners < minimum_corners:
        print("Rejeitado: poucos cantos.")
        return

    if shots < minimum_shots:
        print("Rejeitado: poucos remates.")
        return

    if shots_target < minimum_target:
        print("Rejeitado: poucos remates à baliza.")
        return

    # =================================
    # PREPARAR ALERTA
    # =================================

    home = match["teams"]["home"]["name"]
    away = match["teams"]["away"]["name"]

    home_goals = match["goals"]["home"] or 0
    away_goals = match["goals"]["away"] or 0

    message = (
        "🚩 CANTO À VISTA 🚩\n\n"
        f"🏟 {home} - {away}\n"
        f"📊 Resultado: {home_goals}-{away_goals}\n"
        f"⏱ Minuto: {minute}'\n"
        f"📍 Fase: {phase}\n\n"
        f"🚩 Cantos totais: {corners}\n"
        f"🥅 Remates totais: {shots}\n"
        f"🎯 À baliza: {shots_target}\n\n"
        "📈 Indicadores estatísticos fortes.\n"
        "Possível oportunidade de mais um canto.\n\n"
        "⚠️ Não é garantia de canto. "
        "Confirma o jogo antes de qualquer entrada."
    )

    # =================================
    # ENVIAR E REGISTAR
    # =================================

    telegram(message)

    sent.add(alert_key)

    state["sent"] = list(sent)[-500:]

    save_state(state, sha)

    print("Alerta enviado e registado com sucesso!")


if __name__ == "__main__":
    main()
