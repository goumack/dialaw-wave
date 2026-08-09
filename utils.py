"""Fonctions utilitaires : téléphones, WhatsApp, YouTube, dates."""

import re
from datetime import datetime
from urllib.parse import quote

INDICATIF_SENEGAL = "221"

# Préfixes mobiles sénégalais valides (Orange, Free, Expresso, Promobile)
PREFIXES_SN = ("70", "75", "76", "77", "78", "79")


def normaliser_telephone(brut: str) -> str:
    """Ramène un numéro sénégalais au format international sans « + ».

    77 123 45 67   -> 221771234567
    +221771234567  -> 221771234567
    00221771234567 -> 221771234567
    Renvoie une chaîne vide si le numéro n'est pas exploitable.
    """
    if not brut:
        return ""
    chiffres = re.sub(r"\D", "", brut)

    if chiffres.startswith("00"):
        chiffres = chiffres[2:]

    if len(chiffres) == 9 and chiffres[:2] in PREFIXES_SN:
        return INDICATIF_SENEGAL + chiffres
    if len(chiffres) == 12 and chiffres.startswith(INDICATIF_SENEGAL):
        return chiffres if chiffres[3:5] in PREFIXES_SN else ""
    # Numéro étranger : accepté tel quel s'il est plausible
    if 10 <= len(chiffres) <= 15:
        return chiffres
    return ""


def telephone_affichage(numero: str) -> str:
    """221771234567 -> +221 77 123 45 67"""
    if not numero:
        return ""
    if numero.startswith(INDICATIF_SENEGAL) and len(numero) == 12:
        n = numero[3:]
        return f"+{INDICATIF_SENEGAL} {n[0:2]} {n[2:5]} {n[5:7]} {n[7:9]}"
    return "+" + numero


def telephone_masque(numero: str) -> str:
    """Ne garde que les 4 derniers chiffres — filigrane du lecteur."""
    if not numero:
        return ""
    return "…" + numero[-4:]


def lien_whatsapp(numero: str, message: str) -> str:
    """Lien wa.me pré-rempli : ouvre WhatsApp avec le message déjà écrit."""
    if not numero:
        return ""
    return f"https://wa.me/{numero}?text={quote(message)}"


def ressemble_a_rtmp(valeur: str) -> bool:
    """Détecte une URL d'ingestion RTMP ou une clé de flux YouTube.

    Le RTMP sert à *pousser* l'image vers YouTube depuis OBS : quiconque
    possède ce couple URL + clé peut diffuser sur la chaîne. Il ne doit
    jamais être confondu avec le lien de visionnage envoyé aux clients.
    """
    if not valeur:
        return False
    texte = valeur.strip().lower()
    if texte.startswith(("rtmp://", "rtmps://")):
        return True
    return "rtmp.youtube.com" in texte or "/live2" in texte


def extraire_youtube_id(valeur: str) -> str:
    """Accepte un identifiant brut ou n'importe quelle forme d'URL YouTube.

    https://www.youtube.com/watch?v=ABC123     -> ABC123
    https://youtu.be/ABC123                    -> ABC123
    https://www.youtube.com/live/ABC123        -> ABC123
    https://www.youtube.com/embed/ABC123       -> ABC123
    ABC123                                     -> ABC123
    """
    if not valeur:
        return ""
    valeur = valeur.strip()

    if re.fullmatch(r"[A-Za-z0-9_-]{11}", valeur):
        return valeur

    motifs = (
        r"[?&]v=([A-Za-z0-9_-]{11})",
        r"youtu\.be/([A-Za-z0-9_-]{11})",
        r"/live/([A-Za-z0-9_-]{11})",
        r"/embed/([A-Za-z0-9_-]{11})",
        r"/shorts/([A-Za-z0-9_-]{11})",
    )
    for motif in motifs:
        trouve = re.search(motif, valeur)
        if trouve:
            return trouve.group(1)
    return ""


def parser_date(valeur: str):
    """Lit une date issue d'un champ datetime-local. None si vide ou invalide."""
    if not valeur:
        return None
    for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(valeur.strip(), fmt)
        except ValueError:
            continue
    return None


def date_affichage(valeur) -> str:
    """Affiche une date en français : 09/08/2026 à 20h30."""
    date = parser_date(valeur) if isinstance(valeur, str) else valeur
    if not date:
        return ""
    return date.strftime("%d/%m/%Y à %Hh%M")


def live_termine(config: dict) -> bool:
    """Vrai si l'heure de fin configurée est dépassée."""
    fin = parser_date(config.get("live_fin", ""))
    if not fin:
        return False
    return datetime.now() > fin


def formater_montant(montant) -> str:
    """1000 -> « 1 000 »"""
    try:
        return f"{int(montant):,}".replace(",", " ")
    except (TypeError, ValueError):
        return str(montant)


def construire_message(modele: str, **valeurs) -> str:
    """Remplit le modèle de message WhatsApp en tolérant les clés inconnues."""
    class _Tolerant(dict):
        def __missing__(self, cle):
            return "{" + cle + "}"

    try:
        return modele.format_map(_Tolerant(valeurs))
    except (ValueError, IndexError):
        return modele
