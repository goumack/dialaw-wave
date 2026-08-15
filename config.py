"""Configuration de l'application Dialaw TV Live.

Les valeurs sensibles sont lues depuis les variables d'environnement
(fichier .env à la racine du projet). Voir .env.example.
"""

import os
import secrets
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


def _charger_env():
    """Charge le fichier .env sans dépendance externe."""
    fichier = BASE_DIR / ".env"
    if not fichier.exists():
        return
    for ligne in fichier.read_text(encoding="utf-8").splitlines():
        ligne = ligne.strip()
        if not ligne or ligne.startswith("#") or "=" not in ligne:
            continue
        cle, valeur = ligne.split("=", 1)
        cle = cle.strip()
        valeur = valeur.strip().strip('"').strip("'")
        # Les variables déjà définies dans le système restent prioritaires
        os.environ.setdefault(cle, valeur)


_charger_env()


class Config:
    # --- Sécurité -------------------------------------------------------
    SECRET_KEY = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    # Passe à True automatiquement en production (HTTPS)
    SESSION_COOKIE_SECURE = os.environ.get("FLASK_ENV") == "production"
    PERMANENT_SESSION_LIFETIME = 60 * 60 * 12  # 12 heures

    # --- Base de données ------------------------------------------------
    # Un nom simple reste dans le dossier du projet ; un chemin absolu est
    # respecté tel quel — c'est ainsi que Render pointe vers son disque
    # persistant (/var/data), hors du dossier de code effacé à chaque déploiement.
    DATABASE = str(Path(os.environ.get("DATABASE_NAME", "dialaw_live.db")))
    if not Path(DATABASE).is_absolute():
        DATABASE = str(BASE_DIR / DATABASE)

    # --- Compte administrateur initial ----------------------------------
    # Créé au tout premier démarrage seulement. En production, ces deux
    # valeurs viennent des variables d'environnement : aucun mot de passe
    # réel ne doit figurer dans le code publié sur GitHub.
    ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@dialawtv.sn")
    ADMIN_MOT_DE_PASSE = os.environ.get("ADMIN_MOT_DE_PASSE", "dialaw2026")

    # Refuse de démarrer en production avec les identifiants d'usine
    MOT_DE_PASSE_USINE = "dialaw2026"

    # --- Anti-force brute sur la saisie du code -------------------------
    # Le compteur principal porte sur l'appareil (cookie) : chez les
    # opérateurs mobiles sénégalais, des centaines de clients partagent la
    # même IP publique. Le plafond par IP ne sert qu'à stopper un bourrinage.
    MAX_TENTATIVES_CODE = 8          # par appareil
    MAX_TENTATIVES_IP = 120          # par adresse IP
    FENETRE_TENTATIVES = 15 * 60     # 15 minutes, en secondes

    # --- Divers ---------------------------------------------------------
    DEVISE = "FCFA"


# Valeurs par défaut de la configuration modifiable depuis le back-office.
# Elles sont insérées en base au premier démarrage, puis éditables via /admin.
CONFIG_PAR_DEFAUT = {
    "titre_live": "Grand Direct Dialaw TV",
    "description_live": (
        "Suivez l'émission en direct et exclusive de Dialaw TV. "
        "Accès immédiat après paiement."
    ),
    "prix": "1000",
    "lien_wave": "https://pay.wave.com/m/M_sn_wF5yaWQxUVkW/c/sn/",
    "numero_wave": "221772197773",   # numéro Wave affiché en secours
    "youtube_id": "",                # identifiant du direct non répertorié
    "live_debut": "",                # format YYYY-MM-DDTHH:MM
    "live_fin": "",                  # au-delà, les codes ne fonctionnent plus
    "ventes_ouvertes": "1",          # « 1 » ou « 0 »
    "max_appareils": "1",            # nombre d'appareils autorisés par code
    "whatsapp_support": "221772197773",   # numéro WhatsApp de la rédaction
    "site_url": "",                  # ex. https://live.dialawtv.sn
    # Affiche personnalisée pour l'aperçu WhatsApp. Vide : une image est
    # générée à partir du titre et du prix.
    "image_apercu": "",
    "afficher_chat": "0",            # afficher le chat YouTube à côté du lecteur
    # « 1 » : le flux passe par le site, qui masque l'adresse d'origine mais
    # consomme la bande passante de l'hébergement — tenable pour quelques
    # dizaines de spectateurs seulement.
    # « 0 » : le navigateur va chercher la vidéo directement sur le serveur
    # de diffusion. Obligatoire dès que l'audience se compte en centaines.
    "relayer_flux": "0",
    # Volontairement sans emoji hors du plan Unicode de base : les pictogrammes
    # récents (👉 U+1F449, 🔑 U+1F511) s'affichent en « ? » sur certains
    # clients WhatsApp. Les puces et guillemets ci-dessous passent partout.
    "message_whatsapp": (
        "Bonjour {nom}, votre paiement de {montant} {devise} pour "
        "« {titre} » est confirmé.\n\n"
        "▸ Touchez ce lien, le direct s'ouvre :\n"
        "{lien}\n\n"
        "Rien d'autre à faire : votre accès est déjà dans le lien.\n\n"
        "Ce lien est personnel et n'ouvre le direct que sur un seul "
        "appareil. Le partager vous en priverait vous-même.\n\n"
        "(Mot de passe {code}, si on vous le demande un jour.)\n"
        "Bon direct !\n"
        "Dialaw TV"
    ),
}
