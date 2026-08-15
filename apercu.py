"""Génération de l'image d'aperçu partagée sur WhatsApp.

Quand un lien est envoyé dans une conversation, WhatsApp va chercher une
image pour l'afficher au-dessus. Sans elle, le message n'est qu'une adresse
nue — nettement moins engageant.

L'image est fabriquée à partir des réglages du direct : titre, prix, marque.
Elle est donc toujours à jour, sans qu'aucun fichier ne soit à téléverser.

Elle ne contient volontairement **aucune référence à YouTube** : la miniature
d'origine trahirait l'identifiant du direct non répertorié, que n'importe
quel destinataire pourrait alors ouvrir sans payer.
"""

import io

from PIL import Image, ImageDraw, ImageFont

# Dimensions attendues par WhatsApp, Facebook et consorts
LARGEUR, HAUTEUR = 1200, 630

# Palette reprise de la feuille de style du site
FOND = (11, 13, 18)
FOND_HAUT = (22, 27, 39)
ACCENT = (245, 177, 61)
TEXTE = (233, 237, 245)
TEXTE_DOUX = (152, 162, 184)
ROUGE = (239, 71, 87)


def _police(taille: int, gras: bool = False):
    """Police système, avec repli sur la police par défaut de Pillow.

    Les polices disponibles diffèrent entre un poste Windows et le serveur
    Linux : on essaie plusieurs noms avant d'abandonner.
    """
    candidats = (
        ["DejaVuSans-Bold.ttf", "arialbd.ttf", "Arial_Bold.ttf"]
        if gras else
        ["DejaVuSans.ttf", "arial.ttf", "Arial.ttf"]
    )
    for nom in candidats:
        try:
            return ImageFont.truetype(nom, taille)
        except OSError:
            continue
    return ImageFont.load_default()


def _couper_lignes(texte, police, largeur_max, dessin, max_lignes=2):
    """Découpe un titre en lignes qui tiennent dans la largeur donnée."""
    mots = texte.split()
    lignes, courante = [], ""

    for mot in mots:
        essai = (courante + " " + mot).strip()
        if dessin.textlength(essai, font=police) <= largeur_max:
            courante = essai
        else:
            if courante:
                lignes.append(courante)
            courante = mot
            if len(lignes) == max_lignes:
                break

    if courante and len(lignes) < max_lignes:
        lignes.append(courante)

    # Titre trop long : on tronque la dernière ligne proprement
    if len(lignes) == max_lignes and len(" ".join(lignes)) < len(texte):
        derniere = lignes[-1]
        while (dessin.textlength(derniere + "…", font=police) > largeur_max
               and len(derniere) > 1):
            derniere = derniere[:-1]
        lignes[-1] = derniere.rstrip() + "…"

    return lignes or [texte[:40]]


def construire(titre: str, prix: str, devise: str, marque: str = "DIALAW TV") -> bytes:
    """Fabrique l'image d'aperçu et la renvoie en PNG."""
    image = Image.new("RGB", (LARGEUR, HAUTEUR), FOND)
    dessin = ImageDraw.Draw(image)

    # Dégradé vertical discret, dans l'esprit sombre du site
    for y in range(HAUTEUR):
        melange = y / HAUTEUR
        dessin.line(
            [(0, y), (LARGEUR, y)],
            fill=(
                int(FOND_HAUT[0] + (FOND[0] - FOND_HAUT[0]) * melange),
                int(FOND_HAUT[1] + (FOND[1] - FOND_HAUT[1]) * melange),
                int(FOND_HAUT[2] + (FOND[2] - FOND_HAUT[2]) * melange),
            ),
        )

    # Filet doré sur le bord gauche, signature visuelle de la marque
    dessin.rectangle([0, 0, 12, HAUTEUR], fill=ACCENT)

    marge = 80

    # Bandeau « EN DIRECT » avec sa pastille rouge
    police_etiquette = _police(26, gras=True)
    dessin.ellipse([marge, 74, marge + 18, 92], fill=ROUGE)
    dessin.text((marge + 32, 70), "EN DIRECT", font=police_etiquette, fill=ROUGE)

    # Titre de l'émission, sur deux lignes au plus
    police_titre = _police(74, gras=True)
    lignes = _couper_lignes(titre, police_titre, LARGEUR - 2 * marge, dessin)
    y = 170
    for ligne in lignes:
        dessin.text((marge, y), ligne, font=police_titre, fill=TEXTE)
        y += 92

    # Prix, l'information qui décide de l'achat
    police_prix = _police(88, gras=True)
    police_devise = _police(38, gras=True)
    y_prix = HAUTEUR - 210
    dessin.text((marge, y_prix), str(prix), font=police_prix, fill=ACCENT)
    largeur_prix = dessin.textlength(str(prix), font=police_prix)
    dessin.text((marge + largeur_prix + 16, y_prix + 44), devise,
                font=police_devise, fill=ACCENT)

    # Mode d'emploi en une ligne
    police_pied = _police(30)
    dessin.text((marge, HAUTEUR - 92),
                "Paiement Wave · Mot de passe envoyé sur WhatsApp",
                font=police_pied, fill=TEXTE_DOUX)

    # Marque en haut à droite
    police_marque = _police(34, gras=True)
    largeur_marque = dessin.textlength(marque, font=police_marque)
    dessin.text((LARGEUR - marge - largeur_marque, 70), marque,
                font=police_marque, fill=TEXTE)

    tampon = io.BytesIO()
    image.save(tampon, format="PNG", optimize=True)
    return tampon.getvalue()
