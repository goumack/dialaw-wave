"""Relais du flux HLS : sert la vidéo sans révéler le serveur d'origine.

Deux problèmes réglés d'un coup :

1. **Le mélange HTTP / HTTPS.** Le serveur de diffusion n'écoute qu'en HTTP.
   Un navigateur sur une page HTTPS refuse d'y toucher (« contenu mixte »).
   En passant par le site, le navigateur ne voit que du HTTPS.

2. **L'adresse d'origine reste secrète.** Le spectateur ne voit que des URL
   de votre propre site. Il ne peut donc pas copier l'adresse du flux pour
   la partager — contrairement à une intégration YouTube, dont le logo mène
   à une page publique.

Le relais ne sert que les fichiers du flux (playlists .m3u8 et segments .ts),
et uniquement sous le préfixe configuré : il ne peut pas être détourné pour
atteindre autre chose sur le serveur d'origine.
"""

import re
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

# Seuls ces fichiers transitent : rien d'autre ne doit passer par le relais
EXTENSIONS_AUTORISEES = (".m3u8", ".ts", ".m4s", ".mp4", ".aac", ".key")

TYPES_MIME = {
    ".m3u8": "application/vnd.apple.mpegurl",
    ".ts": "video/mp2t",
    ".m4s": "video/iso.segment",
    ".mp4": "video/mp4",
    ".aac": "audio/aac",
    ".key": "application/octet-stream",
}

DELAI = 15  # secondes ; un segment tarde rarement plus


def est_flux_direct(valeur: str) -> bool:
    """Vrai si la valeur ressemble à une adresse de flux HLS."""
    if not valeur:
        return False
    valeur = valeur.strip().lower()
    return valeur.startswith(("http://", "https://")) and ".m3u8" in valeur


def base_du_flux(url_flux: str) -> str:
    """Dossier contenant la playlist, pour résoudre les chemins relatifs."""
    return url_flux.rsplit("/", 1)[0] + "/"


def chemin_relatif(url_flux: str) -> str:
    """Nom du fichier de playlist principal (souvent « playlist.m3u8 »)."""
    return url_flux.rsplit("/", 1)[-1]


def _extension(chemin: str) -> str:
    chemin = chemin.split("?", 1)[0]
    point = chemin.rfind(".")
    return chemin[point:].lower() if point != -1 else ""


def chemin_autorise(chemin: str) -> bool:
    """Refuse tout ce qui n'est pas un fichier de flux, et toute remontée.

    « ../ » permettrait d'atteindre d'autres dossiers du serveur d'origine :
    le relais deviendrait un proxy ouvert utilisable par n'importe qui.
    """
    if not chemin or ".." in chemin or chemin.startswith("/"):
        return False
    return _extension(chemin) in EXTENSIONS_AUTORISEES


def type_mime(chemin: str) -> str:
    return TYPES_MIME.get(_extension(chemin), "application/octet-stream")


def recuperer(url: str):
    """Télécharge une ressource du flux. Renvoie (contenu, type) ou None."""
    try:
        requete = Request(url, headers={"User-Agent": "DialawTV-Relais/1.0"})
        with urlopen(requete, timeout=DELAI) as reponse:
            return reponse.read(), reponse.headers.get("Content-Type", "")
    except (HTTPError, URLError, OSError):
        return None


def reecrire_playlist(contenu: bytes, prefixe_relais: str) -> bytes:
    """Réécrit les URL d'une playlist pour qu'elles passent par le relais.

    Une playlist HLS renvoie vers d'autres fichiers (sous-playlists, segments).
    Sans réécriture, le navigateur irait les chercher directement sur le
    serveur d'origine — en HTTP, donc bloqué, et l'adresse serait exposée.
    """
    lignes = contenu.decode("utf-8", "replace").splitlines()
    sortie = []

    for ligne in lignes:
        depouillee = ligne.strip()

        # Les clés de chiffrement sont référencées dans une directive
        if depouillee.startswith("#EXT-X-KEY") and 'URI="' in depouillee:
            depouillee = re.sub(
                r'URI="([^"]+)"',
                lambda m: f'URI="{prefixe_relais}{_nom_seul(m.group(1))}"',
                depouillee,
            )
            sortie.append(depouillee)
            continue

        # Les autres directives et les lignes vides passent telles quelles
        if not depouillee or depouillee.startswith("#"):
            sortie.append(ligne)
            continue

        sortie.append(prefixe_relais + _nom_seul(depouillee))

    return ("\n".join(sortie) + "\n").encode("utf-8")


def _nom_seul(reference: str) -> str:
    """Ne garde que le nom du fichier, même si la référence est absolue."""
    reference = reference.strip()
    if reference.startswith(("http://", "https://")):
        return urlparse(reference).path.rsplit("/", 1)[-1]
    return reference.rsplit("/", 1)[-1]


def url_absolue(url_flux: str, chemin: str) -> str:
    """Adresse réelle d'une ressource, à partir du dossier de la playlist."""
    return urljoin(base_du_flux(url_flux), chemin)
