#!/usr/bin/env python3
"""
Script de mise a jour automatique de data.json pour la Carte Emergency HUB.

Source principale : le fil officiel des mises a jour sur le Developer Forum
Roblox (https://devforum.roblox.com/t/emergency-hamburg-updates-and-information-en/2388146),
qui liste toujours en premier la derniere mise a jour du jeu ("Latest Updates").

Ce que fait le script :
  1. Va chercher ce fil et repere le titre de la toute derniere mise a jour
     (ex: "V3.15 Jeweler & Trucking Update").
  2. Si ce titre est different de celui deja enregistre dans data.json,
     il met a jour data.json (section "meta") avec la nouvelle version,
     et ajoute une ligne dans le changelog affiche sur l'onglet Info du site.
  3. (Best effort, secondaire) essaie aussi de rafraichir prix/vitesse de
     quelques vehicules suivis individuellement - voir TRACKED_VEHICLES.
     Si ca echoue, ce n'est pas grave : le reste continue de fonctionner.

Le script ne touche JAMAIS aux donnees existantes s'il n'est pas sur a 100%
d'avoir trouve une info valide : mieux vaut ne rien changer que publier une
erreur sur le site.

Utilisation manuelle :
    python3 update_data.py
"""

from __future__ import annotations

import json
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

try:
    from bs4 import BeautifulSoup
except ImportError:
    print(
        "ERREUR : le module 'beautifulsoup4' n'est pas installe.\n"
        "Lance : pip install beautifulsoup4",
        file=sys.stderr,
    )
    raise

DATA_FILE = Path(__file__).parent / "data.json"
UPDATES_THREAD_URL = (
    "https://devforum.roblox.com/t/emergency-hamburg-updates-and-information-en/2388146"
)
USER_AGENT = "EmergencyHUB-MapUpdater/1.0 (contact: mets-ton-email-ici)"

# Vehicules suivis individuellement pour prix/vitesse (best effort).
# Ajoute une ligne ici si tu veux suivre un vehicule de plus - il faut
# l'URL exacte de sa page sur wiki.emergency-hamburg.com (verifie-la a la main
# une premiere fois dans ton navigateur).
TRACKED_VEHICLES: list[dict] = [
    # Exemple, a completer/verifier toi-meme :
    # {
    #     "path": ["trucker", "trucks"],
    #     "name": "Stellar S100 Electric",
    #     "url": "https://wiki.emergency-hamburg.com/en/Vehicles/Stellar-S100-Electric",
    # },
]


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=25) as resp:
        return resp.read().decode("utf-8", errors="replace")


def find_latest_update_title(html: str) -> tuple[str, str] | None:
    """
    Retourne (version, titre_complet) de la derniere mise a jour listee
    dans le fil "Updates and Information", ou None si non trouve.

    Exemple de retour : ("3.15", "V3.15 Jeweler & Trucking Update")
    """
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(separator=" ", strip=True)

    marker = "Latest Updates"
    idx = text.find(marker)
    search_zone = text[idx:] if idx != -1 else text

    match = re.search(
        r"\bV(\d+(?:\.\d+)+)\s+([A-Za-z0-9\u00C0-\u00FF&,'\u2019\- ]{3,80}?Update)\b",
        search_zone,
    )
    if not match:
        return None

    version = match.group(1)
    title = f"V{version} {match.group(2)}".strip()
    return version, title


def update_meta(data: dict) -> bool:
    """Met a jour data['meta'] si une nouvelle version est detectee. Retourne True si change."""
    try:
        html = fetch(UPDATES_THREAD_URL)
    except Exception as exc:  # noqa: BLE001
        print(f"[avertissement] Impossible de charger le fil des mises a jour : {exc}")
        return False

    result = find_latest_update_title(html)
    if result is None:
        print(
            "[avertissement] Impossible de trouver la derniere mise a jour dans la page "
            "(structure du forum peut-etre changee)."
        )
        return False

    version, title = result
    meta = data.setdefault("meta", {})
    meta["lastCheckedAt"] = datetime.now(timezone.utc).isoformat(timespec="seconds")

    if meta.get("latestVersion") == version:
        print(f"[ok] Deja a jour (version {version}), rien a changer.")
        return False

    old_version = meta.get("latestVersion")
    print(f"[maj] Nouvelle version detectee : {old_version!r} -> {version!r} ({title})")

    meta["latestVersion"] = version
    meta["latestUpdateTitle"] = title
    meta["latestUpdateUrl"] = UPDATES_THREAD_URL

    changelog = meta.setdefault("changelog", [])
    changelog.insert(0, {
        "version": version,
        "title": title,
        "detectedAt": meta["lastCheckedAt"],
    })
    meta["changelog"] = changelog[:10]

    return True


def find_vehicle(data: dict, path: list[str], name: str) -> dict | None:
    node = data
    for key in path:
        node = node.get(key)
        if node is None:
            return None
    for vehicle in node:
        if vehicle.get("name") == name:
            return vehicle
    return None


def extract_price(html: str) -> str | None:
    for pat in (r"\$[\d,]+", r"[\d\s]{3,}\s?\u20ac", r"[\d\s]{2,}\s?XP"):
        m = re.search(pat, html)
        if m:
            return m.group(0).strip()
    return None


def extract_speed(html: str) -> str | None:
    m = re.search(r"Maximum Speed:?\**\s*([\d]+\s*km/h)", html, re.I)
    return m.group(1).strip() if m else None


def update_tracked_vehicles(data: dict) -> bool:
    changed = False
    for entry in TRACKED_VEHICLES:
        name = entry["name"]
        vehicle = find_vehicle(data, entry["path"], name)
        if vehicle is None:
            print(f"[ignore] '{name}' n'existe pas dans data.json, on saute.")
            continue
        try:
            html = fetch(entry["url"])
        except Exception as exc:  # noqa: BLE001
            print(f"[avertissement] Impossible de charger {entry['url']} : {exc}")
            continue

        text = BeautifulSoup(html, "html.parser").get_text(separator=" ", strip=True)
        new_price = extract_price(text)
        new_speed = extract_speed(text)

        if new_price and new_price != vehicle.get("price"):
            print(f"[maj] {name}: prix {vehicle.get('price')!r} -> {new_price!r}")
            vehicle["price"] = new_price
            changed = True
        if new_speed and new_speed != vehicle.get("speed"):
            print(f"[maj] {name}: vitesse {vehicle.get('speed')!r} -> {new_speed!r}")
            vehicle["speed"] = new_speed
            changed = True

    return changed


def main() -> int:
    if not DATA_FILE.exists():
        print(f"ERREUR : {DATA_FILE} introuvable.", file=sys.stderr)
        return 1

    data = json.loads(DATA_FILE.read_text(encoding="utf-8"))

    changed_meta = update_meta(data)
    changed_vehicles = update_tracked_vehicles(data) if TRACKED_VEHICLES else False

    if changed_meta or changed_vehicles:
        DATA_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        summary_lines = []
        if changed_meta:
            summary_lines.append(f"Nouvelle mise a jour du jeu : {data['meta']['latestUpdateTitle']}")
        if changed_vehicles:
            summary_lines.append("Donnees vehicules rafraichies.")
        Path(__file__).parent.joinpath("last_update_summary.txt").write_text(
            "\n".join(summary_lines), encoding="utf-8"
        )
        print("\ndata.json mis a jour avec succes.")
    else:
        DATA_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print("\nAucun changement de contenu, mais lastCheckedAt a ete rafraichi.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
