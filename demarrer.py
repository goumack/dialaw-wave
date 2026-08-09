"""Lanceur de Dialaw TV Live.

    python demarrer.py

Vérifie les dépendances, ouvre le navigateur, démarre le serveur.
Équivalent multiplateforme de demarrer.bat.

Options :
    --port 8000      écouter sur un autre port
    --sans-navigateur ne pas ouvrir le navigateur
    --reseau         rendre le site visible depuis les autres appareils
                     du réseau local (téléphones connectés au même wifi)
"""

import argparse
import ipaddress
import socket
import subprocess
import sys
import threading
import webbrowser


def verifier_dependances():
    """Installe Flask s'il manque, plutôt que d'échouer sur un import."""
    try:
        import flask  # noqa: F401
        return True
    except ImportError:
        pass

    print("  Flask n'est pas installé. Installation en cours...\n")
    resultat = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-r", "requirements.txt"]
    )
    if resultat.returncode != 0:
        print("\n  L'installation a échoué.")
        print("  Lancez manuellement :  pip install -r requirements.txt")
        return False

    print()
    return True


def adresse_locale() -> str:
    """Adresse IP de cette machine sur le réseau local.

    Aucune donnée n'est envoyée : on ouvre une socket UDP vers une adresse
    externe uniquement pour que le système révèle l'interface qu'il
    utiliserait, puis on la referme.
    """
    sonde = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sonde.connect(("8.8.8.8", 80))
        return sonde.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sonde.close()


def port_disponible(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as test:
        test.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            test.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def main():
    analyseur = argparse.ArgumentParser(
        description="Démarre le site de billetterie Dialaw TV Live."
    )
    analyseur.add_argument("--port", type=int, default=5000,
                           help="port d'écoute (5000 par défaut)")
    analyseur.add_argument("--sans-navigateur", action="store_true",
                           help="ne pas ouvrir le navigateur au démarrage")
    analyseur.add_argument("--reseau", action="store_true",
                           help="rendre le site accessible depuis le wifi local")
    options = analyseur.parse_args()

    if not verifier_dependances():
        return 1

    if not port_disponible(options.port):
        print(f"  Le port {options.port} est déjà utilisé.")
        print("  Une autre instance tourne peut-être déjà : regardez si")
        print(f"  http://127.0.0.1:{options.port}/ répond dans votre navigateur.")
        print(f"  Sinon, choisissez un autre port :  python demarrer.py --port 8000")
        return 1

    # L'import doit suivre la vérification des dépendances
    from app import app

    url_locale = f"http://127.0.0.1:{options.port}/"

    print()
    print("  " + "=" * 46)
    print("    DIALAW TV LIVE")
    print("  " + "=" * 46)
    print(f"    Site public   {url_locale}")
    print(f"    Back-office   {url_locale}admin")
    print(f"    Connexion     {app.config['ADMIN_EMAIL']}")
    print(f"                  {app.config['ADMIN_MOT_DE_PASSE']}")

    if options.reseau:
        ip = adresse_locale()
        print()
        print("    Depuis un téléphone du même wifi :")
        print(f"                  http://{ip}:{options.port}/")
        try:
            if ipaddress.ip_address(ip).is_loopback:
                print("    (adresse réseau introuvable — vérifiez votre connexion)")
        except ValueError:
            pass

    print()
    print("    Arrêter : Ctrl+C")
    print("  " + "=" * 46)
    print()

    if not options.sans_navigateur:
        # Différé : le navigateur ne doit s'ouvrir qu'une fois le serveur prêt
        threading.Timer(1.2, lambda: webbrowser.open(url_locale)).start()

    hote = "0.0.0.0" if options.reseau else "127.0.0.1"
    try:
        # Rechargeur désactivé : il relancerait ce script en entier,
        # rouvrant le navigateur à chaque sauvegarde de fichier.
        app.run(host=hote, port=options.port, debug=False)
    except KeyboardInterrupt:
        print("\n  Serveur arrêté. À bientôt !\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
